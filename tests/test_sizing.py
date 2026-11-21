from stockanalysis.sizing import available_cash, plan_trade

SETTINGS = {"budget": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 20.0}


def test_shares_come_from_risk_and_stop_distance():
    # ATR 2 -> stop 5 below entry; risking $100 buys 20 shares ($1,000, under the $2,000 cap)
    plan = plan_trade(50.0, 2.0, "buy", SETTINGS, cash=10_000)
    assert plan["stop"] == 45.0 and plan["target"] == 60.0
    assert plan["shares"] == 20 and plan["cost"] == 1000.0
    assert plan["risk_amount"] == 100.0 and plan["limited_by"] == "risk"


def test_position_cap_and_cash_limit_the_size():
    capped = plan_trade(100.0, 0.4, "buy", SETTINGS, cash=10_000)  # risk alone would allow 100 shares
    assert capped["shares"] == 20 and capped["limited_by"] == "position cap"
    short_of_cash = plan_trade(100.0, 0.4, "buy", SETTINGS, cash=550)
    assert short_of_cash["shares"] == 5 and short_of_cash["limited_by"] == "cash"


def test_bigger_budget_means_more_shares():
    small = plan_trade(50.0, 2.0, "buy", SETTINGS, cash=10_000)
    big = plan_trade(50.0, 2.0, "buy", {**SETTINGS, "budget": 50_000.0}, cash=50_000)
    assert big["shares"] == 5 * small["shares"]


def test_too_expensive_explains_why():
    plan = plan_trade(900.0, 50.0, "strong_buy", SETTINGS, cash=10_000)  # stop is $125 away, risk budget $100
    assert plan["shares"] == 0 and "Raise the budget" in plan["notes"][0]


def test_no_buy_size_for_hold_sell_or_existing_position():
    assert plan_trade(50.0, 2.0, "hold", SETTINGS, cash=10_000)["shares"] == 0
    assert plan_trade(50.0, 2.0, "sell", SETTINGS, cash=10_000)["shares"] == 0
    held = plan_trade(50.0, 2.0, "buy", SETTINGS, cash=9_000, position={"shares": 20, "entry_price": 45.0})
    assert held["shares"] == 0 and held["holding"]["pnl"] == 100.0


def test_available_cash_subtracts_open_positions():
    positions = [{"shares": 10, "entry_price": 100.0}, {"shares": 5, "entry_price": 200.0}]
    assert available_cash(SETTINGS, positions) == 8_000.0
    assert available_cash({**SETTINGS, "budget": 500.0}, positions) == 0.0
