"""Synthetic checks of the index math (no network needed):  python -m pytest tests/ -q"""
import datetime as dt
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tele import indices as ix
from tele.grid import LAT, LON, regrid
import build_climatology as bc

rng = np.random.default_rng(0)
LAT2, LON2 = np.meshgrid(LAT, LON, indexing="ij")


def test_regrid_identity_and_wrap():
    f = np.sin(np.deg2rad(LON2)) * np.cos(np.deg2rad(LAT2))
    lats = np.arange(-90, 90.01, 0.5); lons = np.arange(-180, 180, 0.5)
    L2, N2 = np.meshgrid(lats, lons, indexing="ij")
    src = np.sin(np.deg2rad(N2)) * np.cos(np.deg2rad(L2))
    assert np.abs(regrid(src, lats, lons) - f).max() < 1e-3


def test_aam_uniform_wind():
    u = np.full((2, 73, 144), 10.0)
    m = ix.relative_aam(u, [1000, 100])
    expect = 2 * np.pi * ix.A_EARTH**3 / ix.G * 10 * (np.pi / 2) * 90000
    assert abs(m / expect - 1) < 0.01, m / expect
    assert 1e25 < m < 1e27


def _synthetic_years(nyears=6):
    """Daily NH heights with a seasonal cycle, an AO mode and noise."""
    ao_mode = np.where(LAT2[:37] > 60, -60.0, np.where(LAT2[:37] > 35, 30.0, 0.0))
    amps = []
    for y in range(2001, 2001 + nyears):
        ts = [dt.datetime(y, 1, 1) + dt.timedelta(days=i) for i in range(365 + (y % 4 == 0))]
        doy = np.array([t.timetuple().tm_yday for t in ts])
        season = 5500 + 100 * np.cos(2 * np.pi * doy / 365)
        a = np.convolve(rng.normal(size=len(ts)), np.ones(15) / 4, "same")
        amps.append(a)
        z5 = season[:, None, None] + a[:, None, None] * ao_mode + rng.normal(0, 10, (len(ts), 37, 144))
        z1 = 100 + a[:, None, None] * ao_mode + rng.normal(0, 10, (len(ts), 37, 144))
        yield ts, z5, z1


def test_height_climo_and_ao_sign():
    h = bc.height_climo(_synthetic_years())
    ao_p, nao_p, names, mu, sd = bc.index_constants(h, rng.normal(size=len(h["mon_a500"])))
    # low heights over the pole -> positive AO
    test = np.zeros((73, 144)); test[LAT > 60] = -60; test[(LAT > 35) & (LAT <= 60)] = 30
    assert ix.project(test, ao_p) > 0
    assert ix.project(-test, ao_p) < 0
    assert np.all(sd > 0)
    i = int(np.argmin(np.abs(LAT - 65))); j = int(np.argmin(np.abs(LON - 340)))
    assert nao_p[i, j] < 0                         # positive NAO = low near Iceland


def test_pna_epo_signs():
    z = np.zeros((73, 144))
    # classic +PNA: high over Hawaii & western Canada, low over Aleutians & SE US
    for la, lo, s in ix.PNA_POINTS:
        z[np.argmin(abs(LAT - la)), np.argmin(abs(LON - lo))] = s
    assert ix.pna_raw(z) > 0.9
    ridge = np.zeros((73, 144)); ridge[(LAT >= 55) & (LAT <= 65)] = 100   # Alaska ridge
    assert ix.epo_raw(ridge) < 0


def test_rmm_eastward_propagation():
    n = 3000
    t = np.arange(n)
    lon = np.deg2rad(LON)
    ts = [dt.datetime(2000, 1, 1) + dt.timedelta(days=int(i)) for i in t]
    ph = 2 * np.pi * t[:, None] / 45.0                     # 45-day eastward wave
    noise = lambda s: rng.normal(0, s, (n, 144))
    olr = 230 - 20 * np.cos(lon[None] - ph) + noise(3)     # convection = low OLR at the crest
    u850 = 3 * np.cos(lon[None] - ph - 0.6) + noise(.5)
    u200 = -6 * np.cos(lon[None] - ph - 0.6) + noise(1)
    means, eofs, norms, pcstd, pcstd_w = bc.rmm_climo(ts, olr, u850, u200)
    # project the latter part and check phases advance 1->8 (eastward)
    seg = slice(2000, 2090)
    a = {}
    for k, x in (("olr", olr), ("u850", u850), ("u200", u200)):
        ks = [bc.cal_index(d) for d in ts]
        an = x - means[k][ks]
        prior = np.array([an[i - 120:i].mean(0) for i in range(2000, 2090)])
        a[k] = an[seg] - prior
    r1, r2 = ix.rmm_from_profiles(a["olr"], a["u850"], a["u200"], eofs, norms, pcstd)
    ang = np.unwrap(np.arctan2(r2, r1))
    assert np.mean(np.diff(ang)) > 0, "phase should rotate counter-clockwise (eastward)"
    amp = np.hypot(r1, r2)
    assert 0.5 < amp.mean() < 3
    # the EOF structures themselves land at the phase boundaries 4|5 and 6|7
    nl = 144
    for k, want in ((0, (4, 5)), (1, (6, 7))):
        e = eofs[k]
        p, _ = ix.mjo_phase(*ix.rmm_from_profiles(e[:nl] * norms[0], e[nl:2*nl] * norms[1],
                                                  e[2*nl:] * norms[2], eofs, norms, pcstd))
        assert int(p) in want, (k, p)
    # OLR minimum of EOF1 sits east of the minimum of the 'Indian Ocean' (-EOF2) pattern


