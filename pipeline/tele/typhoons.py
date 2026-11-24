"""West Pacific tropical cyclone tracks from NOAA IBTrACS for the Typhoon Rule tab.

Typhoon Rule (J. Renken): a typhoon that recurves near Japan tends to be followed by a
trough/storm over the eastern US roughly 6-10 days later. This module finds recurving
storms and the implied eastern-US window; it makes no claim about the rule's skill.
"""
import csv
import datetime as dt
import io
import json
import logging
import os

import numpy as np

log = logging.getLogger("tele")

BASE = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/"
DEFAULT_URLS = [BASE + "ibtracs.last3years.list.v04r01.csv", BASE + "ibtracs.ACTIVE.list.v04r01.csv"]
JAPAN_BOX = dict(lat=(24.0, 46.0), lon=(122.0, 150.0))
TYPHOON_KT = 64


def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def parse_csv(text, since):
    """-> {sid: {"name", "season", "pts": {datetime: (lat, lon0360, wind_kt)}}} for WP storms."""
    rows = csv.DictReader(io.StringIO(text))
    out = {}
    for r in rows:
        if r.get("BASIN", "").strip() != "WP":
            continue
        try:
            t = dt.datetime.strptime(r["ISO_TIME"].strip(), "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue                                            # also skips the units row
        if t < since or t.hour % 6:
            continue
        lat, lon = _f(r.get("LAT")), _f(r.get("LON"))
        if lat is None or lon is None:
            continue
        winds = [w for w in (_f(r.get("USA_WIND")), _f(r.get("WMO_WIND"))) if w is not None]
        s = out.setdefault(r["SID"].strip(), {"name": r.get("NAME", "").strip().title() or "Unnamed",
                                               "season": r.get("SEASON", "").strip(), "pts": {}})
        s["pts"][t] = (lat, lon % 360.0, max(winds) if winds else None)
    return out


def in_box(lat, lon, box):
    return box["lat"][0] <= lat <= box["lat"][1] and box["lon"][0] <= lon <= box["lon"][1]


def analyse(name, pts, now, lag=(6, 10)):
    """pts: sorted list of (time, lat, lon, wind). Finds recurvature (westernmost point
    followed by >= 4 deg of eastward and >= 3 deg of northward motion)."""
    times = [p[0] for p in pts]
    lats = np.array([p[1] for p in pts])
    lons = np.array([p[2] for p in pts])
    winds = [p[3] for p in pts if p[3] is not None]
    vmax = max(winds) if winds else None
    rec = None
    i = int(np.argmin(lons))
    if i < len(pts) - 1 and lats[i] >= 15:
        after_lon, after_lat = lons[i:].max() - lons[i], lats[i:].max() - lats[i]
        if after_lon >= 4 and after_lat >= 3:
            rec = i
    near_japan = False
    if rec is not None:
        near_japan = in_box(lats[rec], lons[rec], dict(lat=(20, 40), lon=(115, 150))) or any(
            in_box(la, lo, JAPAN_BOX) for la, lo in zip(lats[rec:], lons[rec:]))
    out = {
        "name": name, "max_wind": vmax,
        "pts": [[t.strftime("%Y%m%d%H"), round(float(la), 1), round(float(lo), 1),
                 None if w is None else int(round(w))] for (t, la, lo, w) in pts],
        "first": times[0].strftime("%Y%m%d%H"), "last": times[-1].strftime("%Y%m%d%H"),
        "active": bool((now - times[-1]) < dt.timedelta(hours=36)),
        "recurve": None, "near_japan": bool(near_japan), "rule": False, "window": None,
    }
    if rec is not None:
        tr = times[rec]
        out["recurve"] = {"t": tr.strftime("%Y%m%d%H"), "lat": round(float(lats[rec]), 1),
                          "lon": round(float(lons[rec]), 1)}
        out["rule"] = bool(near_japan and vmax is not None and vmax >= TYPHOON_KT)
        if near_japan:
            out["window"] = [(tr + dt.timedelta(days=lag[0])).strftime("%Y%m%d%H"),
                             (tr + dt.timedelta(days=lag[1])).strftime("%Y%m%d%H")]
    return out


def build(texts, now, days=60):
    since = now - dt.timedelta(days=days)
    merged = {}
    for text in texts:                                  # later sources (ACTIVE) override
        for sid, s in parse_csv(text, since).items():
            m = merged.setdefault(sid, {"name": s["name"], "season": s["season"], "pts": {}})
            m["pts"].update(s["pts"])
            if s["name"] and s["name"] != "Unnamed":
                m["name"] = s["name"]
    storms = []
    for sid, s in merged.items():
        pts = sorted((t,) + v for t, v in s["pts"].items())
        if len(pts) < 2:
            continue
        a = analyse(s["name"], pts, now)
        a["id"] = sid
        storms.append(a)
    storms.sort(key=lambda a: a["first"], reverse=True)
    return {"updated": now.strftime("%Y-%m-%dT%H:%MZ"), "source": "NOAA IBTrACS v04r01 (West Pacific)",
            "lag_days": [6, 10], "storms": storms}


def update(data_dir, cfg, now=None, fetch=None):
    """Refresh data/typhoons.json if it is older than cfg['refresh_hours']."""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    path = os.path.join(data_dir, "typhoons.json")
    try:
        with open(path) as f:
            old = json.load(f)
        age = now - dt.datetime.strptime(old["updated"], "%Y-%m-%dT%H:%MZ")
        if age < dt.timedelta(hours=cfg.get("refresh_hours", 6)):
            return False
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        pass
    if fetch is None:
        from .gribio import http_get
        fetch = http_get
    texts = []
    for url in cfg.get("urls", DEFAULT_URLS):
        try:
            b = fetch(url)
            if b:
                texts.append(b.decode("utf-8", "replace"))
        except Exception as e:                                  # noqa: BLE001
            log.warning("typhoon source unavailable %s (%s)", url, e)
    if not texts:
        log.warning("no typhoon data downloaded; keeping the previous file")
        return False
    out = build(texts, now, cfg.get("days", 60))
    os.makedirs(data_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace(tmp, path)
    log.info("typhoons: %d West Pacific storms, %d meet the Typhoon Rule", len(out["storms"]),
             sum(s["rule"] for s in out["storms"]))
    return True
