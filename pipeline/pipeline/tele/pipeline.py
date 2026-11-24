"""Turn one model run into one JSON file of index forecasts."""
import datetime as dt
import logging

import numpy as np

from . import indices as ix
from .climo import INDEX_NAMES, cal_index

log = logging.getLogger("tele")
MJO_WINDOW = 120          # days, prior-mean removal (Wheeler & Hendon 2004)
MJO_MIN_DAYS = 60


def collect(source, run, clim, steps_data=None, maps=None, map_max_hours=360):
    """Fetch every step and reduce it to raw index values + equatorial profiles.

    Returns (steps, members) where members[m] = dict(raw={name: [..]}, eq={var: [..]}).
    steps_data lets tests inject fields instead of downloading. maps: an optional
    tele.maps.MapAccumulator that receives North Pacific fields once per forecast day.
    """
    members = {}
    steps_ok = []
    for si, step in enumerate(source.steps):
        valid = run + dt.timedelta(hours=step)
        data = steps_data[si] if steps_data is not None else source.fetch_step(run, step)
        if not data:
            log.warning("%s %s f%03d: no data", source.key, run.strftime("%Y%m%d%H"), step)
            continue
        steps_ok.append(step)
        for m, d in data.items():
            rec = members.setdefault(m, {"raw": {n: {} for n in INDEX_NAMES},
                                         "eq": {"olr": {}, "ttr": {}, "u850": {}, "u200": {}}})
            raw = clim.raw_indices(valid, d.get("z500"), d.get("z1000"),
                                   d.get("u") if source.cfg.get("aam", True) else None)
            for n, v in raw.items():
                rec["raw"][n][step] = v
            for var in ("olr", "ttr"):
                if d.get(var) is not None:
                    rec["eq"][var][step] = ix.eq_profile(d[var])
            for lev in (850, 200):
                if lev in d.get("u", {}):
                    rec["eq"][f"u{lev}"][step] = ix.eq_profile(d["u"][lev])
            if maps is not None and step % 24 == 0 and step <= map_max_hours:
                z = d.get("z500")
                maps.add(step, z500=z, z500a=None if z is None else z - clim.z500_mean[cal_index(valid)],
                         mslp=d.get("mslp"))
        log.info("%s %s f%03d done (%d members)", source.key, run.strftime("%Y%m%d%H"), step, len(data))
    return steps_ok, members


def olr_profiles(eq, steps):
    """OLR profile per step: direct flux (NCEP) or de-accumulated ttr (ECMWF)."""
    if eq["olr"]:
        return {s: eq["olr"].get(s) for s in steps}
    out = {s: None for s in steps}
    ttr = eq["ttr"]
    for a, b in zip(steps[:-1], steps[1:]):
        if a in ttr and b in ttr:
            out[b] = -(ttr[b] - ttr[a]) / ((b - a) * 3600.0)      # J m-2 -> W m-2, upward positive
    return out


def rmm_series(clim, run, steps, eq, hist_daily):
    """RMM1/RMM2 for one member. hist_daily: date -> {var: observed anomaly profile}."""
    olr = olr_profiles(eq, steps)
    valid = {s: run + dt.timedelta(hours=s) for s in steps}
    have = [s for s in steps if s in eq["u850"] and s in eq["u200"]]
    wind_only = any(olr.get(s) is None for s in have if s > 0) or not have
    # forecast anomalies, then daily means for dates after the init date
    fc = {}
    for s in have:
        a = {"u850": clim.eq_anom(valid[s], "u850", eq["u850"][s]),
             "u200": clim.eq_anom(valid[s], "u200", eq["u200"][s])}
        if olr.get(s) is not None:
            a["olr"] = clim.eq_anom(valid[s], "olr", olr[s])
        fc[s] = a
    fc_daily = {}
    for s, a in fc.items():
        for var, p in a.items():
            fc_daily.setdefault(valid[s].date(), {}).setdefault(var, []).append(p)
    fc_daily = {d: {v: np.mean(ps, axis=0) for v, ps in vs.items()} for d, vs in fc_daily.items()}

    def daily(d, var):
        if d > run.date() or d not in hist_daily:
            return fc_daily.get(d, {}).get(var)
        return hist_daily[d].get(var)

    r1, r2 = [], []
    for s in steps:
        if s not in fc:
            r1.append(None); r2.append(None); continue
        day = valid[s].date()
        win = [day - dt.timedelta(days=k) for k in range(1, MJO_WINDOW + 1)]
        prof = {}
        for var in ("olr", "u850", "u200"):
            x = fc[s].get(var)
            if x is None:
                prof[var] = None
                continue
            past = [p for p in (daily(d, var) for d in win) if p is not None]
            prof[var] = x - np.mean(past, axis=0) if len(past) >= MJO_MIN_DAYS else x
        a, b = ix.rmm_from_profiles(prof["olr"], prof["u850"], prof["u200"], clim.rmm_eofs,
                                    clim.rmm_norms,
                                    clim.rmm_pcstd_wind if wind_only else clim.rmm_pcstd,
                                    wind_only=wind_only)
        r1.append(float(a)); r2.append(float(b))
    return r1, r2, wind_only


