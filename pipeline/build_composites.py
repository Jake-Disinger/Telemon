#!/usr/bin/env python3
"""US temperature and precipitation composites for the MJO, GWO, Bering Sea Rule and
Typhoon Rule (run once by the Setup workflow; about 20-40 minutes the first time).

For every signal we collect the 1991-2020 days on which it occurred, then average what
the contiguous US did over the following days:

  * MJO  - Wheeler-Hendon RMM phase 1-8 with amplitude >= 1, computed from the same
           reanalysis winds/OLR and EOFs as the live index (climatology.npz).
  * GWO  - Weickmann-Berry phase 1-8 with amplitude >= 1, from daily global relative
           AAM (R1 zonal wind, every 5 deg latitude / 10 deg longitude), processed
           exactly like the live GWO diagram (5-day mean, 5-point tendency).
  * BSR  - Bering Sea 500 hPa height anomaly (50-65N, 165E-160W) <= -1 sigma ("trough")
           or >= +1 sigma ("ridge").
  * TR   - typhoons (>= 64 kt) recurving near Japan, from NOAA IBTrACS, dated at
           recurvature (same test as the live Typhoon Rule tab).

US data: CPC Global Unified daily temperature (tmax/tmin) and precipitation, 0.5 deg,
sampled every 1 deg over 24-50N, 126-66W, through the PSL OPeNDAP server.

Each composite is done for 12 overlapping 3-month seasons and a few lead windows (mean
of days a..b after the signal day). Stored per grid cell: mean temperature anomaly (F),
% of cases warmer than normal, precipitation as % of normal, and a significance flag
(t-test with one degree of freedom per separate event). Regional lag curves (0-30 days)
are stored for a handful of regions. Output: <data_dir>/composites/*.json

  python build_composites.py --climatology climatology.npz --out ../web/data/composites
"""
import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from tele import indices as ix                          # noqa: E402
from tele import reanalysis as ra                       # noqa: E402
from tele import typhoons as ty                         # noqa: E402
from tele.climo import cal_index, harmonic_smooth       # noqa: E402
from tele.grid import EQ_MASK, LAT                      # noqa: E402

log = logging.getLogger("tele")

NH = slice(0, 37)                                       # 90N .. 0 (as in build_climatology)
US_LAT, US_LON = (24.0, 50.0), (234.0, 294.0)           # degrees E
CPC_URLS = {
    "tmax": ra.PSL + "/cpc_global_temp/tmax.{year}.nc",
    "tmin": ra.PSL + "/cpc_global_temp/tmin.{year}.nc",
    "precip": ra.PSL + "/cpc_global_precip/precip.{year}.nc",
}
IBTRACS_WP = ty.BASE + "ibtracs.WP.list.v04r01.csv"
BERING = dict(lat=(50.0, 65.0), lon=(165.0, 200.0))
AAM_LEVELS = [850, 700, 500, 300, 250, 200, 100, 50]    # same as the live AAM index
GWO_TEND = 1.2e25 / 1.4e19 / 86400.0                     # same constant as web/js/app.js
LAGS = 30

# (key, name, (lat_s, lat_n), (lon_w, lon_e) in degrees west-negative)
REGIONS = [
    ("eky", "Eastern Kentucky", (36.5, 38.5), (-85.0, -81.5)),
    ("ohv", "Ohio Valley", (36.0, 41.5), (-89.0, -80.0)),
    ("ne", "Northeast", (40.0, 47.5), (-80.0, -67.0)),
    ("se", "Southeast", (29.5, 35.5), (-90.0, -76.0)),
    ("umw", "Upper Midwest", (42.0, 49.0), (-98.0, -86.0)),
    ("np", "Northern Plains", (42.0, 49.0), (-106.0, -97.0)),
    ("sp", "Southern Plains", (29.0, 37.0), (-104.0, -94.0)),
    ("nw", "Pacific Northwest", (42.0, 49.0), (-125.0, -116.0)),
    ("sw", "Southwest", (31.0, 38.0), (-120.0, -105.0)),
]

