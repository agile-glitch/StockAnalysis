"""HTTP API and static web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import hmac

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Database, SettingsError
from .engine import Engine, Scheduler
from .insiders import InsiderService, InsiderWatcher
from .providers import CachedProvider, ProviderError, make_provider
from .push import Pusher
from .sec import SecClient
from .symbols import SYMBOL_RE

STATIC_DIR = Path(__file__).resolve().parent / "static"


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


class LabRunIn(BaseModel):
    symbol: str
    tactic: str
    params: dict = Field(default_factory=dict)

INSIDER_SETTINGS = {"sec_contact", "insider_poll_minutes", "insider_alert_sells", "insider_sell_min_value",
                    "insider_market_alerts", "insider_market_min_value"}


def _symbol(raw: str) -> str:
    symbol = (raw or "").strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Enter a ticker symbol such as AAPL, GLD, GC=F or BTC-USD.")
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

    # Requests relayed by a tunnel or proxy (how TradingView reaches a home
    # computer) come from the internet: let them reach the webhook only, never
    # your positions, settings or alerts.
    FORWARD_HEADERS = ("x-forwarded-for", "forwarded", "cf-connecting-ip", "x-real-ip", "true-client-ip")

    @app.middleware("http")
    async def guard_tunnelled_requests(request: Request, call_next):
        from fastapi.responses import JSONResponse
        relayed = any(h in request.headers for h in FORWARD_HEADERS)
        if relayed and request.url.path != "/api/webhooks/tradingview":
            return JSONResponse({"detail": "Only the TradingView webhook is reachable from the internet."}, status_code=403)
        return await call_next(request)
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

    # ---------------- TradingView ----------------
    def tv_token() -> str:
        token = db.get_settings()["tv_webhook_token"]
        if not token:
            from .tradingview import new_token
            token = db.update_settings({"tv_webhook_token": new_token()})["tv_webhook_token"]
        return token

    @app.get("/api/tradingview/setup")
    def tradingview_setup(request: Request):
        from .tradingview import SUGGESTED_MESSAGE
        base = str(request.base_url).rstrip("/")
        return {"webhook_path": "/api/webhooks/tradingview?token=" + tv_token(),
                "local_url": base + "/api/webhooks/tradingview?token=" + tv_token(),
                "message": SUGGESTED_MESSAGE}

    @app.post("/api/tradingview/token")
    def tradingview_new_token():
        from .tradingview import new_token
        db.update_settings({"tv_webhook_token": new_token()})
        return {"ok": True}

    @app.post("/api/webhooks/tradingview")
    async def tradingview_webhook(request: Request, token: str = ""):
        """Receives TradingView alert webhooks. TradingView cannot send custom
        headers, so the secret travels in the URL; keep the URL private."""
        from .tradingview import MAX_BODY, dedup_key, parse_alert
        expected = db.get_settings()["tv_webhook_token"]
        if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(403, "Wrong or missing token")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "Alert message too long")
        text = raw.decode("utf-8", errors="replace")
        alert = parse_alert(text)
        db.add_notification(symbol=alert["symbol"], kind="tradingview", tone=alert["tone"], title=alert["title"],
                            body=alert["body"], dedup_key=dedup_key(text))
        return {"ok": True}

    @app.get("/api/lab/pine")
    def lab_pine(tactic: str, params: str = "{}"):
        import json as _json

        from .tactics import TACTICS
        from .tradingview import pine_script
        if tactic not in TACTICS:
            raise HTTPException(400, "Unknown tactic")
        try:
            parsed = _json.loads(params)
        except ValueError:
            parsed = {}
        return {"code": pine_script(tactic, parsed if isinstance(parsed, dict) else {})}

    @app.get("/api/tradingview/studies")
    def tradingview_studies(symbol: str, tactic: str = "", params: str = "{}"):
        import json as _json

        from .tactics import TACTICS
        from .tradingview import studies, tv_symbol
        try:
            parsed = _json.loads(params)
        except ValueError:
            parsed = {}
        key = tactic if tactic in TACTICS else None
        return {"symbol": tv_symbol(_symbol(symbol)), "studies": studies(key, parsed if isinstance(parsed, dict) else {})}

    @app.get("/api/trend")
    def trend_overview():
        return engine.trend.snapshot()

    @app.get("/api/markets")
    def markets_overview():
        from .markets_view import overview
        return overview(provider, engine)

    @app.get("/api/lab/tactics")
    def lab_tactics():
        from .lab_runner import tactic_catalog
        return tactic_catalog()

    @app.get("/api/lab/results")
    def lab_results():
        from .lab_runner import load_lab_report
        report = load_lab_report()
        if not report:
            raise HTTPException(404, "No indicator test yet. Run: python -m stockanalysis.validation.lab")
        return report

    @app.post("/api/lab/run")
    def lab_run(body: LabRunIn):
        from . import lab_runner
        from .tactics import TACTICS
        symbol = _symbol(body.symbol)
        if body.tactic not in TACTICS:
            raise HTTPException(400, "Unknown tactic")
        try:
            df = provider.history(symbol, "10y")
        except ProviderError as exc:
            raise HTTPException(404, str(exc)) from exc
        if len(df) < 300:
            raise HTTPException(400, f"{symbol} needs more than a year of history to test.")
        tbill = None
        try:
            tbill = provider.history("^IRX", "10y")["close"]
        except Exception:
            pass
        return {"symbol": symbol, **lab_runner.run(df, body.tactic, body.params, tbill)}

    @app.get("/api/validation/experiments")
    def validation_experiments():
        from .validation.experiments import BUNDLED as EXP_BUNDLED
        from .validation.run import REPORT_DIR
        path = REPORT_DIR / "experiments.json"
        if not path.exists():
            path = EXP_BUNDLED
        if not path.exists():
            raise HTTPException(404, "No experiments yet. Run: python -m stockanalysis.validation.experiments")
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
