#!/usr/bin/env python3
"""Seed the 'observed' history (black line) and the MJO 120-day history from past
GFS analyses on the NOAA AWS archive, so charts and RMM values are right from day one
instead of after four months of live ingest.

Uses the same method as the live ingest (GFS f000 for heights/winds, the 0-6 h mean
OLR from f006), so backfilled and live values are directly comparable.

  python backfill_analysis.py --days 150
"""
import argparse
import datetime as dt
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from run_ingest import load_config                    # noqa: E402
from tele import indices as ix                        # noqa: E402
from tele.climo import Climatology, INDEX_NAMES       # noqa: E402
from tele.sources import NCEPSource                   # noqa: E402
from tele.store import Store                          # noqa: E402

log = logging.getLogger("tele")


class OLROnly(NCEPSource):
    def wanted(self):
        return {"ULWRF:top of atmosphere": ("olr", None)}


def fetch_analysis(src, olr_src, run):
    """-> (fields at f000, OLR field from f006 or None); None if the run is missing."""
    try:
        d0 = src.fetch_step(run, 0)
        if not d0:
            return None
        d6 = olr_src.fetch_step(run, 6)
        olr = next(iter(d6.values()))["olr"] if d6 else None
        return next(iter(d0.values())), olr
    except Exception as e:                                   # noqa: BLE001
        log.warning("skip %s (%s)", run.strftime("%Y%m%d%H"), e)
        return None


def backfill(cfg, clim, store, days, fetch=None, now=None, hours=(0, 12), workers=4):
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    gcfg = cfg["models"][cfg.get("analysis_model", "gfs")]
    src = NCEPSource("gfs", gcfg, set(clim.aam_levels) | {850, 200})
    olr_src = OLROnly("gfs", gcfg, [])
    fetch = fetch or (lambda run: fetch_analysis(src, olr_src, run))
    last = (now - dt.timedelta(hours=7)).replace(minute=0, second=0, microsecond=0)
    start = (now - dt.timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    runs = []
    t = start
    while t <= last:
        if t.hour in hours:
            runs.append(t)
        t += dt.timedelta(hours=6)
    log.info("backfilling %d GFS analyses %s .. %s", len(runs), runs[0], runs[-1])

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for run, res in zip(runs, ex.map(fetch, runs)):
            if res is None:
                continue
            f, olr = res
            raw = clim.raw_indices(run, f.get("z500"), f.get("z1000"), f.get("u"))
            store.update_analysis(run, {n: clim.standardize(n, raw[n]) for n in INDEX_NAMES})
            u = f.get("u", {})
            if 850 in u and 200 in u:
                prof = {"u850": clim.eq_anom(run, "u850", ix.eq_profile(u[850])),
                        "u200": clim.eq_anom(run, "u200", ix.eq_profile(u[200]))}
                if olr is not None:
                    prof["olr"] = clim.eq_anom(run, "olr", ix.eq_profile(olr))
                store.add_mjo_history(run, prof)
            done += 1
            if done % 20 == 0:
                log.info("... %d/%d analyses (%s)", done, len(runs), run.strftime("%Y%m%d%H"))
    log.info("%d of %d analyses processed", done, len(runs))

    # observed RMM for each day once the equatorial history is in place
    hist = store.mjo_daily()
    n_rmm = 0
    for d in sorted(hist):
        win = [d - dt.timedelta(days=k) for k in range(1, 121)]
        p = {}
        for var in ("olr", "u850", "u200"):
            past = [hist[x][var] for x in win if x in hist and var in hist[x]]
            if var in hist[d]:
                p[var] = hist[d][var] - np.mean(past, axis=0) if len(past) >= 60 else hist[d][var]
            else:
                p[var] = None
        if p["u850"] is None or p["u200"] is None:
            continue
        wo = p["olr"] is None
        r1, r2 = ix.rmm_from_profiles(p["olr"], p["u850"], p["u200"], clim.rmm_eofs, clim.rmm_norms,
                                      clim.rmm_pcstd_wind if wo else clim.rmm_pcstd, wind_only=wo)
        store.update_analysis(dt.datetime(d.year, d.month, d.day), {"rmm1": float(r1), "rmm2": float(r2)})
        n_rmm += 1
    log.info("observed RMM written for %d days", n_rmm)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--days", type=int, default=150)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config(a.config)
    clim = Climatology(cfg["climatology"])
    store = Store(cfg["data_dir"], cfg["state_dir"])
    n = backfill(cfg, clim, store, a.days)
    if n == 0:
        log.error("no GFS analyses could be downloaded - check the gfs url in config.json")
        sys.exit(1)
    log.info("backfill complete")


if __name__ == "__main__":
    main()