PRODUCTS = {
    "mjo": {"name": "MJO", "cats": [f"Phase {p}" for p in range(1, 9)],
            "windows": [[0, 4], [5, 9], [10, 14], [15, 19]],
            "rule": "RMM phase with amplitude >= 1"},
    "gwo": {"name": "GWO", "cats": [f"Phase {p}" for p in range(1, 9)],
            "windows": [[0, 4], [5, 9], [10, 14], [15, 19]],
            "rule": "GWO phase with amplitude >= 1"},
    "bsr": {"name": "Bering Sea Rule", "cats": ["Bering trough", "Bering ridge"],
            "windows": [[0, 4], [12, 16], [17, 21], [22, 26]],
            "rule": "Bering Sea 500 hPa anomaly <= -1 sigma (trough) or >= +1 sigma (ridge)"},
    "tr": {"name": "Typhoon Rule", "cats": ["Recurving typhoon near Japan"],
           "windows": [[1, 5], [6, 10], [11, 15]],
           "rule": "typhoon (>= 64 kt) recurving near Japan; day 0 = recurvature"},
}
MLET = "JFMAMJJASOND"


def season_label(m):
    return "".join(MLET[(m - 2 + k) % 12] for k in range(3))


# ---------------------------------------------------------------------------
# small numeric helpers
def doy_climo(X, ks, nharm):
    """(N, ...) daily values -> harmonic-smoothed day-of-year mean (366, ...)."""
    good = np.isfinite(X)
    s = np.zeros((366,) + X.shape[1:]); n = np.zeros_like(s)
    np.add.at(s, ks, np.where(good, X, 0.0)); np.add.at(n, ks, good)
    m = s / np.maximum(n, 1)
    m[n == 0] = np.nan
    # fill empty day slots (should not happen with 30 years) by the overall mean
    if np.isnan(m).any():
        fill = np.nanmean(m, axis=0)
        m = np.where(np.isnan(m), fill, m)
    return harmonic_smooth(m, nharm)


def window_mean(X, a, b, min_frac=0.6):
    """out[d] = mean of X[d+a .. d+b] (NaN-aware). a may be negative. NaN where the
    window leaves the record or too few values are valid."""
    N = X.shape[0]
    good = np.isfinite(X)
    cs = np.concatenate([np.zeros((1,) + X.shape[1:]), np.cumsum(np.where(good, X, 0.0), 0)])
    cn = np.concatenate([np.zeros((1,) + X.shape[1:]), np.cumsum(good, 0)])
    out = np.full(X.shape, np.nan)
    d = np.arange(max(0, -a), N - max(0, b))
    if d.size == 0:
        return out
    s = cs[d + b + 1] - cs[d + a]
    n = cn[d + b + 1] - cn[d + a]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[d] = np.where(n >= min_frac * (b - a + 1), s / np.maximum(n, 1), np.nan)
    return out


def event_groups(days, gap=3):
    """Label consecutive (within `gap` days) signal days as one event -> group ids."""
    days = np.asarray(days)
    if days.size == 0:
        return days
    return np.concatenate([[0], np.cumsum(np.diff(days) > gap)])


def mjo_phase(r1, r2):
    """Wheeler-Hendon phase 1-8 (same formula as web/js/charts.js)."""
    ang = np.degrees(np.arctan2(r2, r1))
    return (np.floor((ang + 180.0) / 45.0).astype(int) % 8) + 1


def gwo_phase(x, y):
    """GWO phase 1-8 (same formula as web/js/charts.js: clockwise from x<0, y>0)."""
    th = np.degrees(np.arctan2(y, x))
    return (np.floor(np.mod(270.0 - th, 360.0) / 45.0).astype(int) % 8) + 1


def gwo_xy(sigma):
    """Daily AAM (sigma) -> GWO x (5-day centered mean) and y (5-point tendency x const),
    as in gwoFromDaily() in web/js/app.js."""
    v = np.asarray(sigma, float)
    sm = window_mean(v[:, None], -2, 2, min_frac=0.5)[:, 0]          # >= 3 of 5 days
    y = np.full_like(sm, np.nan)
    y[2:-2] = (sm[:-4] - 8 * sm[1:-3] + 8 * sm[3:-1] - sm[4:]) / 12.0
    return sm, y * GWO_TEND


def bad_years_by_spread(years_of_day, series, factor=2.5):
    """Years whose anomaly RMS is far above the typical year (corrupted downloads)."""
    yrs = sorted(set(int(y) for y in years_of_day))
    rms = {}
    for y in yrs:
        v = series[years_of_day == y]
        v = v[np.isfinite(v)]
        rms[y] = float(np.sqrt(np.mean(v ** 2))) if v.size > 30 else np.nan
    med = np.nanmedian(list(rms.values()))
    return sorted(y for y, r in rms.items() if not np.isfinite(r) or r > factor * med or r < med / factor), rms


