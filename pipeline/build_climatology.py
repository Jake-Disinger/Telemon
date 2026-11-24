#!/usr/bin/env python3
"""Build climatology.npz (run once; about 30-60 minutes, ~1 GB transferred).

Uses NCEP/NCAR Reanalysis-1 (1991-2020 by default) and NOAA interpolated OLR through
the PSL OPeNDAP server to derive:
  * daily (harmonic-smoothed) mean and std of 500 and 1000 hPa heights
  * AO and NAO loading patterns (leading EOFs of monthly anomalies)
  * normalization constants (std of the monthly-mean index) for NAO/AO/PNA/EPO/AAM
  * mean relative AAM by day of year
  * Wheeler-Hendon RMM EOFs, normalization factors and PC standard deviations

  python build_climatology.py [--start 1991 --end 2020] [--out climatology.npz]
"""
import argparse
import calendar
import datetime as dt
import logging
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from tele import indices as ix                         # noqa: E402
from tele import reanalysis as ra                      # noqa: E402
from tele.climo import cal_index, harmonic_smooth      # noqa: E402
from tele.grid import EQ_MASK, LAT                     # noqa: E402

log = logging.getLogger("tele")
NH = slice(0, 37)          # 90N .. 0


# ---------------------------------------------------------------------------
def doy_mean(sums, counts):
    """sums (366, ...) / counts (366,), filling empty calendar slots (e.g. Feb 29 in a
    period with no leap years) from the neighbouring days."""
    counts = np.asarray(counts, float)
    out = sums / np.maximum(counts, 1).reshape((-1,) + (1,) * (sums.ndim - 1))
    for k in np.where(counts == 0)[0]:
        out[k] = 0.5 * (out[(k - 1) % 366] + out[(k + 1) % 366])
    return out


def clean(a, lo, hi):
    """Missing or fill values (and anything physically impossible) -> NaN."""
    a = np.array(a, dtype=float)
    a[~np.isfinite(a) | (a < lo) | (a > hi)] = np.nan
    return a


def doy_mean_pts(sums, counts):
    """Per-gridpoint version of doy_mean: counts has the same shape as sums."""
    out = sums / np.maximum(counts, 1)
    out[counts == 0] = np.nan
    # fill empty slots from neighbouring days (then anything left with the overall mean)
    for k in range(366):
        bad = np.isnan(out[k])
        if bad.any():
            nb = np.nanmean(np.stack([out[(k - 1) % 366], out[(k + 1) % 366]]), axis=0)
            out[k][bad] = nb[bad]
    allm = np.nanmean(out, axis=0)
    return np.where(np.isnan(out), allm, out)


