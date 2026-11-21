import math
from datetime import date, timedelta

import pytest

from stockanalysis import options as opt

TODAY = date(2026, 11, 19)
SETTINGS = {"budget": 10_000.0, "max_position_pct": 20.0, "options_enabled": True, "option_risk_pct": 3.0}
EXPIRIES = ["2026-11-27", "2026-12-18", "2026-12-31", "2027-01-15", "2027-03-19"]


def chain(spot=100.0, vol=0.30, step=2.5, markup=1.0):
    """A Black-Scholes chain priced at `vol`, quoted with IV = vol * markup."""
    def build(expiry):
        t = (date.fromisoformat(expiry) - TODAY).days / 365
        out = []
        for i in range(-12, 13):
            strike = spot + i * step
            for kind in ("call", "put"):
                fair = opt.bs_price(spot, strike, t, vol * markup, kind)
                if fair < 0.05:
                    continue
                out.append({"contract": f"X{kind}{strike}", "type": kind, "strike": strike, "expiry": expiry,
                            "bid": round(fair * 0.98, 2), "ask": round(fair * 1.02, 2), "last": round(fair, 2),
                            "volume": 500, "open_interest": 2000, "iv": vol * markup})
        return out
    return build


def recommend(action, **kw):
    args = dict(spot=100.0, action=action, expirations=EXPIRIES, chain_for=chain(), hv30=0.30,
                settings=SETTINGS, cash=10_000.0, today=TODAY)
    args.update(kw)
    return opt.recommend(**args)


def test_black_scholes_basics():
    call = opt.bs_delta(100, 100, 0.25, 0.3, "call")
    put = opt.bs_delta(100, 100, 0.25, 0.3, "put")
    assert 0.5 < call < 0.6 and math.isclose(call - put, 1.0)
    # put-call parity
    c, p = opt.bs_price(100, 95, 0.5, 0.25, "call"), opt.bs_price(100, 95, 0.5, 0.25, "put")
    assert math.isclose(c - p, 100 - 95 * math.exp(-opt.RISK_FREE * 0.5), rel_tol=1e-9)
    assert opt.bs_delta(100, 100, 0, 0.3, "call") == 0.0


def test_expiry_prefers_monthly_near_45_days():
    assert opt.pick_expiry(EXPIRIES, TODAY) == ("2027-01-15", 57)
    assert opt.pick_expiry(["2026-11-27", "2026-12-31"], TODAY) == ("2026-12-31", 42)
    assert opt.pick_expiry(["2026-11-27"], TODAY) == ("2026-11-27", 8)
    assert opt.pick_expiry([], TODAY) is None
    assert opt.pick_expiry(["2026-11-01"], TODAY) is None  # already expired


def test_neutral_signal_means_no_options_trade():
    out = recommend("hold")
    assert out["ideas"] == [] and "neutral" in out["notes"][0]


def test_options_can_be_switched_off():
    out = recommend("buy", settings={**SETTINGS, "options_enabled": False})
    assert out["ideas"] == [] and not out["enabled"]


def test_bullish_with_room_in_the_budget_buys_a_call_near_60_delta():
    out = recommend("buy", settings={**SETTINGS, "budget": 100_000.0})
    top = out["ideas"][0]
    assert top["kind"] == "long_call" and top["primary"]
    leg = top["legs"][0]
    assert leg["action"] == "buy" and leg["type"] == "call" and abs(leg["delta"] - 0.60) < 0.08
    assert top["contracts"] >= 1 and top["total_cost"] <= 3000.0
    assert top["max_loss"] == top["net_cost"]
    assert out["dte"] == 57 and out["iv_regime"] == "normal"
    assert {i["kind"] for i in out["ideas"]} == {"long_call", "bull_call_spread"}


def test_small_budget_gets_a_spread_that_fits():
    out = recommend("buy")  # $300 of options risk; a 0.60-delta call costs far more
    top = out["ideas"][0]
    assert top["kind"] == "bull_call_spread"
    assert top["affordable"] and top["net_cost"] <= 300.0
    buy, sell = top["legs"]
    assert buy["action"] == "buy" and sell["action"] == "sell" and sell["strike"] > buy["strike"]
    width = (sell["strike"] - buy["strike"]) * 100
    assert math.isclose(top["max_loss"] + top["max_profit"], width, abs_tol=0.01)
    call = next(i for i in out["ideas"] if i["kind"] == "long_call")
    assert not call["affordable"] and "above your" in call["warnings"][0]


def test_bearish_signal_recommends_puts():
    out = recommend("sell", settings={**SETTINGS, "budget": 100_000.0})
    top = out["ideas"][0]
    assert top["kind"] == "long_put" and top["direction"] == "bearish"
    assert -0.68 < top["legs"][0]["delta"] < -0.52
    spread = next(i for i in out["ideas"] if i["kind"] == "bear_put_spread")
    assert spread["legs"][1]["strike"] < spread["legs"][0]["strike"]


def test_earnings_this_week_leads_with_a_spread_and_warns():
    earnings = TODAY + timedelta(days=3)
    out = recommend("buy", settings={**SETTINGS, "budget": 100_000.0}, next_earnings=earnings)
    assert out["ideas"][0]["kind"] == "bull_call_spread"
    call = next(i for i in out["ideas"] if i["kind"] == "long_call")
    assert "Earnings in 3 day" in call["warnings"][0]
    assert any("fall before this expiry" in n for n in out["notes"])


def test_rich_volatility_prefers_selling_a_cash_secured_put():
    rich = dict(chain_for=chain(markup=1.6), settings={**SETTINGS, "budget": 100_000.0}, cash=100_000.0)
    out = recommend("buy", **rich)
    assert out["iv_regime"] == "rich"
    top = out["ideas"][0]
    assert top["kind"] == "cash_secured_put"
    leg = top["legs"][0]
    assert leg["action"] == "sell" and leg["type"] == "put" and leg["strike"] < 100
    assert top["collateral"] == leg["strike"] * 100
    # Without the cash for 100 shares, no put-selling idea.
    poor = recommend("buy", chain_for=chain(markup=1.6))
    assert all(i["kind"] != "cash_secured_put" for i in poor["ideas"])


def test_covered_call_when_holding_100_shares_and_neutral():
    out = recommend("hold", position={"shares": 250, "entry_price": 90.0})
    top = out["ideas"][0]
    assert top["kind"] == "covered_call" and top["contracts"] == 2
    assert top["legs"][0]["strike"] > 100


def test_missing_quotes_fall_back_to_last_price_with_a_warning():
    def after_hours(expiry):
        rows = chain()(expiry)
        for r in rows:
            r["bid"] = r["ask"] = 0.0
            r["iv"] = 0.0001
        return rows
    out = recommend("buy", chain_for=after_hours, settings={**SETTINGS, "budget": 100_000.0})
    top = out["ideas"][0]
    assert top["legs"][0]["iv"] == pytest.approx(0.30)  # falls back to realised volatility
    assert any("No live bid/ask" in w for w in top["warnings"])


def test_no_chain_is_reported_not_raised():
    assert "No listed options" in recommend("buy", expirations=[])["notes"][0]
    assert recommend("buy", chain_for=lambda e: [])["ideas"] == []