def smooth121(G):
    """NaN-aware 1-2-1 smoothing in both directions of a (rows, cols) grid; keeps NaNs."""
    out = G.copy()
    for axis in (0, 1):
        g = np.where(np.isfinite(out), out, 0.0)
        w = np.isfinite(out).astype(float)
        num = 2 * g + np.roll(g, 1, axis) + np.roll(g, -1, axis)
        den = 2 * w + np.roll(w, 1, axis) + np.roll(w, -1, axis)
        # no wrap-around at the edges
        if axis == 0:
            num[0] -= g[-1]; den[0] -= w[-1]; num[-1] -= g[0]; den[-1] -= w[0]
        else:
            num[:, 0] -= g[:, -1]; den[:, 0] -= w[:, -1]; num[:, -1] -= g[:, 0]; den[:, -1] -= w[:, 0]
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(np.isfinite(out), num / den, np.nan)
    return out


def bits_hex(mask):
    """bool array -> hex string (4 cells per character, first cell = highest bit)."""
    m = np.asarray(mask, bool)
    pad = (-m.size) % 4
    m = np.concatenate([m, np.zeros(pad, bool)])
    vals = m.reshape(-1, 4) @ np.array([8, 4, 2, 1])
    return "".join("0123456789abcdef"[v] for v in vals)


def ints(a, scale=1.0, lo=None, hi=None):
    a = np.asarray(a, float) * scale
    if lo is not None or hi is not None:
        a = np.clip(a, lo, hi)
    return [None if not np.isfinite(v) else int(round(v)) for v in a]


# ---------------------------------------------------------------------------
# data readers (cached per year like the reanalysis reads)
def _cache_path(tag, year, key):
    if not ra.CACHE:
        return None
    os.makedirs(ra.CACHE, exist_ok=True)
    return os.path.join(ra.CACHE, f"{tag}_{year}_{hashlib.md5(key.encode()).hexdigest()[:12]}.npz")


def read_cpc(var, year):
    """CPC global daily tmax/tmin/precip over the US box, every 2nd 0.5-deg point.
    -> dates, lats (N->S), lons (deg E), array (t, lat, lon) with NaN where missing."""
    url = CPC_URLS[var].format(year=year)
    cpath = _cache_path("cpc_" + var, year, f"{url}|{US_LAT}|{US_LON}|2")
    if cpath and os.path.exists(cpath) and year < dt.date.today().year:
        c = np.load(cpath)
        log.info("cached %s", os.path.basename(cpath))
        return [dt.date.fromisoformat(s) for s in c["t"]], c["lat"], c["lon"], c["a"].astype(float)
    ds = ra.open_nc(url)
    lat = np.asarray(ds.variables["lat"][:], float)
    lon = np.asarray(ds.variables["lon"][:], float) % 360.0
    ii = np.where((lat >= US_LAT[0]) & (lat <= US_LAT[1]))[0]
    jj = np.where((lon >= US_LON[0]) & (lon <= US_LON[1]))[0]
    i0, i1, j0, j1 = ii.min(), ii.max(), jj.min(), jj.max()
    ts = [t.date() for t in ra.times(ds)]
    log.info("CPC %s %d", var, year)
    a = np.ma.filled(ds.variables[var][:, i0:i1 + 1:2, j0:j1 + 1:2].astype(float), np.nan)
    ds.close()
    la, lo = lat[i0:i1 + 1:2], lon[j0:j1 + 1:2]
    if la[0] < la[-1]:
        la, a = la[::-1], a[:, ::-1]
    lim = (-80, 65) if var != "precip" else (0, 1500)
    a = np.where((a >= lim[0]) & (a <= lim[1]), a, np.nan)
    if cpath and year < dt.date.today().year:
        np.savez(cpath, t=np.array([d.isoformat() for d in ts]), lat=la, lon=lo, a=a.astype(np.float32))
    return ts, la, lo, a


def _runs(idx):
    """sorted indices -> list of (start, stop) contiguous runs."""
    out, s = [], idx[0]
    for p, q in zip(idx[:-1], idx[1:]):
        if q != p + 1:
            out.append((s, p + 1)); s = q
    out.append((s, idx[-1] + 1))
    return out


