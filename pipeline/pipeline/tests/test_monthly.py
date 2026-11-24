"""Monthly-file climatology path: harmonic daily climatology and the daily-vs-monthly diagnostic."""
import datetime as dt, logging, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_climatology as bc
from tele import reanalysis as ra


def test_monthly_to_daily_recovers_seasonal_cycle():
    d = np.arange(366)
    truth = 5600 + 150 * np.cos(2 * np.pi * (d - 200) / 366) + 25 * np.cos(4 * np.pi * (d - 30) / 366)
    starts = [(dt.date(2000, m, 1) - dt.date(2000, 1, 1)).days for m in range(1, 13)] + [366]
    monthly = np.array([truth[starts[i]:starts[i + 1]].mean() for i in range(12)])
    rec = bc.monthly_to_daily(monthly[:, None])[:, 0]
    assert np.abs(rec - truth).max() < 4.0, np.abs(rec - truth).max()


class _Var:
    def __init__(self, a, **kw): self.a = a; self.__dict__.update(kw)
    def __getitem__(self, k): return np.ma.masked_array(self.a[k])


def test_monthly_heights_and_diagnostic(monkeypatch, caplog):
    years = list(range(2001, 2006))
    times = [dt.datetime(y, m, 1) for y in years for m in range(1, 13)]
    rng = np.random.default_rng(0)
    lat = 90 - 2.5 * np.arange(73)
    season = np.array([np.cos(2 * np.pi * (t.month - 7) / 12) for t in times])
    z500 = 5600 + 100 * season[:, None, None] * np.ones((1, 73, 144)) + rng.normal(0, 20, (60, 73, 144))
    z1000 = 100 + rng.normal(0, 30, (60, 73, 144))
    hgt = np.stack([z1000, z500], axis=1)                     # levels 1000, 500
    ds = type("DS", (), {})()
    ds.variables = {"time": _Var(np.arange(60.0), units="x"), "level": _Var(np.array([1000.0, 500.0])), "hgt": _Var(hgt)}
    ds.close = lambda: None
    monkeypatch.setattr(ra, "open_nc", lambda url: ds)
    monkeypatch.setattr(ra, "times", lambda d: times)
    # daily-derived monthly means: correct except 2003, which carries a +120 m offset
    raw = z500[:, :37].copy(); raw[24:36] += 120
    h_daily = {"mon_year": np.array([t.year for t in times]), "mon_month": np.array([t.month for t in times]), "mon_raw500": raw}
    with caplog.at_level(logging.INFO, logger="tele"):
        out = bc.monthly_heights(years, h_daily)
    assert "2003: 120" in caplog.text
    assert out["mon_a500"].shape == (60, 73, 144) and np.allclose(out["mon_a500"][:, 37:], 0)
    assert abs(np.nanstd(out["mon_a500"][:, 10]) - 20) < 3          # seasonal cycle removed, noise left
    jan = out["z500_mean"][14, 10].mean(); jul = out["z500_mean"][196, 10].mean()
    assert jul - jan > 150                                        # seasonal cycle in the daily climatology
