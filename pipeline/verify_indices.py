#!/usr/bin/env python3
"""Compare the site's observed NAO, AO and PNA with CPC's official daily values and log
the agreement (correlation, mean difference, spread). Writes <data_dir>/verification.json.

  python verify_indices.py
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_ingest import load_config            # noqa: E402

log = logging.getLogger("tele")
CPC = "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{name}.cdas.{lev}.19500101_current.csv"
SERIES = {"nao": "z500", "ao": "z1000", "pna": "z500"}


def parse_cpc(text, since):
    out = {}
    for line in text.splitlines():
        p = line.strip().split(",")
        if len(p) < 4:
            continue
        try:
            d = dt.date(int(p[0]), int(p[1]), int(p[2]))
            v = float(p[3])
        except ValueError:
            continue
        if d >= since and np.isfinite(v):
            out[d] = v
    return out


def ours_daily(analysis, name):
    acc = {}
    for t, v in zip(analysis["times"], analysis.get(name, [])):
        if v is not None:
            acc.setdefault(dt.date(int(t[:4]), int(t[4:6]), int(t[6:8])), []).append(v)
    return {d: float(np.mean(v)) for d, v in acc.items()}


def compare(ours, cpc):
    ks = sorted(set(ours) & set(cpc))
    if len(ks) < 20:
        return None
    o = np.array([ours[k] for k in ks]); c = np.array([cpc[k] for k in ks])
    return {"n": len(ks), "first": str(ks[0]), "last": str(ks[-1]),
            "corr": round(float(np.corrcoef(o, c)[0, 1]), 3),
            "mean_diff": round(float(np.mean(o - c)), 3),
            "sd_ours": round(float(o.std()), 3), "sd_cpc": round(float(c.std()), 3),
            "rms_diff": round(float(np.sqrt(np.mean((o - c) ** 2))), 3)}


def main(fetch=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config(a.config)
    with open(os.path.join(cfg["data_dir"], "analysis.json")) as f:
        analysis = json.load(f)
    if fetch is None:
        from tele.gribio import http_get
        fetch = http_get
    since = dt.date.today() - dt.timedelta(days=200)
    report = {"checked": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "indices": {}}
    for name, lev in SERIES.items():
        try:
            text = fetch(CPC.format(name=name, lev=lev)).decode()
        except Exception as e:                                   # noqa: BLE001
            log.warning("CPC %s unavailable (%s)", name, e)
            continue
        r = compare(ours_daily(analysis, name), parse_cpc(text, since))
        if r is None:
            log.warning("%s: not enough overlapping days to compare", name.upper())
            continue
        report["indices"][name] = r
        flag = "GOOD" if r["corr"] >= 0.9 else "CHECK" if r["corr"] >= 0.8 else "POOR"
        log.info("%-3s vs CPC: corr %.2f  mean diff %+.2f  sd %.2f vs %.2f  (%d days)  [%s]",
                 name.upper(), r["corr"], r["mean_diff"], r["sd_ours"], r["sd_cpc"], r["n"], flag)
    with open(os.path.join(cfg["data_dir"], "verification.json"), "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