def read_u_zonal_mean(year):
    """Daily R1 zonal wind on AAM_LEVELS, every 5 deg lat / 10 deg lon, reduced to zonal
    means -> dates, lats (37,), ubar (t, nlev, 37)."""
    url = ra.URLS["daily"].format(var="uwnd", year=year)
    cpath = _cache_path("ubar", year, f"{url}|{AAM_LEVELS}|2|4")
    if cpath and os.path.exists(cpath) and year < dt.date.today().year:
        c = np.load(cpath)
        log.info("cached %s", os.path.basename(cpath))
        return [dt.date.fromisoformat(s) for s in c["t"]], c["lat"], c["a"].astype(float)
    ds = ra.open_nc(url)
    ra.check_grid(ds)
    ts = [t.date() for t in ra.times(ds)]
    lat = np.asarray(ds.variables["lat"][:], float)[::2]
    li = ra.level_index(ds, AAM_LEVELS)
    order = np.argsort(li)
    li_sorted = [li[k] for k in order]
    v = ds.variables["uwnd"]
    parts = {}
    log.info("uwnd zonal means %d", year)
    for s, e in _runs(li_sorted):
        blk = np.ma.filled(v[:, s:e, ::2, ::4].astype(float), np.nan)
        blk = np.where(np.abs(blk) < 200, blk, np.nan)
        for k, lev in enumerate(range(s, e)):
            parts[lev] = np.nanmean(blk[:, k], axis=-1)          # (t, 37)
    ds.close()
    ubar = np.stack([parts[l] for l in li], axis=1)              # (t, nlev, 37) in AAM_LEVELS order
    if cpath and year < dt.date.today().year:
        np.savez(cpath, t=np.array([d.isoformat() for d in ts]), lat=lat, a=ubar.astype(np.float32))
    return ts, lat, ubar


def aam_from_ubar(ubar, lat, levels):
    """Global relative AAM (kg m2 s-1) from zonal-mean wind (..., nlev, nlat)."""
    p = np.asarray(levels, float) * 100.0
    order = np.argsort(p)
    cos2 = np.cos(np.deg2rad(lat)) ** 2
    dphi = np.deg2rad(abs(lat[1] - lat[0]))
    integ = (np.nan_to_num(ubar) * cos2).sum(axis=-1) * dphi        # (..., nlev)
    integ = integ[..., order]
    trap = getattr(np, "trapezoid", None) or np.trapz
    return 2.0 * np.pi * ix.A_EARTH ** 3 / ix.G * trap(integ, p[order], axis=-1)


def fetch_text(url, name):
    path = os.path.join(ra.CACHE, name) if ra.CACHE else None
    if path and os.path.exists(path) and os.path.getsize(path) > 1000:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    from tele.gribio import http_get
    b = http_get(url, timeout=600)
    if not b:
        raise RuntimeError(f"could not download {url}")
    text = b.decode("utf-8", "replace")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return text


# ---------------------------------------------------------------------------
# predictors
def rmm_history(clim, years, dates):
    """Daily RMM1/RMM2 for `dates` from cached R1 winds + OLR (as in build_climatology)."""
    from build_climatology import LIMITS, clean
    eqs = slice(int(np.where(EQ_MASK)[0][0]), int(np.where(EQ_MASK)[0][-1]) + 1)
    w = np.cos(np.deg2rad(LAT[EQ_MASK]))
    tsu, u850, u200 = [], [], []
    for y in years:
        ts, u = ra.read_levels("uwnd", y, [850, 200], eqs)
        tsu += ts
        u850.append((u[:, 0] * w[None, :, None]).sum(1) / w.sum())
        u200.append((u[:, 1] * w[None, :, None]).sum(1) / w.sum())
    u850, u200 = np.concatenate(u850), np.concatenate(u200)
    olr_eq = ra.read_olr_eq([t.date() for t in tsu], eqs)
    olr = (olr_eq * w[None, :, None]).sum(1) / w.sum()
    ks = np.array([cal_index(t) for t in tsu])
    an = {}
    for name, x in (("olr", olr), ("u850", u850), ("u200", u200)):
        a = clean(x, *LIMITS[name]) - clim["eq_" + name + "_mean"][ks]
        a = np.where(np.isfinite(a), a, 0.0)
        cs = np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0)
        prior = np.full_like(a, np.nan)
        prior[120:] = (cs[120:-1] - cs[:-121]) / 120.0
        an[name] = a - prior
    r1, r2 = ix.rmm_from_profiles(an["olr"], an["u850"], an["u200"], clim["rmm_eofs"],
                                  clim["rmm_norms"], clim["rmm_pcstd"])
    pos = {t.date(): i for i, t in enumerate(tsu)}
    out1 = np.full(len(dates), np.nan); out2 = np.full(len(dates), np.nan)
    for i, d in enumerate(dates):
        j = pos.get(d)
        if j is not None:
            out1[i], out2[i] = r1[j], r2[j]
    amp = np.hypot(out1, out2)
    log.info("RMM history: %d days, mean amplitude %.2f, %.0f%% of days >= 1",
             np.isfinite(amp).sum(), np.nanmean(amp), 100 * np.nanmean(amp >= 1))
    return out1, out2


