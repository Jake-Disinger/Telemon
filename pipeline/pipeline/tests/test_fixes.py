"""Regression tests for the NAO-trend, box-NAO fallback and AAM calibration fixes."""
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tele import indices as ix
from tele.grid import LAT, LON
from tele.climo import Climatology
import calibrate_aam as cal
import test_e2e

L2, N2 = np.meshgrid(LAT, LON, indexing="ij")
rng = np.random.default_rng(7)


def test_nao_eof_ignores_warming_trend():
    n = 360
    trend = np.linspace(-15, 15, n)                                      # rising heights everywhere
    dip = (np.exp(-((L2 - 65) / 8) ** 2 - ((N2 - 335) / 25) ** 2) * -60 +
           np.exp(-((L2 - 40) / 8) ** 2 - ((N2 - 335) / 25) ** 2) * 40)  # Iceland low / Azores high
    enso = np.where(np.abs(L2 - 20) < 6, 30.0, 0.0)                      # subtropical band
    amp = rng.normal(size=n); amp2 = rng.normal(size=n)
    X = trend[:, None, None] * 3 + amp[:, None, None] * dip + amp2[:, None, None] * enso * 0.6
    X = X + rng.normal(0, 5, X.shape)
    p, _ = ix.eof_pattern(X, ix.NAO_DOMAIN)
    p = ix.orient_nao(p)
    assert ix.dipole_ok(p, (65, 340), (40, 335))
    r = np.corrcoef(ix.project(X, p), amp)[0, 1]
    assert r > 0.9             # positive amplitude = low over Iceland = positive NAO


def test_box_pattern_matches_box_difference():
    a = rng.normal(0, 50, (73, 144))
    p = ix.box_pattern(ix.NAO_SOUTH, ix.NAO_NORTH)
    assert np.isclose(ix.project(a, p), ix.box_mean(a, ix.NAO_SOUTH) - ix.box_mean(a, ix.NAO_NORTH))
    assert ix.dipole_ok(ix.orient_nao(p), (65, 340), (40, 335))


def test_aam_offset_estimate_and_use():
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(80)]
    r1 = {d: 1.4e26 + 1e25 * np.sin(i / 9) for i, d in enumerate(days)}
    def gfs(run):
        return r1[run.date()] + 1.8e25 + rng.normal(0, 1e23)
    res = cal.compute_offset(r1, gfs, 60, workers=2)
    assert abs(res["aam_offset"] - 1.8e25) < 1e23 and res["corr"] > 0.99 and res["n"] == 60
    with tempfile.TemporaryDirectory() as tmp:
        test_e2e.fake_climo(os.path.join(tmp, "c.npz"))
        cp = os.path.join(tmp, "calibration.json")
        json.dump(res, open(cp, "w"))
        u = {l: np.full((73, 144), 10.0) for l in test_e2e.LEVELS}
        t = dt.datetime(2026, 11, 23)
        a0 = Climatology(os.path.join(tmp, "c.npz")).raw_indices(t, u=u)["aam"]
        a1 = Climatology(os.path.join(tmp, "c.npz"), cp).raw_indices(t, u=u)["aam"]
        assert np.isclose(a0 - a1, res["aam_offset"])
        assert Climatology(os.path.join(tmp, "c.npz"), os.path.join(tmp, "missing.json")).aam_offset == 0
