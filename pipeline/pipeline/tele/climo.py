"""Climatology container: loads climatology.npz written by build_climatology.py and
turns raw model fields into standardized index values."""
import datetime as dt
import json
import os

import numpy as np
from . import indices as ix

INDEX_NAMES = ["nao", "ao", "pna", "epo", "aam"]


def cal_index(d):
    """Day index 0..365 on a leap-year calendar so Feb 29 has its own slot."""
    return (dt.date(2000, d.month, d.day) - dt.date(2000, 1, 1)).days


def harmonic_smooth(daily, nharm=3):
    """Keep the mean + first nharm annual harmonics of a (366, ...) climatology."""
    f = np.fft.rfft(daily, axis=0)
    f[nharm + 1:] = 0
    return np.fft.irfft(f, n=daily.shape[0], axis=0)


class Climatology:
    def __init__(self, path, calibration=None):
        c = np.load(path, allow_pickle=False)
        # model-vs-reanalysis AAM offset written by calibrate_aam.py (kg m2 s-1)
        self.aam_offset = 0.0
        self.offsets = {}
        if calibration and os.path.exists(calibration):
            with open(calibration) as f:
                cal = json.load(f)
            self.aam_offset = float(cal.get("aam_offset", 0.0))
            self.offsets = {k: float(v) for k, v in cal.get("index_offsets", {}).items()}
        self.z500_mean = c["z500_mean"]
        self.z500_std = c["z500_std"]
        self.z1000_mean = c["z1000_mean"]
        self.ao_pattern = c["ao_pattern"]
        self.nao_pattern = c["nao_pattern"]
        self.idx_mu = dict(zip([str(n) for n in c["idx_names"]], c["idx_mu"]))
        self.idx_sd = dict(zip([str(n) for n in c["idx_names"]], c["idx_sd"]))
        self.aam_levels = [int(x) for x in c["aam_levels"]]
        self.aam_mean = c["aam_mean"]
        self.eq_mean = {"olr": c["eq_olr_mean"], "u850": c["eq_u850_mean"], "u200": c["eq_u200_mean"]}
        self.rmm_eofs = c["rmm_eofs"]
        self.rmm_norms = c["rmm_norms"]
        self.rmm_pcstd = c["rmm_pcstd"]
        self.rmm_pcstd_wind = c["rmm_pcstd_wind"]
        # CPC-style rotated-PCA patterns for NAO/PNA (absent in older climatology files)
        self.rpca = None
        if "nao_rp" in c.files:
            self.rpca = {"sigma": c["rpca_sigma"], "nao": c["nao_rp"], "pna": c["pna_rp"],
                         "nao_sd": c["nao_rp_sd"], "pna_sd": c["pna_rp_sd"],
                         "nao_b": c["nao_rp_b"] if "nao_rp_b" in c.files else np.zeros(12),
                         "pna_b": c["pna_rp_b"] if "pna_rp_b" in c.files else np.zeros(12)}

    def month_weights(self, valid):
        """Blend neighbouring calendar-month patterns so values don't jump at month ends."""
        import calendar
        m, d = valid.month, valid.day
        n_days = calendar.monthrange(valid.year, m)[1]
        mid = (n_days + 1) / 2.0
        f = (d - mid) / n_days                           # -0.5 .. +0.5
        other = m % 12 + 1 if f >= 0 else (m - 2) % 12 + 1
        return [(m - 1, 1.0 - abs(f)), (other - 1, abs(f))]

    def rpca_index(self, name, valid, anom):
        r = self.rpca
        return sum(w * (ix.rpca_project(anom, r["sigma"][k], r[name][k], r[name + "_sd"][k]) + r[name + "_b"][k])
                   for k, w in self.month_weights(valid)) - self.offsets.get(name, 0.0)

    # raw (un-normalized) indices for one valid time ---------------------------
    def raw_indices(self, valid, z500=None, z1000=None, u=None):
        """valid: datetime. z500/z1000: (lat,lon) m. u: dict level->(lat,lon) m/s.
        Returns dict of raw index values (None where inputs are missing)."""
        k = cal_index(valid)
        out = dict.fromkeys(INDEX_NAMES)
        if z500 is not None:
            a = z500 - self.z500_mean[k]
            if self.rpca is not None:
                out["nao"] = self.rpca_index("nao", valid, a)
                out["pna"] = self.rpca_index("pna", valid, a)
            else:
                out["nao"] = float(ix.project(a, self.nao_pattern))
                out["pna"] = float(ix.pna_raw(a / self.z500_std[k]))
            out["epo"] = float(ix.epo_raw(a))
        if z1000 is not None:
            out["ao"] = float(ix.project(z1000 - self.z1000_mean[k], self.ao_pattern))
        if u is not None and all(l in u for l in self.aam_levels):
            m = ix.relative_aam(np.stack([u[l] for l in self.aam_levels]), self.aam_levels)
            out["aam"] = float(m - self.aam_offset - self.aam_mean[k])
        return out

    def standardize(self, name, raw):
        if raw is None:
            return None
        return (raw - self.idx_mu[name]) / self.idx_sd[name]

    # MJO helpers ---------------------------------------------------------------
    def eq_anom(self, valid, var, profile):
        return profile - self.eq_mean[var][cal_index(valid)]
