"""Teleconnection index math. Pure numpy; every field is on the 2.5 deg grid in grid.py.

Index definitions (documented in README):
  AO   projection of daily 1000 hPa height anomalies (20-90N) on the leading EOF of
       monthly 1000 hPa anomalies (CPC method). Positive = low heights over the pole.
  NAO  projection of daily 500 hPa height anomalies on the leading EOF of monthly
       500 hPa anomalies over 20-80N, 90W-40E. Positive = low near Iceland.
  PNA  Wallace & Gutzler (1981) point formula using standardized 500 hPa anomalies:
       0.25*[Z(20N,160W) - Z(45N,165W) + Z(55N,115W) - Z(30N,85W)]
  EPO  500 hPa anomaly averaged over 20-35N,160W-125W minus 55-65N,160W-125W
       (sign chosen so a ridge over Alaska / the NE Pacific gives a negative EPO).
  AAM  global relative atmospheric angular momentum from the zonal wind.
  MJO  Wheeler-Hendon RMM1/RMM2 from 15S-15N OLR, u850 and u200.
All indices except MJO are finally standardized by the 1991-2020 standard deviation of
the monthly-mean index (CPC convention for daily teleconnection values).
"""
import numpy as np
from .grid import LAT, LON, EQ_MASK

A_EARTH = 6.371e6
G = 9.80665
COSLAT = np.cos(np.deg2rad(LAT))

# ---- domains ---------------------------------------------------------------
AO_DOMAIN = dict(lat=(20, 90), lon=(0, 360))
NAO_DOMAIN = dict(lat=(20, 80), lon=(270, 40))       # 90W .. 40E (wraps)
PNA_POINTS = [(20, 200, +1), (45, 195, -1), (55, 245, +1), (30, 275, -1)]
EPO_SOUTH = dict(lat=(20, 35), lon=(200, 235))
EPO_NORTH = dict(lat=(55, 65), lon=(200, 235))


def lon_mask(lon_range):
    a, b = lon_range[0] % 360, lon_range[1] % 360
    if lon_range == (0, 360):
        return np.ones(LON.size, bool)
    if a <= b:
        return (LON >= a) & (LON <= b)
    return (LON >= a) | (LON <= b)


def domain_mask(dom):
    lm = (LAT >= dom["lat"][0]) & (LAT <= dom["lat"][1])
    return lm[:, None] & lon_mask(dom["lon"])[None, :]


def box_mean(field, dom):
    """cos(lat)-weighted area mean of field (..., lat, lon) over a box."""
    m = domain_mask(dom)
    w = (COSLAT[:, None] * np.ones(LON.size)[None, :]) * m
    return np.nansum(field * w, axis=(-2, -1)) / w.sum()


def leading_eofs(X, k, return_vals=False):
    """Leading k EOFs (rows) of a centred data matrix X (time, space).

    Uses the eigen-decomposition of the smaller covariance matrix, which is more
    robust than an SVD of the full matrix (NumPy's SVD can occasionally fail to
    converge on large, perfectly valid inputs)."""
    if not np.isfinite(X).all():
        raise ValueError("EOF input contains missing/invalid values")
    nt, ns = X.shape
    if ns <= nt:
        w, v = np.linalg.eigh(X.T @ X)
        e = v[:, ::-1][:, :k].T
    else:
        w, v = np.linalg.eigh(X @ X.T)
        u = v[:, ::-1][:, :k]
        e = (X.T @ u).T
        e /= np.linalg.norm(e, axis=1, keepdims=True)
    if return_vals:
        return e, np.maximum(w[::-1][:k], 0) / max(nt - 1, 1)
    return e


