"""Backfill from (simulated) GFS analyses -> analysis.json with indices + observed RMM."""
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backfill_analysis as bf
from tele.climo import Climatology
from tele.store import Store
import test_e2e


def test_backfill_from_gfs_analyses():
    with tempfile.TemporaryDirectory() as tmp:
        test_e2e.fake_climo(os.path.join(tmp, "c.npz"))
        clim = Climatology(os.path.join(tmp, "c.npz"))
        store = Store(os.path.join(tmp, "data"), os.path.join(tmp, "state"))
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")))
        missing = {dt.datetime(2026, 10, 1, 0)}            # one run absent from the archive

        def fake_fetch(run):
            if run in missing:
                return None
            f = test_e2e.fields(0, int(run.timestamp()) % 1000)
            return f, f["olr"]
        now = dt.datetime(2026, 11, 23, 16)
        n = bf.backfill(cfg, clim, store, 100, fetch=fake_fetch, now=now, workers=2)
        a = json.load(open(os.path.join(tmp, "data", "analysis.json")))
        assert n == 200 and len(a["times"]) == 201   # missing 00Z run still gets an RMM value from 12Z
        assert a["times"][0] == "2026081500" and a["times"][-1] == "2026112300"
        for k in ("nao", "ao", "pna", "epo", "aam", "rmm1"):
            assert k in a
        rmm = [v for v in a["rmm1"] if v is not None]
        assert len(rmm) >= 99