def aam_history(clim, years, dates, read=read_u_zonal_mean):
    """Daily global relative AAM anomaly in sigma units of the live index."""
    pos = {d: i for i, d in enumerate(dates)}
    aam = np.full(len(dates), np.nan)
    lat = None
    for y in years:
        ts, lat, ub = read(y)
        m = aam_from_ubar(ub, lat, AAM_LEVELS)
        for d, v in zip(ts, m):
            if d in pos:
                aam[pos[d]] = v
    ks = np.array([cal_index(d) for d in dates])
    # The coarse sampling changes the integral slightly: fit the reduced-grid
    # climatology to the full-grid one stored in climatology.npz and undo the difference.
    cl = doy_climo(aam[:, None], ks, 3)[:, 0]
    full = np.asarray(clim["aam_mean"], float)
    b, a0 = np.polyfit(full, cl, 1) if np.std(full) > 1e-6 * abs(np.mean(full)) else (0.0, 0.0)
    log.info("AAM reduced grid vs full grid climatology: slope %.3f, offset %.3g", b, a0)
    if not (0.7 < b < 1.3):
        log.warning("AAM reduced-grid fit looks off (slope %.2f); using offset only", b)
        b, a0 = 1.0, float(np.mean(cl - full))
    aam = (aam - a0) / b
    names = [str(n) for n in clim["idx_names"]]
    sd = float(clim["idx_sd"][names.index("aam")])
    sig = (aam - full[ks]) / sd
    bad, _ = bad_years_by_spread(np.array([d.year for d in dates]), sig)
    if bad:
        log.warning("AAM: excluding years with implausible values: %s", bad)
        sig[np.isin([d.year for d in dates], bad)] = np.nan
    log.info("AAM history: daily anomaly sd %.2f (monthly-index sigma units)", np.nanstd(sig))
    return sig, {"slope": float(b), "offset": float(a0)}


def bering_history(clim, years, dates, read=None, monthly=None):
    """Daily Bering Sea 500 hPa box-mean anomaly (m) from the cached R1 heights."""
    read = read or (lambda y: ra.read_levels("hgt", y, [500, 1000], NH))
    lat_nh = LAT[NH]
    lon = 2.5 * np.arange(144)
    rows = np.where((lat_nh >= BERING["lat"][0]) & (lat_nh <= BERING["lat"][1]))[0]
    cols = np.where((lon >= BERING["lon"][0]) & (lon <= BERING["lon"][1]))[0]
    wts = np.cos(np.deg2rad(lat_nh[rows]))[:, None] * np.ones(cols.size)[None, :]
    wts /= wts.sum()
    zm = np.asarray(clim["z500_mean"])[:, :37][:, rows][:, :, cols]          # (366, r, c)
    pos = {d: i for i, d in enumerate(dates)}
    raw = np.full(len(dates), np.nan); anom = np.full(len(dates), np.nan)
    for y in years:
        ts, z = read(y)
        z5 = z[:, 0][:, rows][:, :, cols]
        for t, f in zip(ts, z5):
            d = t.date() if isinstance(t, dt.datetime) else t
            i = pos.get(d)
            if i is None or not np.isfinite(f).all():
                continue
            raw[i] = float((f * wts).sum())
            anom[i] = float(((f - zm[cal_index(d)]) * wts).sum())
    yrs = np.array([d.year for d in dates])
    bad, _ = bad_years_by_spread(yrs, anom)
    if monthly is not None:                       # compare with the official monthly file
        mm = monthly(rows, cols, wts)                                     # {(y, m): box mean}
        rms = {}
        for (y, m), v in mm.items():
            sel = (yrs == y) & np.array([d.month == m for d in dates])
            if sel.any() and np.isfinite(raw[sel]).sum() > 20:
                rms.setdefault(y, []).append((np.nanmean(raw[sel]) - v) ** 2)
        off = sorted(y for y, v in rms.items() if np.sqrt(np.mean(v)) > 15)
        bad = sorted(set(bad) | set(off) | (set(years) - set(rms)))
    if bad:
        log.warning("Bering index: excluding years whose daily heights look corrupted: %s", bad)
        anom[np.isin(yrs, bad)] = np.nan
    ks = np.array([cal_index(d) for d in dates])
    var = doy_climo(anom[:, None] ** 2, ks, 3)[:, 0]
    sd = np.sqrt(np.maximum(var, 1.0))
    log.info("Bering index: %d valid days, sd %.0f-%.0f m through the year", np.isfinite(anom).sum(), sd.min(), sd.max())
    return anom / sd[ks], sd, bad