# ---- EOF-pattern projection (AO, NAO) --------------------------------------
def eof_pattern(monthly_anoms, dom):
    """Leading EOF of monthly anomalies (time, lat, lon) inside dom.

    Returns the pattern as a full-grid array of sqrt(cos lat)-weighted unit-vector
    loadings (zero outside the domain) and the std of the monthly PC.
    """
    m = domain_mask(dom)
    sw = np.sqrt(COSLAT)[:, None] * np.ones(LON.size)[None, :]
    X = (monthly_anoms * sw)[:, m]                      # (time, npts)
    X = np.where(np.isfinite(X), X, np.nan)
    keep = np.isfinite(X).mean(axis=1) > 0.9            # drop months that are mostly missing
    X = X[keep]
    X = X - np.nanmean(X, axis=0)
    X = np.where(np.isfinite(X), X, 0.0)                # remaining isolated gaps -> zero anomaly
    # Remove the long-term trend at every point and the domain-uniform component
    # (heights rising everywhere with warming); otherwise the leading EOF is a monopole
    # trend pattern instead of the NAO/AO dipole.
    t = np.arange(len(X), dtype=float); t -= t.mean()
    X = X - np.outer(t, (t @ X) / (t @ t))
    v = sw[m] / np.linalg.norm(sw[m])
    X = X - np.outer(X @ v, v)
    e = leading_eofs(X, 1)[0]
    pc = X @ e
    pattern = np.zeros(m.shape)
    e = np.nan_to_num(e)
    pattern[m] = e
    return pattern, float(pc.std())


def box_pattern(south, north):
    """Projection pattern equivalent to box_mean(a, south) - box_mean(a, north)."""
    w = COSLAT[:, None] * np.ones(LON.size)[None, :]
    S, N = domain_mask(south), domain_mask(north)
    return (S * w / (w * S).sum() - N * w / (w * N).sum()) / np.sqrt(COSLAT)[:, None]


NAO_SOUTH = dict(lat=(35, 45), lon=(280, 350))     # Azores / subtropical Atlantic ridge
NAO_NORTH = dict(lat=(55, 70), lon=(290, 350))     # Iceland / Greenland low


def dipole_ok(pattern, p1, p2):
    """True if the pattern has opposite-signed, substantial loadings at the two points."""
    def at(la, lo):
        return pattern[int(np.argmin(np.abs(LAT - la))), int(np.argmin(np.abs(LON - lo)))]
    a, b = at(*p1), at(*p2)
    big = np.abs(pattern).max()
    return a * b < 0 and min(abs(a), abs(b)) > 0.25 * big


def project(anom, pattern):
    """Project anomaly field(s) (..., lat, lon) onto an EOF pattern from eof_pattern()."""
    sw = np.sqrt(COSLAT)[:, None]
    return np.nansum(anom * sw * pattern, axis=(-2, -1))


def orient_ao(pattern):
    """Positive AO = negative height anomaly over the polar cap."""
    polar = pattern[LAT >= 70].mean()
    return -pattern if polar > 0 else pattern


def orient_nao(pattern):
    """Positive NAO = negative height anomaly near Iceland (65N, 20W)."""
    i, j = int(np.argmin(np.abs(LAT - 65))), int(np.argmin(np.abs(LON - 340)))
    return -pattern if pattern[i, j] > 0 else pattern


# ---- point / box indices ---------------------------------------------------
def pna_raw(z500_std_anom):
    """Wallace-Gutzler PNA from standardized 500 hPa anomalies (..., lat, lon)."""
    tot = 0.0
    for la, lo, s in PNA_POINTS:
        i, j = int(np.argmin(np.abs(LAT - la))), int(np.argmin(np.abs(LON - lo)))
        tot = tot + s * z500_std_anom[..., i, j]
    return 0.25 * tot


def epo_raw(z500_anom):
    return box_mean(z500_anom, EPO_SOUTH) - box_mean(z500_anom, EPO_NORTH)


# ---- atmospheric angular momentum ------------------------------------------
def relative_aam(u_levels, levels_hpa):
    """Global relative AAM (kg m^2 s^-1).

    u_levels: zonal wind (nlev, lat, lon) [m/s] on pressure levels levels_hpa.
    M_r = (2*pi*a^3/g) * integral( [u] cos^2(phi) dphi dp )
    """
    p = np.asarray(levels_hpa, float) * 100.0
    order = np.argsort(p)
    p = p[order]
    ubar = np.nanmean(np.asarray(u_levels)[order], axis=-1)     # (nlev, lat) zonal mean
    dphi = np.deg2rad(2.5)
    integrand_lat = (ubar * COSLAT[None, :] ** 2).sum(axis=-1) * dphi   # (nlev,)
    trap = getattr(np, "trapezoid", None) or np.trapz
    col = trap(integrand_lat, p)
    return 2.0 * np.pi * A_EARTH ** 3 / G * col