def height_climo(year_data):
    """year_data: iterable of (times, z500 (t,37,144), z1000 (t,37,144)).
    Returns dict with daily mean/std (366,73,144) and monthly anomaly stacks.
    Missing values are skipped (NOAA's daily files have a few gaps)."""
    s = {k: np.zeros((366, 37, 144)) for k in ("s5", "q5", "s1", "n5", "n1")}
    monthly = []                                           # (year, month, z500, z1000)
    for ts, z5, z1 in year_data:
        z5, z1 = clean(z5, 3000, 7000), clean(z1, -1500, 1500)
        for i, t in enumerate(ts):
            k = cal_index(t)
            g5, g1 = np.isfinite(z5[i]), np.isfinite(z1[i])
            s["s5"][k] += np.where(g5, z5[i], 0); s["q5"][k] += np.where(g5, z5[i], 0) ** 2; s["n5"][k] += g5
            s["s1"][k] += np.where(g1, z1[i], 0); s["n1"][k] += g1
        months = np.array([t.month for t in ts])
        with np.errstate(all="ignore"):
            for m in range(1, 13):
                sel = months == m
                if sel.any():
                    monthly.append((ts[0].year, m, np.nanmean(z5[sel], 0), np.nanmean(z1[sel], 0)))
    n = s["n5"]
    e5, q5, e1 = doy_mean_pts(s["s5"], n), doy_mean_pts(s["q5"], n), doy_mean_pts(s["s1"], s["n1"])
    m5 = harmonic_smooth(e5)
    sd5 = np.sqrt(np.maximum(harmonic_smooth(np.maximum(q5 - e5 ** 2, 1.0)), 1.0))
    m1 = harmonic_smooth(e1)

    def full(nh, fill):
        out = np.full((366, 73, 144), fill, dtype=np.float32)
        out[:, NH, :] = nh
        return out

    z500_mean, z500_std, z1000_mean = full(m5, 0.0), full(sd5, 1.0), full(m1, 0.0)
    a5, a1, mids = [], [], []
    for y, m, z5, z1 in monthly:
        days = [cal_index(dt.date(y, m, d)) for d in range(1, calendar.monthrange(y, m)[1] + 1)]
        f5 = np.zeros((73, 144)); f5[NH] = z5 - z500_mean[days, NH].mean(0)
        f1 = np.zeros((73, 144)); f1[NH] = z1 - z1000_mean[days, NH].mean(0)
        a5.append(f5); a1.append(f1); mids.append(days[len(days) // 2])
    return dict(z500_mean=z500_mean, z500_std=z500_std, z1000_mean=z1000_mean,
                mon_a500=np.array(a5), mon_a1000=np.array(a1), mon_mid=np.array(mids),
                mon_year=np.array([y for y, m, _, _ in monthly]), mon_month=np.array([m for _, m, _, _ in monthly]))


def rpca_climo(h):
    """CPC-style NAO/PNA loading patterns for each calendar month (3-month windows)."""
    out = {k: [] for k in ("sigma", "nao", "pna", "nao_sd", "pna_sd")}
    for m in range(1, 13):
        win = {(m - 2) % 12 + 1, m, m % 12 + 1}
        sel = np.isin(h["mon_month"], list(win))
        r = ix.rpca_month(h["mon_a500"][sel], h["mon_year"][sel] + (h["mon_month"][sel] - 1) / 12.0)
        for k in out:
            out[k].append(r[k])
        log.info("RPCA %s: NAO template match %.2f, PNA template match %.2f",
                 calendar.month_abbr[m], r["nao_match"], r["pna_match"])
    return {k: np.array(v) for k, v in out.items()}


def index_constants(h, aam_monthly_anom):
    """EOF patterns + monthly-index mean/std for normalization."""
    ao_p, _ = ix.eof_pattern(h["mon_a1000"], ix.AO_DOMAIN)
    nao_p, _ = ix.eof_pattern(h["mon_a500"], ix.NAO_DOMAIN)
    ao_p, nao_p = ix.orient_ao(ao_p), ix.orient_nao(nao_p)
    # sanity checks: AO = polar cap vs mid-latitudes, NAO = Iceland vs Azores
    if not ix.dipole_ok(ao_p, (85, 0), (45, 180)) and not ix.dipole_ok(ao_p, (85, 0), (45, 0)):
        log.warning("AO EOF failed the dipole check; check the climatology data")
    if ix.dipole_ok(nao_p, (65, 340), (40, 335)):
        log.info("NAO EOF passed the Iceland/Azores dipole check")
    else:
        log.warning("NAO EOF failed the Iceland/Azores dipole check; using the box-difference NAO "
                    "(500 hPa, 35-45N 80-10W minus 55-70N 70-10W)")
        nao_p = ix.orient_nao(ix.box_pattern(ix.NAO_SOUTH, ix.NAO_NORTH))
    for name, p in (("AO", ao_p), ("NAO", nao_p)):
        def at(la, lo):
            return p[int(np.argmin(np.abs(LAT - la))), int(round(lo / 2.5)) % 144]
        log.info("%s loadings: 85N %+.3f | 65N,20W %+.3f | 40N,25W %+.3f | 45N,180 %+.3f",
                 name, at(85, 0), at(65, 340), at(40, 335), at(45, 180))
    raw = {
        "ao": ix.project(h["mon_a1000"], ao_p),
        "nao": ix.project(h["mon_a500"], nao_p),
        "pna": np.array([ix.pna_raw(a / h["z500_std"][k]) for a, k in zip(h["mon_a500"], h["mon_mid"])]),
        "epo": ix.epo_raw(h["mon_a500"]),
        "aam": np.asarray(aam_monthly_anom),
    }
    names = ["nao", "ao", "pna", "epo", "aam"]
    mu = np.array([0.0 if k == "aam" else np.nanmean(raw[k]) for k in names])
    sd = np.array([np.nanstd(raw[k]) for k in names])
    return ao_p, nao_p, names, mu, sd


def aam_climo(times_m, u_m, levels):
    """times_m: monthly datetimes; u_m: (t, nlev, 73, 144). Returns daily mean (366,)
    and monthly anomalies."""
    aam = np.array([ix.relative_aam(u, levels) for u in u_m])
    months = np.array([t.month for t in times_m])
    clim12 = np.array([aam[months == m].mean() for m in range(1, 13)])
    # daily values: place monthly means at mid-month and smooth with 3 harmonics
    daily = np.zeros(366)
    for d in range(366):
        date = dt.date(2000, 1, 1) + dt.timedelta(days=d)
        daily[d] = clim12[date.month - 1]
    daily = harmonic_smooth(daily, 3)
    anom = aam - clim12[months - 1]
    return daily, anom


LIMITS = {"olr": (50, 500), "u850": (-150, 150), "u200": (-200, 200)}


def rmm_climo(ts, olr, u850, u200):
    """ts: daily datetimes; profiles (t, 144). Returns eq means + RMM EOF quantities."""
    ks = np.array([cal_index(t) for t in ts])
    means, anoms = {}, {}
    for name, x in (("olr", olr), ("u850", u850), ("u200", u200)):
        x = clean(x, *LIMITS[name])
        good = np.isfinite(x)
        s = np.zeros((366, 144)); n = np.zeros((366, 144))
        np.add.at(s, ks, np.where(good, x, 0)); np.add.at(n, ks, good)
        mean = harmonic_smooth(doy_mean_pts(s, n), 3)
        a = x - mean[ks]
        a = np.where(np.isfinite(a), a, 0.0)          # isolated gaps -> zero anomaly
        # remove previous 120-day mean
        cs = np.cumsum(np.vstack([np.zeros((1, 144)), a]), axis=0)
        prior = np.full_like(a, np.nan)
        prior[120:] = (cs[120:-1] - cs[:-121]) / 120.0
        means[name], anoms[name] = mean, a - prior
    for name in ("olr", "u850", "u200"):
        x = anoms[name][120:]
        log.info("RMM input %-4s: %d days, %.1f%% valid, anomaly std %.2f",
                 name, len(x), 100 * np.isfinite(x).mean(), float(np.nanstd(x)) if np.isfinite(x).any() else float("nan"))
    ok = ~np.isnan(anoms["olr"]).any(1) & ~np.isnan(anoms["u850"]).any(1) & ~np.isnan(anoms["u200"]).any(1)
    eofs, norms, pcstd, pcstd_w = ix.compute_rmm_eofs(anoms["olr"][ok], anoms["u850"][ok], anoms["u200"][ok])
    return means, eofs, norms, pcstd, pcstd_w


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1991)
    ap.add_argument("--end", type=int, default=2020)
    ap.add_argument("--out", default=os.path.join(HERE, "climatology.npz"))
    ap.add_argument("--aam-levels", default="850,700,500,300,250,200,100,50")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    years = range(a.start, a.end + 1)
    levels = [int(x) for x in a.aam_levels.split(",")]
    w = np.cos(np.deg2rad(LAT[EQ_MASK]))
    eqs = slice(int(np.where(EQ_MASK)[0][0]), int(np.where(EQ_MASK)[0][-1]) + 1)

    def heights():
        for y in years:
            ts, z = ra.read_levels("hgt", y, [500, 1000], NH)
            yield ts, z[:, 0], z[:, 1]
    log.info("heights ...")
    h = height_climo(heights())

    log.info("monthly zonal wind for AAM ...")
    ds = ra.open_nc(ra.URLS["monthly"].format(var="uwnd"))
    tm = ra.times(ds)
    sel = [i for i, t in enumerate(tm) if a.start <= t.year <= a.end]
    li = ra.level_index(ds, levels)
    um = np.stack([np.ma.filled(ds.variables["uwnd"][sel[0]:sel[-1] + 1, i].astype(float), np.nan) for i in li], 1)
    ds.close()
    aam_daily, aam_anom = aam_climo([tm[i] for i in sel], um, levels)

    log.info("equatorial winds + OLR for the RMM EOFs ...")
    tsu, u850, u200 = [], [], []
    for y in years:
        ts, u = ra.read_levels("uwnd", y, [850, 200], eqs)
        tsu += ts
        u850.append((u[:, 0] * w[None, :, None]).sum(1) / w.sum())
        u200.append((u[:, 1] * w[None, :, None]).sum(1) / w.sum())
    u850, u200 = np.concatenate(u850), np.concatenate(u200)
    olr_eq = ra.read_olr_eq([t.date() for t in tsu], eqs)   # (t, lat, lon), one year per request
    olr = (olr_eq * w[None, :, None]).sum(1) / w.sum()
    for nm, x in (("olr", olr), ("u850", u850), ("u200", u200)):
        log.info("raw %-4s: shape %s, %.1f%% finite, range %.1f .. %.1f", nm, x.shape,
                 100 * np.isfinite(x).mean(), np.nanmin(x), np.nanmax(x))
    means, eofs, norms, pcstd, pcstd_w = rmm_climo(tsu, olr, u850, u200)

    ao_p, nao_p, names, mu, sd = index_constants(h, aam_anom)
    rp = rpca_climo(h)
    # NAO/PNA from the RPCA patterns are already standardized (monthly sd = 1)
    for k in ("nao", "pna"):
        mu[names.index(k)], sd[names.index(k)] = 0.0, 1.0
    np.savez_compressed(
        a.out,
        z500_mean=h["z500_mean"], z500_std=h["z500_std"], z1000_mean=h["z1000_mean"],
        ao_pattern=ao_p, nao_pattern=nao_p, idx_names=np.array(names), idx_mu=mu, idx_sd=sd,
        aam_levels=np.array(levels), aam_mean=aam_daily,
        eq_olr_mean=means["olr"], eq_u850_mean=means["u850"], eq_u200_mean=means["u200"],
        rmm_eofs=eofs, rmm_norms=norms, rmm_pcstd=pcstd, rmm_pcstd_wind=pcstd_w,
        rpca_sigma=rp["sigma"].astype(np.float32), nao_rp=rp["nao"].astype(np.float32), pna_rp=rp["pna"].astype(np.float32),
        nao_rp_sd=rp["nao_sd"], pna_rp_sd=rp["pna_sd"],
        period=np.array([a.start, a.end]))
    log.info("wrote %s", a.out)


if __name__ == "__main__":
    main()