def official_bering_monthly(years):
    def get(rows, cols, wts):
        ds = ra.open_nc(ra.URLS["monthly"].format(var="hgt"))
        tm = ra.times(ds)
        sel = [i for i, t in enumerate(tm) if years[0] <= t.year <= years[-1]]
        li = ra.level_index(ds, [500])[0]
        z = np.ma.filled(ds.variables["hgt"][sel[0]:sel[-1] + 1, li, rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].astype(float), np.nan)
        ds.close()
        return {(tm[i].year, tm[i].month): float((z[k] * wts).sum()) for k, i in enumerate(sel)}
    return get


def typhoon_events(years, text=None):
    """Recurvature dates of typhoons that recurved near Japan (IBTrACS West Pacific)."""
    text = text if text is not None else fetch_text(IBTRACS_WP, "ibtracs_wp.csv")
    storms = ty.parse_csv(text, dt.datetime(years[0], 1, 1) - dt.timedelta(days=30))
    far = dt.datetime(2999, 1, 1)
    out = []
    for sid, s in storms.items():
        pts = sorted((t,) + v for t, v in s["pts"].items())
        if len(pts) < 2:
            continue
        a = ty.analyse(s["name"], pts, far)
        if a["rule"]:
            d = dt.datetime.strptime(a["recurve"]["t"], "%Y%m%d%H").date()
            if years[0] <= d.year <= years[-1]:
                out.append((d, s["name"], sid))
    out.sort()
    log.info("Typhoon Rule: %d typhoons recurved near Japan in %d-%d", len(out), years[0], years[-1])
    return out


# ---------------------------------------------------------------------------
class USData:
    """Daily US temperature anomaly (F) and precipitation on land cells."""
    def __init__(self, dates, lats, lons, tavg, precip):
        self.dates, self.lats, self.lons = dates, lats, lons
        ks = np.array([cal_index(d) for d in dates])
        nr, nc = lats.size, lons.size
        valid = np.isfinite(tavg).mean(0) > 0.9
        self.cells = np.where(valid.ravel())[0]
        T = tavg.reshape(len(dates), -1)[:, self.cells]
        P = precip.reshape(len(dates), -1)[:, self.cells]
        self.T = (T - doy_climo(T, ks, 3)[ks]) * 1.8
        self.P = P
        self.Pc = np.maximum(doy_climo(P, ks, 4)[ks], 0.0)
        self.shape = (nr, nc)
        self.region_cells = {}
        lat2 = np.repeat(lats, nc)[self.cells]
        lon2 = np.tile(lons, nr)[self.cells]
        for key, _, la, lo in REGIONS:
            lo360 = (lo[0] % 360, lo[1] % 360)
            sel = np.where((lat2 >= la[0]) & (lat2 <= la[1]) & (lon2 >= lo360[0]) & (lon2 <= lo360[1]))[0]
            self.region_cells[key] = sel
        self.R = np.stack([np.nanmean(self.T[:, self.region_cells[k]], 1) if self.region_cells[k].size else
                           np.full(len(dates), np.nan) for k, *_ in REGIONS], 1)
        self.R5 = window_mean(self.R, -2, 2)
        log.info("US data: %d land cells, %d days; temperature anomaly sd %.1f F", self.cells.size, len(dates), np.nanstd(self.T))

    def grid(self, v):
        G = np.full(self.shape[0] * self.shape[1], np.nan)
        G[self.cells] = v
        return G.reshape(self.shape)

    def ungrid(self, G):
        return G.ravel()[self.cells]


def composite_set(us, sig_days, cat_of_day, windows, months, n_cats):
    """sig_days: indices of days with a signal; cat_of_day: category (0..n_cats-1) for each.
    Returns per season (12) a list per category of composite dicts."""
    month = np.array([d.month for d in us.dates])
    Tw = {tuple(w): window_mean(us.T, *w) for w in windows}
    Pw = {tuple(w): window_mean(us.P, *w) for w in windows}
    Pcw = {tuple(w): window_mean(us.Pc, *w) for w in windows}
    out = {}
    for m in months:
        smon = {(m - 2) % 12 + 1, m, m % 12 + 1}
        cats = []
        for c in range(n_cats):
            days = np.array([d for d, k in zip(sig_days, cat_of_day) if k == c and month[d] in smon], int)
            cats.append(one_composite(us, days, windows, Tw, Pw, Pcw))
        out[m] = cats
    return out