def build_payload(source, run, clim, steps, members, hist_daily):
    mids = sorted(members)
    payload = {"model": source.key, "run": run.strftime("%Y%m%d%H"), "kind": source.kind,
               "steps": steps, "members": len(mids), "indices": {}}
    for n in INDEX_NAMES:
        series = [[clim.standardize(n, members[m]["raw"][n].get(s)) for s in steps] for m in mids]
        if all(v is None for row in series for v in row):
            continue
        payload["indices"][n] = _pack(source.kind, series)
        if n == "aam":   # raw anomaly in units of 1e24 kg m2 s-1 for tooltips
            raw = [[_scale(members[m]["raw"][n].get(s), 1e-24) for s in steps] for m in mids]
            payload["indices"][n]["raw"] = _pack(source.kind, raw)["value" if source.kind == "det" else "mean"]
    r1s, r2s, wo = [], [], False
    for m in mids:
        a, b, w = rmm_series(clim, run, steps, members[m]["eq"], hist_daily)
        r1s.append(a); r2s.append(b); wo = wo or w
    if any(v is not None for row in r1s for v in row):
        mjo = {"wind_only": wo}
        if source.kind == "det":
            mjo.update(rmm1=r1s[0], rmm2=r2s[0])
        else:
            mjo.update(rmm1=_nanmean(r1s), rmm2=_nanmean(r2s), members_rmm1=r1s, members_rmm2=r2s)
        payload["indices"]["mjo"] = mjo
    return payload


def _scale(v, f):
    return None if v is None else v * f


def _nanmean(rows):
    arr = np.array([[np.nan if v is None else v for v in r] for r in rows], float)
    with np.errstate(all="ignore"):
        m = np.nanmean(arr, axis=0)
    return [None if not np.isfinite(x) else float(x) for x in m]


def _pack(kind, series):
    if kind == "det":
        return {"value": series[0]}
    return {"mean": _nanmean(series), "members": series}


def analysis_update(clim, store, run, members, steps):
    """Use step 0 of the analysis model as the 'observed' value; keep MJO history."""
    m0 = members[sorted(members)[0]]
    vals = {n: clim.standardize(n, m0["raw"][n].get(0)) for n in INDEX_NAMES}
    eq = m0["eq"]
    prof = {}
    if 0 in eq["u850"] and 0 in eq["u200"]:
        prof["u850"] = clim.eq_anom(run, "u850", eq["u850"][0])
        prof["u200"] = clim.eq_anom(run, "u200", eq["u200"][0])
        olr = olr_profiles(eq, steps)
        first = next((s for s in steps if s > 0 and olr.get(s) is not None and s <= 12), None)
        if first is not None:
            prof["olr"] = clim.eq_anom(run, "olr", olr[first])
        store.add_mjo_history(run, prof)
        hist = store.mjo_daily()
        win = [run.date() - dt.timedelta(days=k) for k in range(1, MJO_WINDOW + 1)]
        p2 = {}
        for var in ("olr", "u850", "u200"):
            if var not in prof:
                p2[var] = None
                continue
            past = [hist[d][var] for d in win if d in hist and var in hist[d]]
            p2[var] = prof[var] - np.mean(past, axis=0) if len(past) >= MJO_MIN_DAYS else prof[var]
        wo = p2["olr"] is None
        a, b = ix.rmm_from_profiles(p2["olr"], p2["u850"], p2["u200"], clim.rmm_eofs, clim.rmm_norms,
                                    clim.rmm_pcstd_wind if wo else clim.rmm_pcstd, wind_only=wo)
        vals["rmm1"], vals["rmm2"] = float(a), float(b)
    store.update_analysis(run, vals)
