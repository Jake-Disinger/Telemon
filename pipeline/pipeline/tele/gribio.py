"""GRIB download helpers: byte-range fetches driven by .idx/.index files, and decoding
with ecCodes onto the common 2.5 deg grid."""
import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from .grid import regrid

log = logging.getLogger("tele")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "teleconnection-monitor/1.0"


def http_get(url, headers=None, retries=3, timeout=120):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, headers=headers or {}, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning("retry %s (%s)", url, e)
            time.sleep(3 * (attempt + 1))


def url_exists(url):
    try:
        r = SESSION.head(url, timeout=30, allow_redirects=True)
        return r.status_code == 200
    except requests.RequestException:
        return False


# ---- index parsing ----------------------------------------------------------
def ncep_idx(text):
    """Parse a wgrib2-style .idx -> list of dict(key='HGT:500 mb', start, end, member)."""
    lines = [l for l in text.splitlines() if l.strip()]
    recs = []
    for i, line in enumerate(lines):
        p = line.split(":")
        start = int(p[1])
        end = int(lines[i + 1].split(":")[1]) - 1 if i + 1 < len(lines) else None
        recs.append(dict(key=f"{p[3]}:{p[4]}", start=start, end=end, raw=line))
    return recs


def ecmwf_index(text):
    """Parse an ECMWF open-data .index (JSON lines)."""
    recs = []
    for line in text.splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        lev = d.get("levelist")
        key = f"{d['param']}:{lev}" if lev not in (None, "") else d["param"]
        num = int(d.get("number", 0) or 0)
        recs.append(dict(key=key, start=int(d["_offset"]),
                         end=int(d["_offset"]) + int(d["_length"]) - 1, member=num))
    return recs


def fetch_ranges(url, recs, workers=8):
    """Download each selected record with an HTTP Range request. Returns list of bytes."""
    def one(r):
        rng = f"bytes={r['start']}-" + ("" if r["end"] is None else str(r["end"]))
        return http_get(url, headers={"Range": rng})
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, recs))


# ---- decoding ---------------------------------------------------------------
def _decode_handle(eccodes, gid):
    ni = eccodes.codes_get(gid, "Ni")
    nj = eccodes.codes_get(gid, "Nj")
    la1 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
    la2 = eccodes.codes_get(gid, "latitudeOfLastGridPointInDegrees")
    lo1 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
    lo2 = eccodes.codes_get(gid, "longitudeOfLastGridPointInDegrees")
    vals = eccodes.codes_get_values(gid).reshape(nj, ni).astype(float)
    try:
        miss = eccodes.codes_get(gid, "missingValue")
        vals[vals == miss] = np.nan
    except Exception:
        pass
    lats = np.linspace(la1, la2, nj)
    if lo2 < lo1:
        lo2 += 360.0
    lons = np.linspace(lo1, lo2, ni)
    try:
        member = int(eccodes.codes_get(gid, "number"))
    except Exception:
        member = 0
    meta = dict(
        shortName=eccodes.codes_get(gid, "shortName"),
        level=int(eccodes.codes_get(gid, "level")),
        member=member,
    )
    return meta, regrid(vals, lats, lons)


def decode_bytes(blob):
    """Decode every GRIB message in a bytes blob -> list of (meta, field_on_2.5deg)."""
    import eccodes
    out = []
    fd, path = tempfile.mkstemp(suffix=".grib2")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        with open(path, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    out.append(_decode_handle(eccodes, gid))
                finally:
                    eccodes.codes_release(gid)
    finally:
        os.remove(path)
    return out