def one_composite(us, days, windows, Tw, Pw, Pcw, min_events=4):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # all-NaN cells (ocean, gaps)
        return _one_composite(us, days, windows, Tw, Pw, Pcw, min_events)


def _one_composite(us, days, windows, Tw, Pw, Pcw, min_events):
    groups = event_groups(days)
    n_ev = int(groups.max() + 1) if days.size else 0
    res = {"n": int(days.size), "events": n_ev}
    if n_ev < min_events:
        res["few"] = True
        return res
    t_list, w_list, p_list, ts_list, ps_list = [], [], [], [], []
    for w in windows:
        w = tuple(w)
        T = Tw[w][days]; P = Pw[w][days]; Pc = Pcw[w][days]
        ok = np.isfinite(T)
        with np.errstate(invalid="ignore", divide="ignore"):
            tm = np.nanmean(T, 0)
            warm = 100.0 * (np.where(ok, T > 0, False).sum(0) / np.maximum(ok.sum(0), 1))
            pm, pcm = np.nanmean(P, 0), np.nanmean(Pc, 0)
            pct = np.where(pcm > 0.3, 100.0 * pm / pcm, np.nan)        # skip very dry climates
            # one degree of freedom per event: average within events first
            def tstat(X):
                ev = np.array([np.nanmean(X[groups == g], 0) for g in range(n_ev)])
                sd = np.nanstd(ev, 0, ddof=1)
                return np.nanmean(ev, 0) / (sd / np.sqrt(n_ev))
            tt = tstat(T); tp = tstat(P - Pc)
        t_list.append(ints(us.ungrid(smooth121(us.grid(tm))), 10))
        w_list.append(ints(us.ungrid(smooth121(us.grid(warm))), 1, 0, 100))
        p_list.append(ints(us.ungrid(smooth121(us.grid(pct))), 1, 0, 400))
        ts_list.append(bits_hex(np.abs(tt) >= 2.0))
        ps_list.append(bits_hex(np.abs(tp) >= 2.0))
    res.update(t=t_list, w=w_list, p=p_list, ts=ts_list, ps=ps_list)
    # regional lag curves of the 5-day mean temperature anomaly
    curves = {}
    N = len(us.dates)
    for r, (key, *_) in enumerate(REGIONS):
        tm, wm = [], []
        for L in range(LAGS + 1):
            dd = days + L
            v = us.R5[dd[dd < N], r]
            v = v[np.isfinite(v)]
            tm.append(np.mean(v) if v.size else np.nan)
            wm.append(100.0 * np.mean(v > 0) if v.size else np.nan)
        curves[key] = {"t": ints(tm, 10), "w": ints(wm, 1)}
    res["curves"] = curves
    return res


