"""Forecast scorecard: bias / error by lead day and the unchanged-file rule."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scorecard as sc                                   # noqa: E402


def test_scores_by_lead(tmp_path):
    d = tmp_path; (d / "runs" / "gfs").mkdir(parents=True); (d / "runs" / "gefs").mkdir()
    import datetime as dt
    t0 = dt.datetime(2026, 11, 1)
    times = [(t0 + dt.timedelta(hours=6 * i)).strftime("%Y%m%d%H") for i in range(4 * 30)]
    obs = [0.1 * (i % 13) - 0.5 for i in range(len(times))]
    json.dump({"times": times, "nao": obs, "ao": obs, "pna": obs, "epo": obs, "aam": obs}, open(d / "analysis.json", "w"))
    pos = {t: i for i, t in enumerate(times)}
    for k in range(10):                                   # GFS: +0.5 too high from day 3 on
        r = times[4 * k]; steps = list(range(0, 241, 24))
        val = [obs[pos[r] + h // 6] + (0.5 if h >= 72 else 0.0) for h in steps]
        json.dump({"run": r, "steps": steps, "indices": {"nao": {"value": val}}}, open(d / "runs" / "gfs" / f"{r}.json", "w"))
        json.dump({"run": r, "steps": steps, "indices": {"nao": {"mean": [obs[pos[r] + h // 6] for h in steps]}}}, open(d / "runs" / "gefs" / f"{r}.json", "w"))
    out = sc.build(str(d))
    g = out["models"]["gfs"]["nao"]
    assert g["1"]["bias"] == 0 and g["3"]["bias"] == 0.5 and g["3"]["n"] == 10 and g["2"]["mae"] == 0
    assert out["models"]["gefs"]["nao"]["5"]["bias"] == 0
    assert "aam" not in out["models"]["gfs"] and out["persistence"]["nao"]["1"]["n"] > 0
    mtime = os.path.getmtime(d / "scorecard.json")
    os.utime(d / "scorecard.json", (mtime - 100, mtime - 100))
    sc.build(str(d))                                      # same scores -> file not rewritten
    assert os.path.getmtime(d / "scorecard.json") == mtime - 100
