"""US composites (build_composites.py): helpers and an end-to-end run on synthetic data
with planted signals that the composites must recover."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_composites as bc                                   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def js_phase(kind, pts):
    """Evaluate the phase formulas from web/js/charts.js with node."""
    src = open(os.path.join(ROOT, "web", "js", "charts.js")).read()
    i = src.index("const LAYOUTS = {")
    j = src.index("};", i) + 2
    code = src[i:j] + f"\nconst P = {json.dumps(pts)};\nconsole.log(JSON.stringify(P.map(p => LAYOUTS.{kind}.phaseOf(p[0], p[1]))));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_phases_match_page():
    rng = np.random.default_rng(1)
    pts = rng.normal(size=(400, 2)) * 2
    pts = np.vstack([pts, [[1, 0], [0, 1], [-1, 0], [0, -1], [1, 1], [-1, -1]]])
    try:
        mj = js_phase("mjo", pts.tolist()); gw = js_phase("gwo", pts.tolist())
    except (FileNotFoundError, subprocess.CalledProcessError):
        return                                                  # node not installed (CI)
    assert list(bc.mjo_phase(pts[:, 0], pts[:, 1])) == mj
    assert list(bc.gwo_phase(pts[:, 0], pts[:, 1])) == gw


def test_window_mean_and_groups():
    x = np.arange(10, dtype=float)[:, None]
    w = bc.window_mean(x, 2, 4)
    assert w[0, 0] == 3.0 and np.isnan(w[-3:, 0]).all()
    c = bc.window_mean(x, -2, 2)
    assert c[2, 0] == 2.0 and np.isnan(c[0, 0])
    assert list(bc.event_groups([1, 2, 3, 10, 11, 30])) == [0, 0, 0, 1, 1, 2]
    assert bc.bits_hex([1, 0, 0, 0, 1, 1, 1, 1, 1]) == "8f8"


def test_gwo_xy_tendency():
    t = np.arange(200)
    sig = np.sin(2 * np.pi * t / 40)
    x, y = bc.gwo_xy(sig)
    k = 100
    # tendency of a sine ~ derivative (5-day mean damps the amplitude slightly)
    assert abs(y[k] / bc.GWO_TEND - (2 * np.pi / 40) * np.cos(2 * np.pi * k / 40) * 0.88) < 0.02


def test_aam_from_ubar_matches_full_grid():
    from tele import indices as ix
    lat = 90.0 - 2.5 * np.arange(73)
    u = 20 * np.cos(np.deg2rad(lat))[None, :, None] * np.ones((len(bc.AAM_LEVELS), 1, 144))
    full = ix.relative_aam(u, bc.AAM_LEVELS)
    red = bc.aam_from_ubar(u[:, ::2, ::4].mean(-1), lat[::2], bc.AAM_LEVELS)
    assert abs(red / full - 1) < 0.01


# ---------------------------------------------------------------------------
YEARS = list(range(2001, 2007))


def fake_world():
    rng = np.random.default_rng(7)
    dates = [dt.date(YEARS[0], 1, 1) + dt.timedelta(days=i) for i in range((dt.date(YEARS[-1], 12, 31) - dt.date(YEARS[0], 1, 1)).days + 1)]
    N = len(dates)
    lats = 49.75 - np.arange(26); lons = 234.25 + np.arange(60)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    ocean = ((LA < 31) & (LO < 243)) | ((LA < 40) & (LO > 289))
    east = (LO > 270) & ~ocean
    doy = np.array([d.timetuple().tm_yday for d in dates])
    base = 12 - 12 * np.cos(2 * np.pi * (doy - 15) / 365)
    noise = np.cumsum(rng.normal(size=(N, 1, 1)), 0) * 0.2
    noise = noise - np.convolve(noise[:, 0, 0], np.ones(31) / 31, "same")[:, None, None]
    T = base[:, None, None] + noise + rng.normal(scale=2.0, size=(N, 26, 60))
    # MJO: steady rotation, 48-day period, amplitude 1.5
    ang = -np.pi + 2 * np.pi * np.arange(N) / 48.0
    r1, r2 = 1.5 * np.cos(ang), 1.5 * np.sin(ang)
    ph = bc.mjo_phase(r1, r2)
    # Bering: AR(1) index
    z = np.zeros(N)
    for i in range(1, N):
        z[i] = 0.8 * z[i - 1] + 0.6 * rng.normal()
    z = z / z.std()
    for i in range(N):
        if ph[i] == 5:                         # warm east 5-9 days after MJO phase 5
            T[i + 5:i + 10][:, east] += 5 / 1.8 / 6
        if z[i] <= -1:                         # cold east 17-21 days after a Bering trough
            T[i + 17:i + 22][:, east] -= 4 / 1.8 / 4
    T[:, ocean] = np.nan
    P = rng.gamma(0.6, 4.0, size=(N, 26, 60)); P[:, ocean] = np.nan
    events = [(dates[i], f"TY{i}", f"S{i}") for i in range(200, N - 40, 45)]
    for d, *_ in events:                       # wet east 6-10 days after recurvature
        i = dates.index(d)
        P[i + 6:i + 11][:, east] *= 2.0
    sig = 1.6 * np.sin(2 * np.pi * np.arange(N) / 40.0)
    return dict(dates=dates, lats=lats, lons=lons, T=T, P=P, r1=r1, r2=r2, z=z, events=events, sig=sig, east=east)


def run_build(w, out):
    pos = {d: i for i, d in enumerate(w["dates"])}

    def cpc(var, y):
        idx = [i for i, d in enumerate(w["dates"]) if d.year == y]
        arr = {"tmax": w["T"] + 5, "tmin": w["T"] - 5, "precip": w["P"]}[var][idx]
        return [w["dates"][i] for i in idx], w["lats"], w["lons"], arr

    sd = np.full(366, 100.0)
    readers = {"cpc": cpc,
               "rmm": lambda dates: (w["r1"][[pos[d] for d in dates]], w["r2"][[pos[d] for d in dates]]),
               "aam": lambda dates: (w["sig"], {"slope": 1.0, "offset": 0.0}),
               "bering": lambda dates: (w["z"], sd, []),
               "typhoons": lambda: w["events"]}
    clim = {}
    return bc.build(clim, YEARS, out, readers)


def test_end_to_end_recovers_planted_signals():
    w = fake_world()
    with tempfile.TemporaryDirectory() as out:
        done = run_build(w, out)
        assert done == ["mjo", "gwo", "bsr", "tr"]
        index = json.load(open(os.path.join(out, "index.json")))
        assert set(index["products"]) == {"mjo", "gwo", "bsr", "tr"}
        g = index["grid"]
        cells = np.array([int(c, 16) >> (3 - k) & 1 for c in index["cells"] for k in range(4)][:g["nrows"] * g["ncols"]], bool)
        east = w["east"].ravel()[cells]

        def field(prod, month, cat, win, name):
            doc = json.load(open(os.path.join(out, f"{prod}_{month:02d}.json")))
            c = doc["cats"][cat]
            return c, np.array([np.nan if v is None else v for v in c[name][win]], float)

        c, t = field("mjo", 1, 4, 1, "t")                 # phase 5, days 5-9, DJF
        assert np.nanmean(t[east]) / 10 > 1.8, np.nanmean(t[east]) / 10
        assert abs(np.nanmean(t[~east]) / 10) < 1.0
        sig = np.array([int(ch, 16) >> (3 - k) & 1 for ch in c["ts"][1] for k in range(4)][:t.size], bool)
        assert sig[east].mean() > 0.8
        _, warm = field("mjo", 1, 4, 1, "w")
        assert np.nanmean(warm[east]) > 75
        _, t0 = field("mjo", 1, 4, 3, "t")                # days 15-19: signal gone
        assert abs(np.nanmean(t0[east])) / 10 < 1.5
        assert c["curves"]["ohv"]["t"][7] > 15            # regional curve peaks ~day 7

        c, t = field("bsr", 1, 0, 2, "t")                 # trough, days 17-21
        assert np.nanmean(t[east]) / 10 < -2.5, np.nanmean(t[east]) / 10
        _, tr = field("bsr", 1, 1, 2, "t")                # ridge: no signal
        assert abs(np.nanmean(tr[east])) / 10 < 1.5

        c, p = field("tr", 8, 0, 1, "p")                  # typhoon, days 6-10: wet east
        if not c.get("few"):
            assert np.nanmean(p[east]) > 160
        doc = json.load(open(os.path.join(out, "gwo_01.json")))
        assert sum(c["n"] for c in doc["cats"]) > 0
        size = os.path.getsize(os.path.join(out, "mjo_01.json"))
        assert size < 600_000, size


# ---- readers against fake OPeNDAP datasets (layout of the PSL files) ---------------
class _FakeVar:
    def __init__(self, a, **attrs):
        self.a = a; self.__dict__.update(attrs)

    def __getitem__(self, k):
        return np.ma.masked_invalid(self.a[k])


class _FakeDS:
    def __init__(self, variables, dates):
        self.variables = variables; self._dates = dates

    def close(self):
        pass


def test_read_cpc_and_ubar(monkeypatch, tmp_path):
    from tele import reanalysis as ra
    monkeypatch.setattr(ra, "CACHE", str(tmp_path))
    dates = [dt.date(2001, 1, 1) + dt.timedelta(days=i) for i in range(365)]
    lat = 89.75 - 0.5 * np.arange(360); lon = 0.25 + 0.5 * np.arange(720)
    tmax = np.full((365, 360, 720), np.nan, np.float32)
    tmax[:, (lat > 20) & (lat < 55)] = 10.0
    tmax[:, :, lon > 290] = np.nan                                # Atlantic
    ds = _FakeDS({"lat": _FakeVar(lat), "lon": _FakeVar(lon), "tmax": _FakeVar(tmax)}, dates)
    monkeypatch.setattr(ra, "open_nc", lambda url: ds)
    monkeypatch.setattr(ra, "times", lambda d: [dt.datetime(x.year, x.month, x.day) for x in d._dates])
    ts, la, lo, a = bc.read_cpc("tmax", 2001)
    assert la[0] > la[-1] and abs(la[0] - 49.75) < 1e-6 and abs(la[1] - la[0]) == 1.0
    assert abs(lo[0] - 234.25) < 1e-6 and lo.size == 60 and a.shape == (365, 26, 60)
    assert np.isnan(a[:, :, lo > 290]).all() and np.nanmean(a) == 10.0
    ts2, la2, _, a2 = bc.read_cpc("tmax", 2001)                  # from the cache
    assert np.allclose(np.nan_to_num(a2), np.nan_to_num(a)) and ts2 == ts

    # zonal wind: 17 levels, 73x144 grid
    levels = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10]
    glat = 90 - 2.5 * np.arange(73); glon = 2.5 * np.arange(144)
    u = np.broadcast_to((20 * np.cos(np.deg2rad(glat)))[None, None, :, None], (365, 17, 73, 144)).copy()
    ds2 = _FakeDS({"lat": _FakeVar(glat), "lon": _FakeVar(glon), "level": _FakeVar(np.array(levels)), "uwnd": _FakeVar(u)}, dates)
    monkeypatch.setattr(ra, "open_nc", lambda url: ds2)
    ts, ulat, ub = bc.read_u_zonal_mean(2001)
    assert ub.shape == (365, len(bc.AAM_LEVELS), 37) and np.allclose(ub[0, 0], 20 * np.cos(np.deg2rad(ulat)))
    from tele import indices as ix
    full = ix.relative_aam(u[0, [levels.index(l) for l in bc.AAM_LEVELS]], bc.AAM_LEVELS)
    assert abs(bc.aam_from_ubar(ub[0], ulat, bc.AAM_LEVELS) / full - 1) < 0.01


def test_predictor_histories(monkeypatch):
    from tele import reanalysis as ra
    years = [2001, 2002]
    dates = [dt.date(2001, 1, 1) + dt.timedelta(days=i) for i in range(730)]
    # AAM: reduced-grid values = climatology + a sine anomaly; year 2002 is fine
    aam_mean = np.full(366, 1.0e26)
    clim = {"aam_mean": aam_mean, "idx_names": np.array(["nao", "ao", "pna", "epo", "aam"]), "idx_sd": np.array([1, 1, 1, 1, 2e24])}
    lat37 = 90 - 5.0 * np.arange(37)

    def read(y):
        ds = [d for d in dates if d.year == y]
        base = 1.0e26 / bc.aam_from_ubar(np.ones((len(bc.AAM_LEVELS), 37)), lat37, bc.AAM_LEVELS)
        amp = 1 + 0.02 * np.sin(np.arange(len(ds)) / 7.0)
        return ds, lat37, np.ones((len(ds), len(bc.AAM_LEVELS), 37)) * base * amp[:, None, None]
    sig, fit = bc.aam_history(clim, years, dates, read=read)
    assert np.nanmax(np.abs(sig)) > 0.3 and abs(np.nanmean(sig)) < 0.2

    # Bering: heights = climatology + anomaly; 2003 corrupted (zeros -> huge anomalies)
    years4 = [2001, 2002, 2003, 2004]
    dates4 = [dt.date(2001, 1, 1) + dt.timedelta(days=i) for i in range((dt.date(2004, 12, 31) - dt.date(2001, 1, 1)).days + 1)]
    clim = {"z500_mean": np.full((366, 73, 144), 5500.0)}
    rng = np.random.default_rng(3)

    def readz(y):
        ts = [dt.datetime(d.year, d.month, d.day) for d in dates4 if d.year == y]
        z = np.full((len(ts), 2, 37, 144), 5500.0) + rng.normal(scale=80, size=(len(ts), 1, 1, 1))
        if y == 2003:
            z[:200] = 0.0
        return ts, z
    z, sd, bad = bc.bering_history(clim, years4, dates4, read=readz)
    yrs = np.array([d.year for d in dates4])
    assert bad == [2003] and np.isnan(z[yrs == 2003]).all() and 0.7 < np.nanstd(z) < 1.3


def test_typhoon_events_from_ibtracs_csv():
    import test_rules
    now = dt.datetime(2005, 9, 20)
    ev = bc.typhoon_events([2005], text=test_rules.make_csv(now))
    assert [e[1] for e in ev] == ["Koinu"]


def test_rmm_history_runs(monkeypatch):
    from tele import reanalysis as ra
    years = [2001, 2002]
    neq = int(bc.EQ_MASK.sum())

    def read_levels(var, y, levels, lat_slice=None, url=None):
        ts = [dt.datetime(y, 1, 1) + dt.timedelta(days=i) for i in range(365)]
        k = np.arange(365)[:, None, None, None] + 365 * (y - 2001)
        u = 5 * np.sin(2 * np.pi * (k / 45.0 - np.arange(144)[None, None, None, :] / 144.0)) * np.ones((1, 2, neq, 1))
        return ts, u

    def read_olr(dates, lat_slice):
        k = np.array([(d - dt.date(2001, 1, 1)).days for d in dates])[:, None, None]
        return 230 + 20 * np.sin(2 * np.pi * (k / 45.0 - np.arange(144)[None, None, :] / 144.0)) * np.ones((1, neq, 1))
    monkeypatch.setattr(ra, "read_levels", read_levels)
    monkeypatch.setattr(ra, "read_olr_eq", read_olr)
    rng = np.random.default_rng(0)
    clim = {"eq_olr_mean": np.full((366, 144), 230.0), "eq_u850_mean": np.zeros((366, 144)), "eq_u200_mean": np.zeros((366, 144)),
            "rmm_eofs": rng.normal(size=(2, 432)), "rmm_norms": np.ones(3), "rmm_pcstd": np.ones(2)}
    dates = [dt.date(2001, 1, 1) + dt.timedelta(days=i) for i in range(730)]
    r1, r2 = bc.rmm_history(clim, years, dates)
    assert np.isnan(r1[:120]).all() and np.isfinite(r1[130:]).all() and np.nanstd(r1) > 0