def write_product(out_dir, key, comps, meta_cats):
    os.makedirs(out_dir, exist_ok=True)
    summary = {}
    for m, cats in comps.items():
        doc = {"product": key, "season": season_label(m), "month": m,
               "cats": [dict(c, label=meta_cats[i]) for i, c in enumerate(cats)]}
        path = os.path.join(out_dir, f"{key}_{m:02d}.json")
        with open(path, "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        summary[m] = [[c["n"], c["events"]] for c in cats]
    return summary


# ---------------------------------------------------------------------------
def build(clim, years, out_dir, readers):
    dates = [dt.date(years[0], 1, 1) + dt.timedelta(days=i)
             for i in range((dt.date(years[-1], 12, 31) - dt.date(years[0], 1, 1)).days + 1)]
    pos = {d: i for i, d in enumerate(dates)}

    # ---- US temperature and precipitation
    arrays, lats, lons = {}, None, None
    for var in ("tmax", "tmin", "precip"):
        A = None
        for y in years:
            ts, la, lo, a = readers["cpc"](var, y)
            if A is None:
                lats, lons = la, lo
                A = np.full((len(dates), la.size, lo.size), np.nan, np.float32)
            if la.size != lats.size or lo.size != lons.size or np.abs(la - lats).max() > 0.01:
                raise RuntimeError(f"{var} {y}: unexpected grid")
            for d, f in zip(ts, a):
                if d in pos:
                    A[pos[d]] = f
        arrays[var] = A
        log.info("%s: %.1f%% of values present", var, 100 * np.isfinite(A).mean())
    us = USData(dates, lats, lons, (arrays["tmax"] + arrays["tmin"]) / 2.0, arrays["precip"])
    del arrays
    months = range(1, 13)
    index = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "period": [years[0], years[-1]],
        "grid": {"lat_n": float(lats[0]), "lon_w": float(lons[0]), "res": float(abs(lats[1] - lats[0])),
                 "nrows": int(lats.size), "ncols": int(lons.size)},
        "cells": bits_hex(np.isin(np.arange(lats.size * lons.size), us.cells)),
        "regions": [{"key": k, "name": n, "lat": list(la), "lon": [lo[0] % 360, lo[1] % 360]} for k, n, la, lo in REGIONS],
        "seasons": [{"m": m, "label": season_label(m)} for m in months],
        "lags": LAGS,
        "sources": {
            "us": "CPC Global Unified daily temperature and precipitation (0.5 deg, sampled every 1 deg), via NOAA PSL",
            "mjo": "RMM index recomputed from NCEP/NCAR Reanalysis-1 winds and NOAA interpolated OLR (same EOFs as the live index)",
            "gwo": "Global relative AAM from NCEP/NCAR Reanalysis-1 daily zonal wind, 850-50 hPa",
            "bsr": "NCEP/NCAR Reanalysis-1 daily 500 hPa heights",
            "tr": "NOAA IBTrACS v04r01 West Pacific best tracks"},
        "products": {},
    }

    def add(key, sig_days, cats_of_day, extra=None):
        P = PRODUCTS[key]
        comps = composite_set(us, sig_days, cats_of_day, P["windows"], months, len(P["cats"]))
        counts = write_product(out_dir, key, comps, P["cats"])
        index["products"][key] = dict({"name": P["name"], "cats": P["cats"], "windows": P["windows"],
                                       "rule": P["rule"], "counts": {str(m): v for m, v in counts.items()}}, **(extra or {}))
        log.info("%s composites written (%d signal days)", key, len(sig_days))

    done = []
    for key, fn in (("mjo", lambda: readers["rmm"](dates)), ("gwo", lambda: readers["aam"](dates)),
                    ("bsr", lambda: readers["bering"](dates)), ("tr", lambda: readers["typhoons"]())):
        try:
            if key == "mjo":
                r1, r2 = fn()
                amp = np.hypot(r1, r2)
                ph = mjo_phase(np.nan_to_num(r1), np.nan_to_num(r2))
                d = np.where(np.isfinite(amp) & (amp >= 1))[0]
                add("mjo", d, ph[d] - 1)
            elif key == "gwo":
                sig, fit = fn()
                x, y = gwo_xy(sig)
                amp = np.hypot(x, y)
                ph = gwo_phase(np.nan_to_num(x), np.nan_to_num(y))
                d = np.where(np.isfinite(amp) & (amp >= 1))[0]
                add("gwo", d, ph[d] - 1, {"aam_fit": fit})
            elif key == "bsr":
                z, sd, bad = fn()
                d = np.where(np.isfinite(z) & (np.abs(z) >= 1))[0]
                add("bsr", d, np.where(z[d] <= -1, 0, 1),
                    {"box": BERING, "sd": [round(float(v), 1) for v in sd], "excluded_years": bad})
            else:
                ev = fn()
                d = np.array([pos[e[0]] for e in ev if e[0] in pos], int)
                add("tr", d, np.zeros(d.size, int), {"events": [[e[0].isoformat(), e[1]] for e in ev]})
            done.append(key)
        except Exception:                                      # noqa: BLE001
            log.exception("%s composites failed; the others continue", key)
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"))
    log.info("composites done: %s", ", ".join(done) or "none")
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--climatology", default=os.environ.get("TELE_CLIMATOLOGY", os.path.join(HERE, "climatology.npz")))
    ap.add_argument("--out", default=os.path.join(os.environ.get("TELE_DATA_DIR", os.path.join(HERE, "..", "web", "data")), "composites"))
    ap.add_argument("--start", type=int, default=None)
    ap.add_argument("--end", type=int, default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    clim = dict(np.load(a.climatology, allow_pickle=False))
    p0, p1 = (int(v) for v in clim.get("period", [1991, 2020]))
    years = list(range(a.start or p0, (a.end or p1) + 1))
    readers = {
        "cpc": read_cpc,
        "rmm": lambda dates: rmm_history(clim, years, dates),
        "aam": lambda dates: aam_history(clim, years, dates),
        "bering": lambda dates: bering_history(clim, years, dates, monthly=official_bering_monthly(years)),
        "typhoons": lambda: typhoon_events(years),
    }
    done = build(clim, years, a.out, readers)
    if not done:
        sys.exit(1)


if __name__ == "__main__":
    main()