def test_idx_parsers_and_urls():
    import json as _j
    from tele import gribio
    from tele.sources import make_source, fmt
    t = "1:0:d=2026112300:HGT:500 mb:24 hour fcst:\n2:5000:d=2026112300:UGRD:850 mb:24 hour fcst:\n3:9000:d=2026112300:ULWRF:top of atmosphere:18-24 hour ave fcst:\n"
    r = gribio.ncep_idx(t)
    assert r[0]["key"] == "HGT:500 mb" and r[0]["end"] == 4999 and r[2]["end"] is None
    e = "\n".join(_j.dumps(d) for d in [
        {"param": "gh", "levelist": "500", "number": "3", "_offset": 10, "_length": 5},
        {"param": "ttr", "_offset": 15, "_length": 5}])
    r = gribio.ecmwf_index(e)
    assert r[0]["key"] == "gh:500" and r[0]["member"] == 3 and r[0]["end"] == 14 and r[1]["key"] == "ttr"
    cfg = _j.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")))
    run = dt.datetime(2026, 11, 23, 0)
    s = make_source("hres", cfg["models"]["hres"], [850, 200])
    assert s.url(run, 24).endswith("/20261123/00z/ifs/0p25/oper/20261123000000-24h-oper-fc.grib2")
    g = make_source("gefs", cfg["models"]["gefs"], [850])
    assert g.url(run, 6, "gep01").endswith("gefs.20261123/00/atmos/pgrb2ap5/gep01.t00z.pgrb2a.0p50.f006")
    c = make_source("geps", cfg["models"]["geps"], [850])
    assert c.url(run, 24, "HGT", "ISBL_0500").endswith("/00/024/CMC_geps-raw_HGT_ISBL_0500_latlon0p5x0p5_2026112300_P024_allmbrs.grib2")


def test_climatology_survives_missing_values():
    """NOAA files occasionally have gaps / fill values; the build must skip them."""
    def gappy():
        for i, (ts, z5, z1) in enumerate(_synthetic_years(4)):
            z5 = z5.copy()
            z5[10] = np.nan                    # a fully missing day
            z5[40:43, 5:9, 100:110] = np.nan   # a patch of missing points
            z5[200, 3, 3] = -9.96921e36        # netCDF fill value that wasn't masked
            if i == 2:
                z5[60:90] = np.nan             # a whole missing month
            yield ts, z5, z1
    h = bc.height_climo(gappy())
    assert np.isfinite(h["z500_mean"]).all() and np.isfinite(h["z500_std"]).all()
    ao_p, nao_p, names, mu, sd = bc.index_constants(h, rng.normal(size=len(h["mon_a500"])))
    assert np.isfinite(nao_p).all() and np.isfinite(ao_p).all()
    assert np.isfinite(mu).all() and np.isfinite(sd).all() and (sd > 0).all()
    i = int(np.argmin(np.abs(LAT - 65))); j = int(np.argmin(np.abs(LON - 340)))
    assert nao_p[i, j] < 0


def test_rmm_climo_survives_missing_values():
    n = 1500
    ts = [dt.datetime(2000, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    lon = np.deg2rad(LON); ph = 2 * np.pi * np.arange(n)[:, None] / 45
    olr = 230 - 20 * np.cos(lon[None] - ph) + rng.normal(0, 3, (n, 144))
    olr[100:103] = np.nan; olr[500, 7] = 1e20
    u8 = 3 * np.cos(lon[None] - ph) + rng.normal(0, .5, (n, 144))
    u2 = -6 * np.cos(lon[None] - ph) + rng.normal(0, 1, (n, 144))
    means, eofs, norms, pcstd, pcw = bc.rmm_climo(ts, olr, u8, u2)
    assert np.isfinite(eofs).all() and np.isfinite(means["olr"]).all() and np.isfinite(pcstd).all()
