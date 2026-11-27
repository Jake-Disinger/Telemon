#!/usr/bin/env python3
"""Measure the systematic AAM difference between GFS analyses and NCEP/NCAR
Reanalysis-1 (the climatology's source) over a period when both exist, and save it to
<state_dir>/calibration.json. The ingest and backfill subtract it, so AAM anomalies are
relative to the 1991-2020 climate instead of carrying a model-vs-reanalysis offset.

  python calibrate_aam.py --days 150

Safeguards (added after a bad calibration on 2026-11-24 shifted every AAM value by ~3 sigma):
reanalysis days whose AAM is implausible for the time of year are dropped, outlying
GFS-minus-reanalysis pairs are rejected, and the result is only kept if it passes a quality
check (correlation >= 0.97, scatter <= 0.35 sigma). Otherwise the last good value is kept,
or KNOWN_GOOD_OFFSET if there is none. When the offset changes, the previous value is
recorded as "aam_offset_replaced" so repair_aam.py can correct already-stored values.
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

# GFS minus Reanalysis-1, measured 2026-11-24 over 2025-10-19..2026-03-17 (150 days,
# correlation 0.992, scatter 0.15 sigma). Used only if no good calibration can be made.
KNOWN_GOOD_OFFSET = -1.2133787557067313e+24
MIN_CORR, MAX_SCATTER_SIGMA = 0.97, 0.35


class WindOnly(NCEPSource):
    def wanted(self):
        return {f"UGRD:{l} mb": ("u", l) for l in self.u_levels}


def reanalysis_aam(levels, years, clim=None, max_sigma=6.0):
    """date -> daily-mean relative AAM from Reanalysis-1. Days with truncated downloads
    (runs of exact zeros) or AAM far outside the climate for the date are skipped."""
    from tele.climo import cal_index
    out, dropped = {}, 0
    for y in years:
        try:
            ts, u = ra.read_levels("uwnd", y, levels)
        except Exception as e:                                   # noqa: BLE001
            log.warning("reanalysis %d unavailable (%s)", y, e)
            continue
        for t, uu in zip(ts, u):
            if np.isfinite(uu).mean() <= 0.99 or (uu == 0).mean() > 0.01:
                dropped += 1
                continue
            m = ix.relative_aam(np.nan_to_num(uu), levels)
            if clim is not None:
                k = cal_index(t)
                if abs(m - clim.aam_mean[k]) > max_sigma * clim.idx_sd["aam"]:
                    dropped += 1
                    continue
            out[t.date()] = m
    if dropped:
        log.warning("reanalysis AAM: skipped %d implausible or incomplete days", dropped)
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
    d = g - r
    med = np.median(d)
    mad = 1.4826 * np.median(np.abs(d - med))
    keep = np.abs(d - med) <= max(4.0 * mad, 1e-6 * abs(med) + 1.0)
    if keep.sum() < 30:
        return None
    g, r, d = g[keep], r[keep], d[keep]
    return dict(aam_offset=float(np.mean(d)), n=int(keep.sum()), rejected=int((~keep).sum()),
                corr=float(np.corrcoef(g, r)[0, 1]), rmse_after=float(np.std(d)),
                period=[str(dates[0]), str(dates[-1])])


def decide(res, old, sd):
    """Pick the offset to store. Returns (calibration dict to write, note)."""
    new = dict(old)
    good = res is not None and res["corr"] >= MIN_CORR and res["rmse_after"] <= MAX_SCATTER_SIGMA * sd
    if good:
        new.update(res)
        new["aam_ok"] = True
        note = "new calibration accepted"
    elif old.get("aam_ok"):
        note = "new calibration failed the quality check; keeping the previous good value"
    else:
        new.update(aam_offset=KNOWN_GOOD_OFFSET, aam_ok=True, source="known good value (2026-11-24)")
        for k in ("n", "rejected", "corr", "rmse_after", "period"):
            new.pop(k, None)
        note = "no good calibration available; using the known good value"
    prev = old.get("aam_offset")
    if prev is not None and abs(prev - new["aam_offset"]) > 1e-3 * sd:
        new["aam_offset_replaced"] = prev          # repair_aam.py fixes stored values, then removes this
    return new, note


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
    r1 = reanalysis_aam(levels, [this_year - 1, this_year], clim)
    if r1:
        log.info("reanalysis AAM available %s .. %s (%d days)", min(r1), max(r1), len(r1))
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

    res = compute_offset(r1, gfs_aam, a.days) if r1 else None
    sd = clim.idx_sd["aam"]
    if res is None:
        log.warning("fewer than 30 good overlapping days")
    else:
        log.info("GFS minus reanalysis AAM: %+.2e kg m2/s (%+.2f sigma), corr %.3f, scatter %.2f sigma, "
                 "%d days used, %d outliers rejected (%s .. %s)", res["aam_offset"], res["aam_offset"] / sd,
                 res["corr"], res["rmse_after"] / sd, res["n"], res["rejected"], *res["period"])
    path = os.path.join(cfg["state_dir"], "calibration.json")
    os.makedirs(cfg["state_dir"], exist_ok=True)
    old = {}
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
    new, note = decide(res, old, sd)       # keeps index_offsets written by verify_indices
    log.info("%s: AAM offset %+.3e (%+.2f sigma)", note, new["aam_offset"], new["aam_offset"] / sd)
    if "aam_offset_replaced" in new:
        log.warning("AAM offset changed by %+.2f sigma; repair_aam.py will correct stored values",
                    (new["aam_offset_replaced"] - new["aam_offset"]) / sd)
    with open(path, "w") as f:
        json.dump(new, f, indent=1)
    log.info("wrote %s", path)


if __name__ == "__main__":
    main()
