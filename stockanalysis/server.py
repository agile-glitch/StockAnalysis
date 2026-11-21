"""HTTP API and static web UI."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Database, SettingsError
from .engine import Engine, Scheduler
from .insiders import InsiderService, InsiderWatcher
from .providers import CachedProvider, ProviderError, make_provider
from .push import Pusher
from .sec import SecClient

STATIC_DIR = Path(__file__).resolve().parent / "static"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class SymbolIn(BaseModel):
    symbol: str


class PositionIn(BaseModel):
    symbol: str
    shares: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop: float | None = Field(default=None, ge=0)


class ReadIn(BaseModel):
    ids: list[int] | None = None


class PushTestIn(BaseModel):
    url: str | None = None

INSIDER_SETTINGS = {"sec_contact", "insider_poll_minutes", "insider_alert_sells", "insider_sell_min_value",
                    "insider_market_alerts", "insider_market_min_value"}


def _symbol(raw: str) -> str:
    symbol = (raw or "").strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Enter a ticker symbol such as AAPL.")
    return symbol


def create_app(db: Database | None = None, provider: CachedProvider | None = None, demo: bool = False,
               background: bool = True, sec_client: SecClient | None = None, push_opener=None) -> FastAPI:
    db = db or Database()
    provider = provider or make_provider(demo=demo)
    # SEC filings are real even in demo mode, so insider alerts work in both.
    sec_client = sec_client or SecClient(lambda: db.get_settings()["sec_contact"])
    insider_service = InsiderService(db, sec_client)
    engine = Engine(db, provider, insiders=insider_service)
    insider_service.on_update = lambda symbol: engine.refresh_symbol(symbol)
    pusher = Pusher(db.get_settings, opener=push_opener)
    db.on_notification(pusher)
    scheduler = Scheduler(engine) if background else None
    watcher = InsiderWatcher(insider_service) if background else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scheduler:
            scheduler.start()
            watcher.start()
        yield
        if scheduler:
            scheduler.stop()
            watcher.stop()

    app = FastAPI(title="StockAnalysis", lifespan=lifespan)
    app.state.engine = engine
    app.state.db = db
    app.state.insiders = insider_service
    app.state.pusher = pusher

    def rescan(force: bool = False):
        if scheduler:
            scheduler.trigger(force=force)
        else:
            engine.scan(force=force)

    # FastAPI runs plain `def` handlers in a thread pool, so slow data calls
    # here do not block other requests.
    @app.get("/api/overview")
    def overview():
        return engine.overview()

    @app.get("/api/stock/{symbol}")
    def stock(symbol: str):
        symbol = _symbol(symbol)
        analysis = engine.analyses.get(symbol)
        if not analysis or analysis.get("error"):
            try:
                analysis = engine.refresh_symbol(symbol, notify=symbol in db.watchlist())
            except ProviderError as exc:
                raise HTTPException(404, str(exc)) from exc
            if analysis.get("error"):
                raise HTTPException(404, analysis["error"])
        return analysis

    @app.get("/api/stock/{symbol}/backtest")
    def backtest(symbol: str):
        try:
            return engine.backtest(_symbol(symbol))
        except ProviderError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/search")
    def search(q: str = ""):
        return provider.search(q.strip()) if q.strip() else []

    @app.post("/api/watchlist")
    def add_symbol(body: SymbolIn):
        symbol = _symbol(body.symbol)
        if symbol in db.watchlist():
            return engine.summary(symbol)
        try:
            provider.history(symbol, "2y")  # confirms the ticker exists before saving it
        except ProviderError as exc:
            raise HTTPException(404, str(exc)) from exc
        db.add_symbol(symbol)
        engine.refresh_symbol(symbol)
        return engine.summary(symbol)

    @app.delete("/api/watchlist/{symbol}")
    def remove_symbol(symbol: str):
        symbol = _symbol(symbol)
        db.remove_symbol(symbol)
        engine.analyses.pop(symbol, None)
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings():
        return db.get_settings()

    @app.put("/api/settings")
    def put_settings(changes: dict):
        try:
            settings = db.update_settings(changes)
        except SettingsError as exc:
            raise HTTPException(400, str(exc)) from exc
        if INSIDER_SETTINGS & set(changes):
            insider_poll()
        # Trade sizes and option picks depend on the budget, so recompute them
        # now. Market data comes from cache, so this is quick.
        engine.scan(wait=True, notify=False)
        return settings

    def insider_poll():
        if watcher:
            watcher.trigger()
        else:
            insider_service.poll()

    @app.get("/api/positions")
    def positions():
        rows = []
        for p in db.positions():
            a = engine.analyses.get(p["symbol"]) or {}
            price = a.get("price")
            rows.append({
                **p,
                "price": price,
                "value": round(p["shares"] * price, 2) if price else None,
                "pnl": round(p["shares"] * (price - p["entry_price"]), 2) if price else None,
                "pnl_pct": round((price / p["entry_price"] - 1) * 100, 1) if price else None,
                "action": a.get("action"),
                "action_label": a.get("action_label"),
                "direction": a.get("direction"),
            })
        return rows

    @app.post("/api/positions")
    def set_position(body: PositionIn):
        symbol = _symbol(body.symbol)
        if symbol not in db.watchlist():
            try:
                provider.history(symbol, "2y")
            except ProviderError as exc:
                raise HTTPException(404, str(exc)) from exc
            db.add_symbol(symbol)
        db.set_position(symbol, body.shares, body.entry_price, body.stop)
        engine.scan(wait=True, notify=False)  # cash available changed, so every plan changes
        return db.position(symbol)

    @app.delete("/api/positions/{symbol}")
    def close_position(symbol: str):
        db.close_position(_symbol(symbol))
        engine.scan(wait=True, notify=False)
        return {"ok": True}

    @app.get("/api/notifications")
    def notifications(after_id: int = 0, limit: int = 200):
        return {"items": db.notifications(limit=min(limit, 500), after_id=after_id), "unread": db.unread_count()}

    @app.post("/api/notifications/read")
    def mark_read(body: ReadIn):
        db.mark_read(body.ids)
        return {"unread": db.unread_count()}

    @app.delete("/api/notifications")
    def clear_notifications():
        db.clear_notifications()
        return {"unread": 0}

    @app.get("/api/news")
    def news():
        return engine.news_feed()

    @app.get("/api/earnings")
    def earnings():
        return engine.earnings_calendar()

    @app.get("/api/insiders")
    def insiders(scope: str = "watchlist", days: int = 14, min_value: float = 0):
        if scope == "market":
            return insider_service.market_buys(days=max(1, min(days, 90)), min_value=max(0.0, min_value))
        return engine.insider_feed()

    @app.get("/api/validation")
    def validation():
        from .validation.run import BUNDLED_REPORT, REPORT_DIR
        path = REPORT_DIR / "report.json"
        if not path.exists():
            path = BUNDLED_REPORT   # the copy shipped with the app
        if not path.exists():
            raise HTTPException(404, "No track record yet. Run: python -m stockanalysis.validation")
        return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/api/validation/stops")
    def validation_stops():
        from .validation.run import REPORT_DIR
        from .validation.stops import BUNDLED_STOPS
        path = REPORT_DIR / "stops.json"
        if not path.exists():
            path = BUNDLED_STOPS
        if not path.exists():
            raise HTTPException(404, "No stop-loss test yet. Run: python -m stockanalysis.validation.stops")
        return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/api/insiders/status")
    def insider_status():
        settings = db.get_settings()
        return {**insider_service.status, "configured": insider_service.configured,
                "market_alerts": settings["insider_market_alerts"],
                "push": {**pusher.status, "enabled": bool(settings["push_url"])}}

    @app.post("/api/insiders/poll")
    def poll_insiders():
        if not insider_service.configured:
            raise HTTPException(400, "Add your name and email under Settings > Insider alerts first.")
        insider_poll()
        return insider_service.status

    @app.post("/api/push/test")
    def push_test(body: PushTestIn):
        try:
            pusher.send_now({"title": "StockAnalysis test alert", "tone": "bullish", "kind": "insider_buy",
                             "body": "Push notifications are working. Insider-trade alerts will arrive here."},
                            url=(body.url or "").strip() or None)
        except Exception as exc:
            raise HTTPException(400, f"Could not send: {exc}") from exc
        return {"ok": True}

    @app.post("/api/scan")
    def scan():
        rescan(force=True)
        return engine.status

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
