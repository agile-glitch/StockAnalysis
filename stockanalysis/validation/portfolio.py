"""Portfolio test: start with money and follow the rules, day by day.

Each evening the rules look at every stock in the universe. New Buy signals
are bought at the next morning's open, sized the way the app sizes trades
(risk a fixed share of the account between entry and a 2.5-ATR stop, capped
per position and by cash). Positions are sold at the next open when the
rules say so: stop or trailing stop hit, price below the 200-day average, or
a Sell signal. Every buy and sell pays a cost (spread and slippage).

Nothing here looks ahead: decisions use only data up to that day's close.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Rules:
    name: str = "App rules (baseline)"
    buy_score: float = 25.0            # buy when the score reaches this (trend gate always applies)
    max_positions: int = 10
    risk_per_trade: float = 0.01       # fraction of equity lost if the stop is hit
    max_position: float = 0.20         # largest position, fraction of equity
    stop_atr: float = 2.5
    trailing: bool = True              # chandelier exit (3 ATR under the 22-day high)
    exit_on_trend_break: bool = True   # sell when the close falls under the 200-day average
    sell_score: float = -25.0          # sell when the score falls to this
    market_filter: bool = False        # no new buys while SPY is under its 200-day average
    rank_by: str = "score"             # which candidates win when slots are scarce
    entry: str = "any"                 # "any" day in Buy state, or only on a "pullback" (2-day RSI < 10)
    cost_bps: float = 10.0             # per side
    cash_interest: bool = True         # idle cash earns the 3-month T-bill rate
    notes: str = ""

    def describe(self) -> dict:
        return asdict(self)


@dataclass
class Panel:
    """Aligned date x symbol matrices for fast simulation."""
    dates: pd.DatetimeIndex
    symbols: list[str]
    open: np.ndarray
    close: np.ndarray
    score: np.ndarray
    action: np.ndarray
    atr: np.ndarray
    chandelier: np.ndarray
    sma200: np.ndarray
    rsi2: np.ndarray
    momentum: np.ndarray
    spy_close: np.ndarray
    spy_sma200: np.ndarray
    cash_rate: np.ndarray | None = None   # daily interest rate on cash (decimal)
    spy_mom12: np.ndarray | None = None   # S&P 500 return over the last 252 trading days
    cash_12m: np.ndarray | None = None    # T-bill return over the same 252 days
    spy_vol: np.ndarray | None = None     # S&P 500 annualised volatility, last 20 days
    extra: dict = field(default_factory=dict)

    @classmethod
    def build(cls, frames: dict[str, pd.DataFrame], spy: pd.DataFrame,
              tbill: pd.Series | None = None) -> "Panel":
        dates = spy.index
        symbols = sorted(frames)

        def mat(col):
            return np.column_stack([frames[s][col].reindex(dates).to_numpy(dtype=float) for s in symbols])

        spy_sma = spy["close"].rolling(200, min_periods=200).mean()
        cash_rate = _daily_cash_rate(dates, tbill)
        spy_mom12 = (spy["close"] / spy["close"].shift(252) - 1).to_numpy(dtype=float)
        growth = np.cumprod(1 + cash_rate)
        cash_12m = np.full(len(dates), np.nan)
        cash_12m[252:] = growth[252:] / growth[:-252] - 1
        spy_vol = (np.log(spy["close"]).diff().rolling(20).std() * math.sqrt(252)).to_numpy(dtype=float)
        return cls(dates=dates, symbols=symbols, open=mat("open"), close=mat("close"), score=mat("score"),
                   action=mat("action"), atr=mat("atr14"), chandelier=mat("chandelier"), sma200=mat("sma200"),
                   rsi2=mat("rsi2"), momentum=mat("mom_12_1"), spy_close=spy["close"].to_numpy(dtype=float),
                   spy_sma200=spy_sma.to_numpy(dtype=float), cash_rate=cash_rate, spy_mom12=spy_mom12,
                   cash_12m=cash_12m, spy_vol=spy_vol)

    def cash_series(self) -> pd.Series | None:
        return None if self.cash_rate is None else pd.Series(self.cash_rate, index=self.dates)

    def window(self, start: str, end: str | None = None) -> tuple[int, int]:
        lo = int(self.dates.searchsorted(pd.Timestamp(start)))
        hi = int(self.dates.searchsorted(pd.Timestamp(end), side="right")) if end else len(self.dates)
        return lo, hi


def _daily_cash_rate(dates: pd.DatetimeIndex, tbill: pd.Series | None) -> np.ndarray:
    if tbill is None or tbill.empty:
        return np.zeros(len(dates))
    yearly = tbill.reindex(dates, method="ffill").fillna(0.0).to_numpy(dtype=float) / 100.0
    return np.clip(yearly, 0, None) / 252.0


def simulate(p: Panel, rules: Rules, start: str, end: str | None = None, capital: float = 100_000.0) -> dict:
    lo, hi = p.window(start, end)
    n = p.close.shape[1]
    cost = rules.cost_bps / 10_000.0
    cash = capital
    shares = np.zeros(n)
    stop = np.full(n, np.nan)
    entry_px = np.full(n, np.nan)
    entry_day = np.zeros(n, dtype=int)
    last_px = np.full(n, np.nan)
    pending_buy: dict[int, tuple[int, float]] = {}   # symbol -> (shares, stop)
    pending_sell: set[int] = set()
    equity_curve, invested_curve = [], []
    trades: list[dict] = []

    for i in range(lo, hi):
        o, c = p.open[i], p.close[i]
        if rules.cash_interest and p.cash_rate is not None and cash > 0:
            cash *= 1 + p.cash_rate[i]
        # 1. Orders decided last night fill at this morning's open.
        for j in list(pending_sell):
            px = o[j] if not math.isnan(o[j]) else last_px[j]
            if math.isnan(px):
                continue
            proceeds = shares[j] * px * (1 - cost)
            cash += proceeds
            trades.append({"symbol": p.symbols[j], "entry_date": p.dates[entry_day[j]].date().isoformat(),
                           "exit_date": p.dates[i].date().isoformat(), "entry": float(entry_px[j]),
                           "exit": float(px), "days": int(i - entry_day[j]),
                           "return_pct": float((px * (1 - cost)) / (entry_px[j] * (1 + cost)) * 100 - 100)})
            shares[j] = 0.0
            stop[j] = entry_px[j] = np.nan
            pending_sell.discard(j)
        for j, (qty, stp) in list(pending_buy.items()):
            px = o[j]
            if math.isnan(px) or qty <= 0:
                continue
            qty = min(qty, math.floor(cash / (px * (1 + cost))))
            if qty <= 0:
                continue
            cash -= qty * px * (1 + cost)
            shares[j], stop[j], entry_px[j], entry_day[j] = qty, stp, px, i
        pending_buy.clear()

        # 2. Mark to market at the close.
        valid = ~np.isnan(c)
        last_px[valid] = c[valid]
        held = shares > 0
        holdings = float(np.nansum(shares[held] * last_px[held]))
        equity = cash + holdings
        equity_curve.append(equity)
        invested_curve.append(holdings / equity if equity > 0 else 0.0)

        # 3. Exits for tomorrow.
        for j in np.flatnonzero(held):
            if math.isnan(c[j]):
                continue
            level = stop[j]
            if rules.trailing and not math.isnan(p.chandelier[i, j]):
                level = max(level, p.chandelier[i, j]) if not math.isnan(level) else p.chandelier[i, j]
            exit_now = (not math.isnan(level) and c[j] < level)
            if rules.exit_on_trend_break and not math.isnan(p.sma200[i, j]) and c[j] < p.sma200[i, j]:
                exit_now = True
            if not math.isnan(p.score[i, j]) and p.score[i, j] <= rules.sell_score:
                exit_now = True
            if exit_now:
                pending_sell.add(j)

        # 4. New buys for tomorrow.
        if i == hi - 1:
            break
        slots = rules.max_positions - int(held.sum()) + len(pending_sell)
        if slots <= 0:
            continue
        if rules.market_filter and not (p.spy_close[i] > p.spy_sma200[i]):
            continue
        cand = (~held) & (p.action[i] >= 1) & (p.score[i] >= rules.buy_score) & valid & ~np.isnan(p.atr[i])
        if rules.entry == "pullback":
            cand &= p.rsi2[i] < 10
        idx = np.flatnonzero(cand)
        if idx.size == 0:
            continue
        key = p.momentum[i, idx] if rules.rank_by == "momentum" else p.score[i, idx]
        order = idx[np.argsort(-np.nan_to_num(key, nan=-1e9))][:slots]
        free_cash = cash
        for j in order:
            px, atr = c[j], p.atr[i, j]
            dist = rules.stop_atr * atr
            if dist <= 0 or px <= 0:
                continue
            qty = math.floor(min(equity * rules.risk_per_trade / dist, equity * rules.max_position / px,
                                 free_cash / (px * (1 + cost))))
            if qty <= 0:
                continue
            free_cash -= qty * px * (1 + cost)
            pending_buy[j] = (qty, px - dist)

    # Close what is still open at the last price, for the statistics only.
    open_trades = [{"symbol": p.symbols[j], "entry_date": p.dates[entry_day[j]].date().isoformat(),
                    "return_pct": float(last_px[j] / entry_px[j] * 100 - 100)} for j in np.flatnonzero(shares > 0)]
    curve = pd.Series(equity_curve, index=p.dates[lo:lo + len(equity_curve)])
    return {"rules": rules.describe(), "curve": curve, "invested": float(np.mean(invested_curve)) if invested_curve else 0.0,
            "trades": trades, "open_trades": open_trades}


def curve_metrics(curve: pd.Series, cash_rate: pd.Series | None = None) -> dict:
    """Return, risk and Sharpe statistics for an equity curve.

    The Sharpe ratio uses returns above the T-bill rate (`cash_rate`, daily
    decimal), the standard definition. Without that, a strategy that sits in
    interest-earning cash looks almost risk-free and scores far too high.
    """
    curve = curve.dropna()
    if len(curve) < 2 or curve.iloc[0] <= 0:
        return {}
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    total = curve.iloc[-1] / curve.iloc[0] - 1
    daily = curve.pct_change().dropna()
    excess = daily
    if cash_rate is not None:
        excess = daily - cash_rate.reindex(daily.index).fillna(0.0)
    vol = daily.std() * math.sqrt(252)
    peak = curve.cummax()
    dd = (curve / peak - 1).min()
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    total, vol, dd, cagr = float(total), float(vol), float(dd), float(cagr)
    return {
        "total_return_pct": round(total * 100, 1),
        "cagr_pct": round(cagr * 100, 2),
        "volatility_pct": round(vol * 100, 1),
        "sharpe": round(float(excess.mean() / excess.std() * math.sqrt(252)), 2) if excess.std() > 0 else None,
        "max_drawdown_pct": round(dd * 100, 1),
        "return_to_drawdown": round(cagr / abs(dd), 2) if dd < 0 else None,
        "years": round(years, 1),
    }


def trade_metrics(result: dict) -> dict:
    trades = result["trades"]
    if not trades:
        return {"trades": 0}
    r = np.array([t["return_pct"] for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(r) * 100, 1),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else None,
        "avg_trade_pct": round(float(r.mean()), 2),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
        "avg_days_held": round(float(np.mean([t["days"] for t in trades])), 1),
        "invested_pct": round(result["invested"] * 100, 1),
    }


def benchmarks(p: Panel, start: str, end: str | None = None) -> dict[str, pd.Series]:
    """S&P 500 (SPY) and an equal-weight buy-and-hold of the same stocks."""
    lo, hi = p.window(start, end)
    spy = pd.Series(p.spy_close[lo:hi], index=p.dates[lo:hi])
    rets = pd.DataFrame(p.close[lo:hi], index=p.dates[lo:hi]).pct_change(fill_method=None)
    ew = (1 + rets.mean(axis=1, skipna=True).fillna(0)).cumprod()
    return {"spy": spy / spy.iloc[0], "equal_weight": ew / ew.iloc[0]}


def yearly_returns(curve: pd.Series) -> dict[str, float]:
    yearly = curve.groupby(curve.index.year).agg(["first", "last"])
    prev_last = None
    out = {}
    for year, row in yearly.iterrows():
        base = prev_last if prev_last is not None else row["first"]
        out[str(year)] = round(float(row["last"] / base - 1) * 100, 1)
        prev_last = row["last"]
    return out


def variant(base: Rules, **changes) -> Rules:
    return replace(base, **changes)


@dataclass(frozen=True)
class MonthlyRules:
    """Hold a basket, rebalanced on the first trading day of each month.

    select:
      "all"          every stock (with market_filter=False this is buy-and-hold)
      "buy"          stocks the app rates Buy or Strong buy
      "not_sell"     every stock the app does not rate Sell
      "above_200"    stocks above their own 200-day average (Faber, per stock)
      "top_momentum" the top_n stocks by 12-month momentum, among those above their 200-day average
      "top_score"    the top_n stocks by app score, among those the app rates Buy
    market_filter: hold cash (earning T-bill interest) while the S&P 500 is
      below its 200-day average at the month-end check.
    """
    name: str
    select: str = "buy"
    top_n: int = 15
    max_weight: float = 0.10
    market_filter: bool = False
    cost_bps: float = 10.0
    cash_interest: bool = True
    notes: str = ""
    # Market regime (used when market_filter is True):
    #   "sma200"  S&P 500 above its 200-day average
    #   "abs_mom" S&P 500 12-month return above T-bills (Antonacci's absolute momentum)
    #   "dual"    risk-off only when BOTH say so (fewer whipsaws)
    #   "band"    200-day average with a 3% buffer: leave below 97% of it, return above it
    regime: str = "sma200"
    risk_off_exposure: float = 0.0   # share of the basket kept when risk-off (0 = all cash)
    vol_target: float | None = None  # scale exposure to this annual volatility (e.g. 0.15)

    def describe(self) -> dict:
        return {"mode": "monthly", **asdict(self)}


def market_risk_on(p: "Panel", rules: "MonthlyRules", i: int, was_on: bool) -> bool:
    above = p.spy_close[i] > p.spy_sma200[i]
    mom_ok = (p.spy_mom12 is not None and not math.isnan(p.spy_mom12[i])
              and p.spy_mom12[i] > (p.cash_12m[i] if not math.isnan(p.cash_12m[i]) else 0.0))
    if rules.regime == "sma200":
        return bool(above)
    if rules.regime == "abs_mom":
        return bool(mom_ok)
    if rules.regime == "dual":
        return bool(above or mom_ok)
    if rules.regime == "band":
        if was_on:
            return bool(p.spy_close[i] > 0.97 * p.spy_sma200[i])
        return bool(above)
    raise ValueError(rules.regime)


def exposure(p: "Panel", rules: "MonthlyRules", i: int, was_on: bool) -> tuple[float, bool]:
    """Share of equity to hold in stocks, and whether the market is 'risk-on'."""
    on = True
    if rules.market_filter:
        if math.isnan(p.spy_sma200[i]):
            on = True
        else:
            on = market_risk_on(p, rules, i, was_on)
    level = 1.0 if on else rules.risk_off_exposure
    if rules.vol_target and p.spy_vol is not None and not math.isnan(p.spy_vol[i]) and p.spy_vol[i] > 0:
        level *= min(1.0, rules.vol_target / p.spy_vol[i])
    return level, on


def _month_starts(dates: pd.DatetimeIndex, lo: int, hi: int) -> set[int]:
    months = dates[lo:hi].to_period("M")
    return {lo + k for k in range(1, hi - lo) if months[k] != months[k - 1]} | {lo + 1}


def _select(p: Panel, rules: MonthlyRules, i: int) -> np.ndarray:
    c = p.close[i]
    valid = ~np.isnan(c) & ~np.isnan(p.sma200[i])
    if rules.select == "all":
        mask = valid
    elif rules.select == "buy":
        mask = valid & (p.action[i] >= 1)
    elif rules.select == "not_sell":
        mask = valid & (p.action[i] >= 0)
    elif rules.select == "above_200":
        mask = valid & (c > p.sma200[i])
    elif rules.select == "top_momentum":
        mask = valid & (c > p.sma200[i]) & ~np.isnan(p.momentum[i])
        idx = np.flatnonzero(mask)
        return idx[np.argsort(-p.momentum[i, idx])][:rules.top_n]
    elif rules.select == "top_score":
        mask = valid & (p.action[i] >= 1)
        idx = np.flatnonzero(mask)
        return idx[np.argsort(-p.score[i, idx])][:rules.top_n]
    else:
        raise ValueError(rules.select)
    return np.flatnonzero(mask)


def simulate_monthly(p: Panel, rules: MonthlyRules, start: str, end: str | None = None,
                     capital: float = 100_000.0) -> dict:
    lo, hi = p.window(start, end)
    n = p.close.shape[1]
    cost = rules.cost_bps / 10_000.0
    cash, shares = capital, np.zeros(n)
    last_px = np.full(n, np.nan)
    entry_px, entry_day = np.full(n, np.nan), np.zeros(n, dtype=int)
    rebalance_days = _month_starts(p.dates, lo, hi)
    curve, invested, trades = [], [], []
    target_idx: np.ndarray | None = None
    target_level, risk_on = 1.0, True

    for i in range(lo, hi):
        if rules.cash_interest and p.cash_rate is not None and cash > 0:
            cash *= 1 + p.cash_rate[i]
        o = p.open[i]
        if i in rebalance_days and target_idx is not None:
            px = np.where(np.isnan(o), last_px, o)
            held_value = float(np.nansum(shares * np.nan_to_num(px)))
            equity = cash + held_value
            weight = min(rules.max_weight, 1.0 / len(target_idx)) * target_level if len(target_idx) else 0.0
            target = np.zeros(n)
            for j in target_idx:
                if not np.isnan(px[j]) and px[j] > 0:
                    target[j] = math.floor(equity * weight / px[j])
            for j in np.flatnonzero((shares > 0) | (target > 0)):
                delta = target[j] - shares[j]
                if delta == 0 or np.isnan(px[j]):
                    continue
                if shares[j] > 0 and target[j] == 0:  # position closed
                    trades.append({"symbol": p.symbols[j], "entry_date": p.dates[entry_day[j]].date().isoformat(),
                                   "exit_date": p.dates[i].date().isoformat(), "days": int(i - entry_day[j]),
                                   "return_pct": float(px[j] / entry_px[j] * 100 - 100 - 2 * rules.cost_bps / 100)})
                if shares[j] == 0 and target[j] > 0:
                    entry_px[j], entry_day[j] = px[j], i
                cash -= delta * px[j] + abs(delta) * px[j] * cost
                shares[j] = target[j]
        c = p.close[i]
        ok = ~np.isnan(c)
        last_px[ok] = c[ok]
        holdings = float(np.nansum(shares * np.nan_to_num(last_px)))
        equity = cash + holdings
        curve.append(equity)
        invested.append(holdings / equity if equity > 0 else 0.0)
        # Decide next month's basket from this close (it trades at the next open).
        if (i + 1) in rebalance_days:
            target_idx = _select(p, rules, i)
            target_level, risk_on = exposure(p, rules, i, risk_on)
    series = pd.Series(curve, index=p.dates[lo:lo + len(curve)])
    return {"rules": rules.describe(), "curve": series, "invested": float(np.mean(invested)) if invested else 0.0,
            "trades": trades, "open_trades": []}


def run_rules(p: Panel, rules, start: str, end: str | None = None) -> dict:
    if isinstance(rules, MonthlyRules):
        return simulate_monthly(p, rules, start, end)
    return simulate(p, rules, start, end)
