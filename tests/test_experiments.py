import numpy as np
import pandas as pd

from stockanalysis.validation.experiments import FEATURES, _norm_cdf, _norm_ppf, deflated_sharpe, fit_weights


def test_normal_helpers():
    assert abs(_norm_ppf(0.975) - 1.959964) < 1e-5
    assert abs(_norm_ppf(0.001) + 3.090232) < 1e-5
    assert abs(_norm_cdf(1.959964) - 0.975) < 1e-6


def test_deflated_sharpe_discounts_the_best_of_many_random_tries():
    rng = np.random.default_rng(1)
    trials = [pd.Series(rng.normal(0, 0.01, 2500)) for _ in range(300)]
    srs = [float(t.mean() / t.std()) for t in trials]
    best = trials[int(np.argmax(srs))]
    res = deflated_sharpe(best, srs)
    assert res["probability_real_if_one_trial"] > 0.95          # looks significant alone...
    assert res["probability_real"] < 0.95                       # ...but not as the best of 300
    strong = pd.Series(rng.normal(0.003, 0.01, 2500))            # a genuine edge, Sharpe ~4.7 a year
    assert deflated_sharpe(strong, srs + [float(strong.mean() / strong.std())])["probability_real"] > 0.99


def test_fit_weights_recovers_the_signals_that_matter():
    rng = np.random.default_rng(2)
    rows = []
    for m, d in enumerate(pd.date_range("2003-01-31", periods=96, freq="ME")):
        x = rng.uniform(-1, 1, size=(40, len(FEATURES)))
        y = 0.02 * x[:, 1] - 0.01 * x[:, 3] + rng.normal(0, 0.03, 40)   # momentum helps, pullback hurts
        t = pd.DataFrame(x, columns=FEATURES)
        t["target"], t["date"] = y, d
        rows.append(t)
    fit = fit_weights(pd.concat(rows, ignore_index=True))
    w = dict(zip(FEATURES, fit["weights"]))
    assert w["momentum"] > 20 and w["pullback"] < -5
    assert abs(sum(abs(v) for v in w.values()) - 100) < 1e-6
    assert max(abs(w[k]) for k in ("trend", "high52", "macd", "earnings")) < w["momentum"] / 2
