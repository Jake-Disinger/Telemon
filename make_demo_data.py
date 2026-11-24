#!/usr/bin/env python3
"""Write SYNTHETIC demo data into web/data so the page can be previewed before the real
ingest runs. The manifest is flagged demo=true and the page shows a banner.
Delete web/data/* (or just run run_ingest.py, which overwrites) to switch to real data."""
import datetime as dt
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "web", "data")
rng = np.random.default_rng(42)
NOW = dt.datetime(2026, 11, 23, 0)
IDX = ["nao", "ao", "pna", "epo", "aam"]
MODELS = {
    "gfs": ("det", [0, 6, 12, 18], 12, 384, 1), "gefs": ("ens", [0, 6, 12, 18], 12, 384, 31),
    "hres": ("det", [0, 12], 12, 240, 1), "eps": ("ens", [0, 12], 12, 360, 51),
    "aifs": ("det", [0, 12], 12, 360, 1), "geps": ("ens", [0, 12], 12, 384, 21),
}


def smooth_series(n, scale, corr=0.93):
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = corr * x[i - 1] + rng.normal(0, scale)
    return x


# "truth" at 6-hourly resolution, from 130 days back to 20 days ahead
hours = np.arange(-130 * 24, 21 * 24, 6)
truth = {k: smooth_series(len(hours), 0.22, 0.985) * 1.3 for k in IDX}
# shape PNA roughly like the reference graphic
t_days = hours / 24
truth["pna"] = 1.4 * np.sin((t_days + 6) / 3.2) * np.exp(-((t_days - 1) / 9) ** 2) + 0.35 * truth["pna"]
phase0 = rng.uniform(0, 2 * np.pi)
mjo_ang = phase0 + 2 * np.pi * t_days / 42 + 0.4 * np.sin(t_days / 17)
mjo_amp = 1.3 + 0.8 * np.sin(t_days / 23) + 0.15 * smooth_series(len(hours), 0.2)
truth["rmm1"], truth["rmm2"] = mjo_amp * np.cos(mjo_ang), mjo_amp * np.sin(mjo_ang)


def truth_at(name, t):
    h = (t - NOW).total_seconds() / 3600
    return float(np.interp(h, hours, truth[name]))


def forecast(name, run, steps, bias_seed, spread):
    """smooth error growth around the truth"""
    g = np.random.default_rng(bias_seed)
    err, out = 0.0, []
    for s in steps:
        err = 0.9 * err + g.normal(0, spread * (0.1 + s / 400))
        out.append(truth_at(name, run + dt.timedelta(hours=s)) * (1 - s / 900) + err)
    return out


def main():
    if os.path.isdir(os.path.join(OUT, "runs")):
        shutil.rmtree(os.path.join(OUT, "runs"))
    man = {"updated": NOW.strftime("%Y-%m-%dT%H:%MZ"), "demo": True, "models": {}}
    for mk, (kind, cycles, sh, mx, nm) in MODELS.items():
        runs = []
        for back in range(0, 6 * 24, 6):
            run = NOW - dt.timedelta(hours=back)
            if run.hour not in cycles:
                continue
            rid = run.strftime("%Y%m%d%H")
            steps = list(range(0, mx + 1, sh))
            seed = hash((mk, rid)) % 2**31
            p = {"model": mk, "run": rid, "kind": kind, "steps": steps, "members": nm, "indices": {}}
            for n in IDX + ["mjo"]:
                if n == "mjo":
                    if kind == "det":
                        p["indices"]["mjo"] = {"wind_only": False,
                                               "rmm1": [round(v, 3) for v in forecast("rmm1", run, steps, seed + 1, .5)],
                                               "rmm2": [round(v, 3) for v in forecast("rmm2", run, steps, seed + 2, .5)]}
                    else:
                        m1 = [[round(v, 2) for v in forecast("rmm1", run, steps, seed + 10 + i, .7)] for i in range(nm)]
                        m2 = [[round(v, 2) for v in forecast("rmm2", run, steps, seed + 500 + i, .7)] for i in range(nm)]
                        p["indices"]["mjo"] = {"wind_only": mk == "geps", "rmm1": np.mean(m1, 0).round(3).tolist(),
                                               "rmm2": np.mean(m2, 0).round(3).tolist(), "members_rmm1": m1, "members_rmm2": m2}
                    continue
                if kind == "det":
                    d = {"value": [round(v, 3) for v in forecast(n, run, steps, seed + IDX.index(n), 1.0)]}
                else:
                    mem = [[round(v, 2) for v in forecast(n, run, steps, seed + 1000 * IDX.index(n) + i, 1.3)] for i in range(nm)]
                    d = {"mean": np.mean(mem, 0).round(3).tolist(), "members": mem}
                if n == "aam":
                    d["raw"] = [round(v * 9.0, 2) for v in (d.get("value") or d["mean"])]
                p["indices"][n] = d
            os.makedirs(os.path.join(OUT, "runs", mk), exist_ok=True)
            with open(os.path.join(OUT, "runs", mk, rid + ".json"), "w") as f:
                json.dump(p, f, separators=(",", ":"))
            runs.append(rid)
        man["models"][mk] = {"runs": sorted(runs, reverse=True)}
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    times = [NOW + dt.timedelta(hours=int(h)) for h in hours if h <= 0 and h % 12 == 0]
    a = {"updated": man["updated"], "times": [t.strftime("%Y%m%d%H") for t in times]}
    for n in IDX + ["rmm1", "rmm2"]:
        a[n] = [round(truth_at(n, t), 3) for t in times]
    with open(os.path.join(OUT, "analysis.json"), "w") as f:
        json.dump(a, f, separators=(",", ":"))
    print("demo data written to", os.path.abspath(OUT))


