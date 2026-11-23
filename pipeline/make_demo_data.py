#!/usr/bin/env python3
"""Write SYNTHETIC demo data into web/data so the page can be previewed before the real
ingest runs. The manifest is flagged demo=true and the page shows a banner.
Delete web/data/* (or just run run_ingest.py, which overwrites) to switch to real data."""
import datetime as dt
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "web", "data")
rng = np.random.default_rng(42)
NOW = dt.datetime(2026, 11, 23, 0)
IDX = ["nao", "ao", "pna", "epo", "aam"]
MODELS = {
    "gfs": ("det", [0, 6, 12, 18], 12, 384, 1), "gefs": ("ens", [0, 6, 12, 18], 12, 384, 31),
    "hres": ("det", [0, 12], 12, 240, 1), "eps": ("ens", [0, 12], 12, 360, 51),
    "aifs": ("det", [0, 12], 12, 360, 1), "geps": ("ens", [0, 12], 12, 384, 21),
}


def smooth_series(n, scale, corr=0.93):
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = corr * x[i - 1] + rng.normal(0, scale)
    return x


# "truth" at 6-hourly resolution, from 130 days back to 20 days ahead
hours = np.arange(-130 * 24, 21 * 24, 6)
truth = {k: smooth_series(len(hours), 0.22, 0.985) * 1.3 for k in IDX}
# shape PNA roughly like the reference graphic
t_days = hours / 24
truth["pna"] = 1.4 * np.sin((t_days + 6) / 3.2) * np.exp(-((t_days - 1) / 9) ** 2) + 0.35 * truth["pna"]
phase0 = rng.uniform(0, 2 * np.pi)
mjo_ang = phase0 + 2 * np.pi * t_days / 42 + 0.4 * np.sin(t_days / 17)
mjo_amp = 1.3 + 0.8 * np.sin(t_days / 23) + 0.15 * smooth_series(len(hours), 0.2)
truth["rmm1"], truth["rmm2"] = mjo_amp * np.cos(mjo_ang), mjo_amp * np.sin(mjo_ang)


def truth_at(name, t):
    h = (t - NOW).total_seconds() / 3600
    return float(np.interp(h, hours, truth[name]))


def forecast(name, run, steps, bias_seed, spread):
    """smooth error growth around the truth"""
    g = np.random.default_rng(bias_seed)
    err, out = 0.0, []
    for s in steps:
        err = 0.9 * err + g.normal(0, spread * (0.1 + s / 400))
        out.append(truth_at(name, run + dt.timedelta(hours=s)) * (1 - s / 900) + err)
    return out


def main():
    if os.path.isdir(os.path.join(OUT, "runs")):
        shutil.rmtree(os.path.join(OUT, "runs"))
    man = {"updated": NOW.strftime("%Y-%m-%dT%H:%MZ"), "demo": True, "models": {}}
    for mk, (kind, cycles, sh, mx, nm) in MODELS.items():
        runs = []
        for back in range(0, 6 * 24, 6):
            run = NOW - dt.timedelta(hours=back)
            if run.hour not in cycles:
                continue
            rid = run.strftime("%Y%m%d%H")
            steps = list(range(0, mx + 1, sh))
            seed = hash((mk, rid)) % 2**31
            p = {"model": mk, "run": rid, "kind": kind, "steps": steps, "members": nm, "indices": {}}
            for n in IDX + ["mjo"]:
                if n == "mjo":
                    if kind == "det":
                        p["indices"]["mjo"] = {"wind_only": False,
                                               "rmm1": [round(v, 3) for v in forecast("rmm1", run, steps, seed + 1, .5)],
                                               "rmm2": [round(v, 3) for v in forecast("rmm2", run, steps, seed + 2, .5)]}
                    else:
                        m1 = [[round(v, 2) for v in forecast("rmm1", run, steps, seed + 10 + i, .7)] for i in range(nm)]
                        m2 = [[round(v, 2) for v in forecast("rmm2", run, steps, seed + 500 + i, .7)] for i in range(nm)]
                        p["indices"]["mjo"] = {"wind_only": mk == "geps", "rmm1": np.mean(m1, 0).round(3).tolist(),
                                               "rmm2": np.mean(m2, 0).round(3).tolist(), "members_rmm1": m1, "members_rmm2": m2}
                    continue
                if kind == "det":
                    d = {"value": [round(v, 3) for v in forecast(n, run, steps, seed + IDX.index(n), 1.0)]}
                else:
                    mem = [[round(v, 2) for v in forecast(n, run, steps, seed + 1000 * IDX.index(n) + i, 1.3)] for i in range(nm)]
                    d = {"mean": np.mean(mem, 0).round(3).tolist(), "members": mem}
                if n == "aam":
                    d["raw"] = [round(v * 9.0, 2) for v in (d.get("value") or d["mean"])]
                p["indices"][n] = d
            os.makedirs(os.path.join(OUT, "runs", mk), exist_ok=True)
            with open(os.path.join(OUT, "runs", mk, rid + ".json"), "w") as f:
                json.dump(p, f, separators=(",", ":"))
            runs.append(rid)
        man["models"][mk] = {"runs": sorted(runs, reverse=True)}
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    times = [NOW + dt.timedelta(hours=int(h)) for h in hours if h <= 0 and h % 12 == 0]
    a = {"updated": man["updated"], "times": [t.strftime("%Y%m%d%H") for t in times]}
    for n in IDX + ["rmm1", "rmm2"]:
        a[n] = [round(truth_at(n, t), 3) for t in times]
    with open(os.path.join(OUT, "analysis.json"), "w") as f:
        json.dump(a, f, separators=(",", ":"))
    print("demo data written to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