# ---- MJO / RMM -------------------------------------------------------------
def eq_profile(field):
    """15S-15N cos-weighted meridional mean -> (..., lon)."""
    w = COSLAT[EQ_MASK]
    return np.nansum(field[..., EQ_MASK, :] * w[:, None], axis=-2) / w.sum()


def rmm_from_profiles(olr, u850, u200, eofs, norms, pc_std, wind_only=False):
    """Project equatorial anomaly profiles (... ,lon) onto the RMM EOFs.

    Inputs must already be anomalies with the prior-120-day mean removed.
    eofs: (2, 3*nlon) ordered [olr, u850, u200]; norms: (3,) normalization factors;
    pc_std: (2,) standard deviation of the PCs used for the final scaling.
    """
    parts = [
        np.zeros_like(u850) if (wind_only or olr is None) else olr / norms[0],
        u850 / norms[1],
        u200 / norms[2],
    ]
    vec = np.concatenate(parts, axis=-1)
    pcs = vec @ np.asarray(eofs).T
    return pcs[..., 0] / pc_std[0], pcs[..., 1] / pc_std[1]


def compute_rmm_eofs(olr_a, u850_a, u200_a):
    """Combined EOF analysis (Wheeler & Hendon 2004) of daily equatorial anomaly
    profiles (time, lon) with the prior-120-day mean already removed.
    Returns eofs (2, 3*nlon), norms (3,), pc_std_full (2,), pc_std_wind (2,)."""
    names = ("OLR", "u850", "u200")
    for nm, x in zip(names, (olr_a, u850_a, u200_a)):
        if x.size == 0 or not np.isfinite(x).all():
            raise ValueError(f"RMM input {nm} has no valid data ({np.isfinite(x).mean() if x.size else 0:.0%} valid)")
    norms = np.array([np.sqrt(np.mean(np.var(x, axis=0))) for x in (olr_a, u850_a, u200_a)])
    for nm, v in zip(names, norms):
        if not np.isfinite(v) or v <= 0:
            raise ValueError(f"RMM input {nm} has zero variance - its download was probably empty or garbled")
    X = np.concatenate([olr_a / norms[0], u850_a / norms[1], u200_a / norms[2]], axis=1)
    X = X - X.mean(axis=0)
    eofs = leading_eofs(X, 2)
    nl = olr_a.shape[1]
    # Sign conventions: EOF1 has enhanced convection (negative OLR) over the
    # Maritime Continent (~120E); EOF2 over the western Pacific (~160E).
    # Use contrasts so the convention is robust to the exact EOF shape:
    #   EOF1 OLR lower at 120E than at 300E (convection over MC, suppressed W. Hem.)
    #   EOF2 OLR lower at 160E than at 80E  (convection W. Pacific, suppressed Indian Ocean)
    def at(e, lon):
        return e[int(round(lon / 2.5)) % nl]
    if at(eofs[0], 120) - at(eofs[0], 300) > 0:
        eofs[0] *= -1
    if at(eofs[1], 160) - at(eofs[1], 80) > 0:
        eofs[1] *= -1
    pcs = X @ eofs.T
    Xw = X.copy()
    Xw[:, :nl] = 0.0
    pcw = Xw @ eofs.T
    return eofs, norms, pcs.std(axis=0), pcw.std(axis=0)


def mjo_phase(rmm1, rmm2):
    """Wheeler-Hendon phase 1-8 and amplitude."""
    ang = np.degrees(np.arctan2(rmm2, rmm1))          # -180..180
    phase = (np.floor((ang + 180.0) / 45.0).astype(int) % 8) + 1
    return phase, np.hypot(rmm1, rmm2)