def demo_maps(man):
    """Synthetic North Pacific maps (moving lows/highs) for the Bering Sea Rule tab."""
    sys.path.insert(0, HERE)
    from tele.maps import META, ROWS, COLS
    from tele.grid import LAT, LON
    lat = LAT[ROWS][:, None]; lon = LON[COLS][None, :]

    def fields(t_hours, seed):
        g = np.random.default_rng(seed)
        z = 5850 - 9.0 * (lat - 15) ** 1.15 + 60 * np.sin(np.deg2rad(lon * 3 + t_hours * 0.4))
        p = np.full(z.shape, 1015.0)
        za = np.zeros(z.shape)
        for k, (la, lo, amp, speed) in enumerate([(52, 175, -38, 0.5), (40, 215, 18, 0.25), (58, 150, -22, 0.6), (33, 160, 14, 0.2)]):
            lo_t = lo + speed * t_hours / 6 + g.normal(0, 2)
            blob = np.exp(-((lat - la) / 7) ** 2 - ((lon - lo_t) / 11) ** 2)
            p += amp * blob
            za += amp * 6 * blob
        return np.round(z + za * 0.6), np.round(za), np.round(p * 10)

    def payload(model, rid, steps, base_h):
        out = dict(META, model=model, run=rid, steps=steps, z500=[], z500a=[], mslp=[])
        for s in steps:
            z, za, p = fields(base_h + s, hash((model, rid, s)) % 2**31)
            out["z500"].append(z.astype(int).ravel().tolist()); out["z500a"].append(za.astype(int).ravel().tolist())
            out["mslp"].append(p.astype(int).ravel().tolist())
        return out

    man["maps"] = {}
    for mk, (kind, cycles, sh, mx, nm) in MODELS.items():
        rids = man["models"][mk]["runs"][:3]
        for rid in rids:
            run = dt.datetime.strptime(rid, "%Y%m%d%H")
            base = (run - NOW).total_seconds() / 3600
            p = payload(mk, rid, list(range(0, min(mx, 360) + 1, 24)), base)
            os.makedirs(os.path.join(OUT, "maps", mk), exist_ok=True)
            json.dump(p, open(os.path.join(OUT, "maps", mk, rid + ".json"), "w"), separators=(",", ":"))
        man["maps"][mk] = rids
    an = []
    for d in range(45, -1, -1):
        t = NOW - dt.timedelta(days=d)
        rid = t.strftime("%Y%m%d%H")
        p = payload("analysis", rid, [0], (t - NOW).total_seconds() / 3600)
        os.makedirs(os.path.join(OUT, "maps", "analysis"), exist_ok=True)
        json.dump(p, open(os.path.join(OUT, "maps", "analysis", rid + ".json"), "w"), separators=(",", ":"))
        an.append(rid)
    man["maps"]["analysis"] = sorted(an, reverse=True)


def demo_typhoons(now_real):
    """Synthetic West Pacific storms (one recurving typhoon near Japan, one weaker
    recurving storm, one active storm heading west) run through the real logic."""
    sys.path.insert(0, HERE)
    from tele import typhoons
    hdr = ("SID,SEASON,NUMBER,BASIN,SUBBASIN,NAME,ISO_TIME,NATURE,LAT,LON,WMO_WIND,USA_WIND\n"
           " ,Year, , , , , , ,degrees_north,degrees_east,kts,kts\n")
    rows = []
    def storm(sid, name, t0, path, wind):
        for k, (la, lo) in enumerate(path):
            t = t0 + dt.timedelta(hours=6 * k)
            rows.append(f"{sid},2026,1,WP,MM,{name},{t:%Y-%m-%d %H:%M:%S},TS,{la:.1f},{lo:.1f},,{wind(k)}\n")
    t0 = now_real - dt.timedelta(days=9)
    p1 = [(14 + 0.5 * k, 140 - 0.9 * k) for k in range(14)] + [(21 + 1.1 * j, 127.4 + 1.5 * j) for j in range(1, 14)]
    storm("2026318N14140", "MAN-YI", t0, p1, lambda k: min(125, 35 + 7 * k) if k < 18 else 125 - 6 * (k - 18))
    t1 = now_real - dt.timedelta(days=20)
    p2 = [(18 + 0.4 * k, 135 - 0.5 * k) for k in range(10)] + [(22 + 1.0 * j, 130.5 + 1.4 * j) for j in range(1, 12)]
    storm("2026307N18135", "PABUK", t1, p2, lambda k: 50)
    t2 = now_real - dt.timedelta(days=2)
    storm("2026325N09150", "WUTIP", t2, [(9 + 0.15 * k, 150 - 1.2 * k) for k in range(9)], lambda k: 40 + 6 * k)
    return typhoons.build([hdr + "".join(rows)], now_real)


if __name__ == "__main__":
    main()
    man = json.load(open(os.path.join(OUT, "manifest.json")))
    demo_maps(man)
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
    nowr = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    ty = demo_typhoons(nowr.replace(hour=nowr.hour - nowr.hour % 6))
    json.dump(ty, open(os.path.join(OUT, "typhoons.json"), "w"), separators=(",", ":"))
    print("demo maps and typhoons written")
