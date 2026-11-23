#!/usr/bin/env python3
"""Seed the 'observed' history (black line) and the MJO 120-day history from
NCEP/NCAR Reanalysis-1 near-real-time daily means, so charts and RMM values are right
from day one instead of after four months of GFS analyses.

  python backfill_analysis.py --days 150
"""
import argparse
import datetime as dt
import logging
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from run_ingest import load_config                    # noqa: E402
from tele import indices as ix                        # noqa: E402
from tele import reanalysis as ra                     # noqa: E402
from tele.climo import Climatology, INDEX_NAMES       # noqa: E402
from tele.store import Store                          # noqa: E402

log = logging.getLogger("tele")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--days", type=int, default=150)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config(a.config)
    clim = Climatology(cfg["climatology"])
    store = Store(cfg["data_dir"], cfg["state_dir"])
    start = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=a.days)
    years = sorted({start.year, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).year})

    # OLR (may lag the winds by a few days; missing days fall back to wind-only)
    olr_by_day = {}
    try:
        ds = ra.open_nc(ra.URLS["olr"])
        to = ra.times(ds)
        i0 = next(i for i, t in enumerate(to) if t >= start)
        block = np.ma.filled(ds.variables["olr"][i0:].astype(float), np.nan)
        for t, f in zip(to[i0:], block):
            olr_by_day[t.date()] = ix.eq_profile(f)
        ds.close()
    except Exception as e:                                       # noqa: BLE001
        log.warning("OLR unavailable (%s); MJO history will be wind-only", e)

    levels = sorted(set(clim.aam_levels) | {850, 200})
    for y in years:
        tz, z = ra.read_levels("hgt", y, [500, 1000])
        tu, u = ra.read_levels("uwnd", y, levels)
        upos = {t.date(): i for i, t in enumerate(tu)}
        for i, t in enumerate(tz):
            if t < start or t.date() not in upos:
                continue
            uu = {l: u[upos[t.date()], k] for k, l in enumerate(levels)}
            raw = clim.raw_indices(t, z[i, 0], z[i, 1], uu)
            vals = {n: clim.standardize(n, raw[n]) for n in INDEX_NAMES}
            prof = {"u850": clim.eq_anom(t, "u850", ix.eq_profile(uu[850])),
                    "u200": clim.eq_anom(t, "u200", ix.eq_profile(uu[200]))}
            if t.date() in olr_by_day:
                prof["olr"] = clim.eq_anom(t, "olr", olr_by_day[t.date()])
            store.add_mjo_history(t, prof)
            store.update_analysis(t, vals)
    # RMM for the observed days once the history is filled in
    hist = store.mjo_daily()
    days = sorted(hist)
    for d in days:
        win = [d - dt.timedelta(days=k) for k in range(1, 121)]
        p = {}
        for var in ("olr", "u850", "u200"):
            past = [hist[x][var] for x in win if x in hist and var in hist[x]]
            p[var] = (hist[d][var] - np.mean(past, axis=0)) if (var in hist[d] and len(past) >= 60) else None
        if p["u850"] is None:
            continue
        wo = p["olr"] is None
        r1, r2 = ix.rmm_from_profiles(p["olr"], p["u850"], p["u200"], clim.rmm_eofs, clim.rmm_norms,
                                      clim.rmm_pcstd_wind if wo else clim.rmm_pcstd, wind_only=wo)
        store.update_analysis(dt.datetime(d.year, d.month, d.day), {"rmm1": float(r1), "rmm2": float(r2)})
    log.info("backfill complete")


if __name__ == "__main__":
    main()