# ---- CPC-style rotated PCA (NAO, PNA) ----------------------------------------
# CPC: NAO and PNA are modes of a rotated principal component analysis (RPCA) of
# standardized monthly 500 hPa anomalies over 20-90N, done separately for each calendar
# month using that month and its neighbours (Barnston & Livezey 1987). Daily values are
# projections of daily standardized anomalies onto that month's loading pattern,
# normalized by the standard deviation of the monthly index.
RPCA_DOMAIN = dict(lat=(20, 90), lon=(0, 360))
N_MODES = 10


def varimax(Phi, gamma=1.0, iters=100, tol=1e-7):
    """Varimax rotation of loadings Phi (npts, k)."""
    p, k = Phi.shape
    R = np.eye(k)
    d = 0.0
    for _ in range(iters):
        L = Phi @ R
        u, s, vt = np.linalg.svd(Phi.T @ (L ** 3 - (gamma / p) * L @ np.diag(np.diag(L.T @ L))))
        R = u @ vt
        d_old, d = d, s.sum()
        if d_old and d / d_old < 1 + tol:
            break
    return Phi @ R


def _gauss(lat, lon, la0, lo0, rla=10.0, rlo=25.0):
    dlon = (lon - lo0 + 180) % 360 - 180
    return np.exp(-((lat - la0) / rla) ** 2 - (dlon / rlo) ** 2)


def nao_template():
    L, N = np.meshgrid(LAT, LON, indexing="ij")
    return -_gauss(L, N, 65, 340) + _gauss(L, N, 40, 330)           # positive NAO


def pna_template():
    L, N = np.meshgrid(LAT, LON, indexing="ij")
    return (_gauss(L, N, 20, 200, 8, 20) - _gauss(L, N, 45, 195) + _gauss(L, N, 55, 245)
            - _gauss(L, N, 32, 275, 8, 20))                            # positive PNA


def rpca_month(anoms, years):
    """anoms: monthly 500 hPa anomalies (n, lat, lon) for one 3-month calendar window.
    Returns dict(sigma, nao, pna, nao_sd, pna_sd, nao_match, pna_match)."""
    m = domain_mask(RPCA_DOMAIN)
    X = np.array(anoms, float)[:, m]
    X = np.where(np.isfinite(X), X, 0.0)
    # remove the linear trend over the years at each point, then standardize
    t = np.asarray(years, float); t = t - t.mean()
    X = X - X.mean(axis=0)
    if np.ptp(t) > 0:
        X = X - np.outer(t, (t @ X) / (t @ t))
    sig = X.std(axis=0)
    sig = np.where(sig > 1e-6, sig, 1.0)
    sw = np.sqrt(COSLAT)[:, None] * np.ones(LON.size)[None, :]
    Z = X / sig * sw[m]
    e, ev = leading_eofs(Z, N_MODES, return_vals=True)
    rot = varimax((e * np.sqrt(ev)[:, None]).T)                       # (npts, k)
    out = {"sigma": np.ones(m.shape)}
    out["sigma"][m] = sig
    used = set()
    for name, tmpl in (("nao", nao_template()), ("pna", pna_template())):
        tv = (tmpl * sw)[m]
        cors = [abs(np.corrcoef(rot[:, i], tv)[0, 1]) if i not in used else -1 for i in range(N_MODES)]
        i = int(np.argmax(cors)); used.add(i)
        v = rot[:, i] / np.linalg.norm(rot[:, i])
        if np.corrcoef(v, tv)[0, 1] < 0:
            v = -v
        pat = np.zeros(m.shape); pat[m] = v
        pcs = Z @ v
        out[name] = pat
        out[name + "_sd"] = float(pcs.std())
        out[name + "_match"] = float(cors[i])
    return out


def rpca_project(anom, sigma, pattern, sd):
    """Standardized index for one anomaly field: projection of the standardized,
    sqrt(cos)-weighted anomaly onto a unit-norm RPCA pattern, divided by the monthly sd."""
    sw = np.sqrt(COSLAT)[:, None]
    return float(np.nansum(anom / sigma * sw * pattern) / sd)
