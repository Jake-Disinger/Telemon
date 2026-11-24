"""End-to-end: fake climatology + fake model fields -> run JSON + manifest + analysis."""
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_climatology as bc
from tele.climo import Climatology
from tele.store import Store
from tele.sources import Source
from tele import pipeline
import test_math as tm

LEVELS = [850, 500, 200, 100]


def fake_climo(path):
    h = bc.height_climo(tm._synthetic_years(3))
    ao, nao, names, mu, sd = bc.index_constants(h, tm.rng.normal(size=len(h["mon_a500"])) * 1e24)
    n = 1500
    ts = [dt.datetime(2000, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    lon = np.deg2rad(np.arange(144) * 2.5); ph = 2 * np.pi * np.arange(n)[:, None] / 45
    r = tm.rng.normal
    means, eofs, norms, pcs, pcw = bc.rmm_climo(ts, 230 - 20*np.cos(lon - ph) + r(0, 3, (n, 144)),
                                                3*np.cos(lon - ph) + r(0, .5, (n, 144)),
                                                -6*np.cos(lon - ph) + r(0, 1, (n, 144)))
    np.savez(path, z500_mean=h["z500_mean"], z500_std=h["z500_std"], z1000_mean=h["z1000_mean"],
             ao_pattern=ao, nao_pattern=nao, idx_names=np.array(names), idx_mu=mu, idx_sd=sd,
             aam_levels=np.array(LEVELS), aam_mean=np.full(366, 1.5e26),
             eq_olr_mean=means["olr"], eq_u850_mean=means["u850"], eq_u200_mean=means["u200"],
             rmm_eofs=eofs, rmm_norms=norms, rmm_pcstd=pcs, rmm_pcstd_wind=pcw)


class FakeSource(Source):
    pass


def fields(m, step, with_olr=True):
    g = np.random.default_rng(m * 1000 + step)
    d = {"z500": 5500 + g.normal(0, 50, (73, 144)), "z1000": 100 + g.normal(0, 40, (73, 144)),
         "u": {l: 10 + g.normal(0, 5, (73, 144)) for l in LEVELS}, "olr": None, "ttr": None}
    if with_olr:
        d["olr"] = 230 + g.normal(0, 10, (73, 144))
    return d


def test_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        fake_climo(os.path.join(tmp, "c.npz"))
        clim = Climatology(os.path.join(tmp, "c.npz"))
        store = Store(os.path.join(tmp, "data"), os.path.join(tmp, "state"))
        run = dt.datetime(2026, 11, 23, 0)
        # analysis history for 100 days so the 120-day mean kicks in
        for k in range(100, 0, -1):
            t = run - dt.timedelta(days=k)
            store.add_mjo_history(t, {"u850": np.zeros(144) + 0.1, "u200": np.zeros(144), "olr": np.zeros(144)})
        for kind, nm in (("det", 1), ("ens", 3)):
            src = FakeSource("gfs" if kind == "det" else "gefs",
                             {"kind": kind, "step_hours": 12, "max_hours": 72, "cycles": [0]}, LEVELS)
            data = [{m: fields(m, s) for m in range(nm)} for s in src.steps]
            steps, members = pipeline.collect(src, run, clim, steps_data=data)
            if kind == "det":
                pipeline.analysis_update(clim, store, run, members, steps)
            store.write_run(src.key, run, pipeline.build_payload(src, run, clim, steps, members, store.mjo_daily()))
        man = json.load(open(os.path.join(tmp, "data", "manifest.json")))
        assert man["models"]["gfs"]["runs"] == ["2026112300"]
        g = json.load(open(os.path.join(tmp, "data", "runs", "gfs", "2026112300.json")))
        assert set(g["indices"]) == {"nao", "ao", "pna", "epo", "aam", "mjo"}
        assert len(g["indices"]["pna"]["value"]) == 7
        assert g["indices"]["mjo"]["wind_only"] is False
        e = json.load(open(os.path.join(tmp, "data", "runs", "gefs", "2026112300.json")))
        assert len(e["indices"]["nao"]["members"]) == 3 and len(e["indices"]["mjo"]["members_rmm1"]) == 3
        a = json.load(open(os.path.join(tmp, "data", "analysis.json")))
        assert a["times"] == ["2026112300"] and "rmm1" in a
        vals = [v for v in g["indices"]["nao"]["value"]]
        assert all(abs(v) < 20 for v in vals), vals
