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


def test_calibration_quality_gate_and_fallback():
    import numpy as np
    sd = 8.4e24
    good = dict(aam_offset=-1.0e24, n=150, rejected=0, corr=0.99, rmse_after=0.15 * sd, period=["a", "b"])
    bad = dict(aam_offset=2.5e25, n=150, rejected=0, corr=0.958, rmse_after=3.2 * sd, period=["a", "b"])
    # bad result, previous good -> keep previous
    new, note = cal.decide(bad, {"aam_offset": -1.2e24, "aam_ok": True, "index_offsets": {"nao": 0.1}}, sd)
    assert new["aam_offset"] == -1.2e24 and new["index_offsets"] == {"nao": 0.1} and "aam_offset_replaced" not in new
    # bad result, previous bad (no flag) -> known good value, and the old one recorded for repair
    new, note = cal.decide(bad, {"aam_offset": 2.5e25}, sd)
    assert new["aam_offset"] == cal.KNOWN_GOOD_OFFSET and new["aam_offset_replaced"] == 2.5e25
    # good result replaces a bad one
    new, note = cal.decide(good, {"aam_offset": 2.5e25}, sd)
    assert new["aam_offset"] == -1.0e24 and new["aam_ok"] and new["aam_offset_replaced"] == 2.5e25
    # robust offset ignores corrupted reanalysis days
    rng = np.random.default_rng(0)
    import datetime as dt
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(100)]
    truth = {d: 1e26 + 1e25 * np.sin(i / 9) for i, d in enumerate(days)}
    r1 = {d: v + (5e25 if i % 7 == 0 else 0) for i, (d, v) in enumerate(truth.items())}   # corrupted days
    gfs = lambda run: truth[run.date()] - 1e24 + rng.normal(scale=5e23)
    res = cal.compute_offset(r1, gfs, 100, workers=2)
    assert abs(res["aam_offset"] + 1e24) < 3e23 and res["rejected"] >= 14 and res["corr"] > 0.97


def test_repair_shifts_only_old_offset_values(tmp_path):
    import json
    import repair_aam as rp
    d = tmp_path / "data"; (d / "runs" / "gfs").mkdir(parents=True)
    times = ["2026112500", "2026112506", "2026112512", "2026112518", "2026112600"]
    an = {"times": times, "aam": [3.5, 0.4, 3.6, 3.55, 3.4]}        # 06Z made with the old offset
    json.dump(an, open(d / "analysis.json", "w"))
    json.dump({"run": "2026112506", "indices": {"aam": {"value": [0.4, 0.1], "raw": [3.0, 1.0]}}}, open(d / "runs" / "gfs" / "2026112506.json", "w"))
    json.dump({"run": "2026112518", "indices": {"aam": {"value": [3.55, 3.0]}}}, open(d / "runs" / "gfs" / "2026112518.json", "w"))
    rp.repair(str(d), 3.115, 8.41e24)
    a = json.load(open(d / "analysis.json"))
    assert abs(a["aam"][1] - 3.515) < 1e-6 and a["aam"][3] == 3.55
    r = json.load(open(d / "runs" / "gfs" / "2026112506.json"))["indices"]["aam"]
    assert abs(r["value"][0] - 3.515) < 1e-6 and abs(r["raw"][0] - (3.0 + 3.115 * 8.41)) < 1e-2
    assert json.load(open(d / "runs" / "gfs" / "2026112518.json"))["indices"]["aam"]["value"] == [3.55, 3.0]
