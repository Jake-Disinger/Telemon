"""Bering-Sea-Rule maps and Typhoon-Rule track logic."""
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tele import typhoons, pipeline
from tele.maps import MapAccumulator, META
from tele.climo import Climatology
from tele.store import Store
from tele.sources import Source
import test_e2e

HDR = ("SID,SEASON,NUMBER,BASIN,SUBBASIN,NAME,ISO_TIME,NATURE,LAT,LON,WMO_WIND,WMO_PRES,WMO_AGENCY,"
       "TRACK_TYPE,DIST2LAND,LANDFALL,IFLAG,USA_AGENCY,USA_ATCF_ID,USA_LAT,USA_LON,USA_RECORD,USA_STATUS,USA_WIND\n"
       " ,Year, , , , , , ,degrees_north,degrees_east,kts,mb, , ,km,km, , , ,degrees_north,degrees_east, , ,kts\n")


def row(sid, name, t, lat, lon, wind, basin="WP"):
    return (f"{sid},2026,30,{basin},MM,{name},{t:%Y-%m-%d %H:%M:%S},TS,{lat},{lon},,,,main,0,0,,jtwc,,"
            f"{lat},{lon},,TY,{wind}\n")


def make_csv(now):
    s = HDR
    t0 = now - dt.timedelta(days=12)
    # recurving typhoon: west-northwest, then turns NE past Japan
    for k in range(24):
        t = t0 + dt.timedelta(hours=6 * k)
        if k < 12:
            lat, lon = 15 + 0.6 * k, 135 - 1.0 * k
        else:
            j = k - 12
            lat, lon = 22.2 + 1.2 * j, 124 + 1.6 * j
        s += row("2026300N15135", "KOINU", t, round(lat, 1), round(lon, 1), 90)
        s += row("2026300N15135", "KOINU", t + dt.timedelta(hours=3), round(lat, 1), round(lon, 1), 90)  # 3-hourly row, dropped
    # straight-moving tropical storm into the Philippines (no recurvature)
    for k in range(10):
        s += row("2026310N10140", "MAWAR", now - dt.timedelta(days=3) + dt.timedelta(hours=6 * k), 10 + 0.2 * k, 140 - 1.5 * k, 45)
    # an Atlantic storm that must be ignored, and an old storm outside the window
    s += row("2026300N20300", "ATL", now, 20, -60, 80, basin="NA")
    s += row("2026100N10140", "OLD", now - dt.timedelta(days=200), 10, 140, 50)
    s += row("2026100N10140", "OLD", now - dt.timedelta(days=199), 11, 139, 50)
    return s


def test_typhoon_rule_detection():
    now = dt.datetime(2026, 11, 23, 12)
    out = typhoons.build([make_csv(now)], now)
    names = {s["name"]: s for s in out["storms"]}
    assert set(names) == {"Koinu", "Mawar"}
    k = names["Koinu"]
    assert k["recurve"] is not None and k["near_japan"] and k["rule"]
    assert abs(k["recurve"]["lon"] - 124.0) < 1.1
    rec_t = dt.datetime.strptime(k["recurve"]["t"], "%Y%m%d%H")
    w0, w1 = (dt.datetime.strptime(x, "%Y%m%d%H") for x in k["window"])
    assert w0 - rec_t == dt.timedelta(days=6) and w1 - rec_t == dt.timedelta(days=10)
    assert all(int(p[0][-2:]) % 6 == 0 for p in k["pts"])
    m = names["Mawar"]
    assert m["recurve"] is None and not m["rule"] and m["window"] is None and m["active"]


def test_typhoon_update_refresh_logic():
    now = dt.datetime(2026, 11, 23, 12)
    calls = []
    def fetch(url):
        calls.append(url); return make_csv(now).encode()
    with tempfile.TemporaryDirectory() as tmp:
        assert typhoons.update(tmp, {"urls": ["a", "b"]}, now=now, fetch=fetch)
        assert not typhoons.update(tmp, {"urls": ["a"]}, now=now + dt.timedelta(hours=2), fetch=fetch)
        assert typhoons.update(tmp, {"urls": ["a"]}, now=now + dt.timedelta(hours=7), fetch=fetch)
        d = json.load(open(os.path.join(tmp, "typhoons.json")))
        assert d["storms"] and len(calls) == 3
        # a failed download keeps the previous file
        assert not typhoons.update(tmp, {"urls": ["a"]}, now=now + dt.timedelta(hours=20), fetch=lambda u: None)


def test_maps_written_for_runs_and_analysis():
    with tempfile.TemporaryDirectory() as tmp:
        test_e2e.fake_climo(os.path.join(tmp, "c.npz"))
        clim = Climatology(os.path.join(tmp, "c.npz"))
        store = Store(os.path.join(tmp, "data"), os.path.join(tmp, "state"))
        run = dt.datetime(2026, 11, 23, 0)
        src = Source("gefs", {"kind": "ens", "step_hours": 12, "max_hours": 72, "cycles": [0]}, test_e2e.LEVELS)
        data = []
        for s in src.steps:
            step = {}
            for m in range(3):
                f = test_e2e.fields(m, s)
                f["mslp"] = np.full((73, 144), 101000.0 + 100 * m)          # Pa
                step[m] = f
            data.append(step)
        acc = MapAccumulator()
        steps, members = pipeline.collect(src, run, clim, steps_data=data, maps=acc)
        p = acc.payload("gefs", "2026112300")
        assert p["steps"] == [0, 24, 48, 72]                                  # daily only
        n = META["nrows"] * META["ncols"]
        assert META["nrows"] == 25 and META["ncols"] == 49 and len(p["mslp"][0]) == n
        assert p["mslp"][0][0] == 10110                                     # mean of 1010,1011,1012 hPa in tenths
        assert abs(np.mean(p["z500a"][1])) < 200
        store.write_map("gefs", run, p)
        store.write_map("analysis", run, acc.payload("analysis", "2026112300", [0]))
        old = run - dt.timedelta(days=60)
        store.write_map("analysis", old, acc.payload("analysis", old.strftime("%Y%m%d%H"), [0]))
        man = json.load(open(os.path.join(tmp, "data", "manifest.json")))
        assert man["maps"]["gefs"] == ["2026112300"]
        assert man["maps"]["analysis"] == ["2026112300"]                    # 60-day-old map pruned on write
