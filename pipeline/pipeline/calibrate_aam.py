#!/usr/bin/env python3
"""Measure the systematic AAM difference between GFS analyses and NCEP/NCAR
Reanalysis-1 (the climatology's source) over a period when both exist, and save it to
<state_dir>/calibration.json. The ingest and backfill subtract it, so AAM anomalies are
relative to the 1991-2020 climate instead of carrying a model-vs-reanalysis offset.

  python calibrate_aam.py --days 150
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from run_ingest import load_config                    # noqa: E402
from tele import indices as ix                        # noqa: E402
from tele import reanalysis as ra                     # noqa: E402
from tele.climo import Climatology                    # noqa: E402
from tele.sources import NCEPSource                   # noqa: E402

log = logging.getLogger("tele")


class WindOnly(NCEPSource):
    def wanted(self):
        return {f"UGRD:{l} mb": ("u", l) for l in self.u_levels}


def reanalysis_aam(levels, years):
    """date -> daily-mean relative AAM from Reanalysis-1."""
    out = {}
    for y in years:
        try:
            ts, u = ra.read_levels("uwnd", y, levels)
        except Exception as e:                                   # noqa: BLE001
            log.warning("reanalysis %d unavailable (%s)", y, e)
            continue
        for t, uu in zip(ts, u):
            if np.isfinite(uu).mean() > 0.99:
                out[t.date()] = ix.relative_aam(np.nan_to_num(uu), levels)
    return out


def compute_offset(r1, gfs_fetch, days, workers=4):
    """r1: date -> AAM; gfs_fetch(datetime) -> AAM or None. Uses the last `days` R1 days."""
    dates = sorted(r1)[-days:]
    runs = [dt.datetime(d.year, d.month, d.day, h) for d in dates for h in (0, 12)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        vals = dict(zip(runs, ex.map(gfs_fetch, runs)))
    pairs = []
    for d in dates:
        g = [vals[dt.datetime(d.year, d.month, d.day, h)] for h in (0, 12)]
        g = [x for x in g if x is not None]
        if g:
            pairs.append((np.mean(g), r1[d]))
    if len(pairs) < 30:
        return None
    g, r = np.array(pairs).T
    return dict(aam_offset=float(np.mean(g - r)), n=len(pairs), corr=float(np.corrcoef(g, r)[0, 1]),
                rmse_after=float(np.std(g - r)), period=[str(dates[0]), str(dates[-1])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--days", type=int, default=150)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config(a.config)
    clim = Climatology(cfg["climatology"])
    levels = clim.aam_levels
    this_year = dt.date.today().year
    r1 = reanalysis_aam(levels, [this_year - 1, this_year])
    if not r1:
        log.error("no reanalysis data for the overlap period; AAM left uncalibrated")
        return
    log.info("reanalysis AAM available %s .. %s", min(r1), max(r1))
    src = WindOnly("gfs", cfg["models"][cfg.get("analysis_model", "gfs")], levels)

    def gfs_aam(run):
        try:
            d = src.fetch_step(run, 0)
            u = next(iter(d.values()))["u"] if d else {}
            if all(l in u for l in levels):
                return ix.relative_aam(np.stack([u[l] for l in levels]), levels)
        except Exception as e:                                   # noqa: BLE001
            log.warning("GFS %s unavailable (%s)", run, e)
        return None

    res = compute_offset(r1, gfs_aam, a.days)
    if res is None:
        log.error("fewer than 30 overlapping days; AAM left uncalibrated")
        return
    sd = clim.idx_sd["aam"]
    log.info("GFS minus reanalysis AAM: %+.2e kg m2/s (%+.2f sigma), corr %.3f over %d days (%s .. %s)",
             res["aam_offset"], res["aam_offset"] / sd, res["corr"], res["n"], *res["period"])
    path = os.path.join(cfg["state_dir"], "calibration.json")
    os.makedirs(cfg["state_dir"], exist_ok=True)
    old = {}
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
    old.update(res)                                   # keep index_offsets written by verify_indices
    with open(path, "w") as f:
        json.dump(old, f, indent=1)
    log.info("wrote %s", path)


if __name__ == "__main__":
    main()
