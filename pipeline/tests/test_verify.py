import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import verify_indices as v


def test_compare_with_cpc():
    today = dt.date.today()
    days = [today - dt.timedelta(days=k) for k in range(60, 0, -1)]
    rng = np.random.default_rng(0)
    truth = np.cumsum(rng.normal(0, 0.3, len(days)))
    cpc_txt = "\n".join(f"{d.year},{d.month},{d.day},{x}" for d, x in zip(days, truth))
    times, vals = [], []
    for d, x in zip(days, truth):
        for h in (0, 12):
            times.append(f"{d:%Y%m%d}{h:02d}"); vals.append(x + 0.5 + rng.normal(0, 0.05))
    r = v.compare(v.ours_daily({"times": times, "nao": vals}, "nao"), v.parse_cpc(cpc_txt, today - dt.timedelta(days=200)))
    assert r["n"] == 60 and r["corr"] > 0.98 and abs(r["mean_diff"] - 0.5) < 0.05
