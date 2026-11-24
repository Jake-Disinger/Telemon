"""North Pacific map fields for the Bering Sea Rule tab (2.5 deg, 15-75N, 120E-120W).

Each saved map holds, per forecast day: 500 hPa height (m), its anomaly from the
1991-2020 daily climatology (m) and mean sea-level pressure (tenths of hPa), as
row-major integer lists from north to south and west to east."""
import numpy as np

from .grid import LAT, LON

LAT_N, LAT_S = 75.0, 15.0
LON_W, LON_E = 120.0, 240.0
ROWS = np.where((LAT <= LAT_N + 1e-6) & (LAT >= LAT_S - 1e-6))[0]
COLS = np.where((LON >= LON_W - 1e-6) & (LON <= LON_E + 1e-6))[0]
META = {"lat_n": LAT_N, "lat_s": LAT_S, "lon_w": LON_W, "lon_e": LON_E, "res": 2.5,
        "nrows": int(ROWS.size), "ncols": int(COLS.size)}


def region(field):
    return np.asarray(field, float)[np.ix_(ROWS, COLS)]


class MapAccumulator:
    """Averages the region fields over ensemble members for each forecast step."""
    def __init__(self):
        self.sums = {}

    def add(self, step, z500=None, z500a=None, mslp=None):
        d = self.sums.setdefault(step, {})
        for name, f in (("z500", z500), ("z500a", z500a), ("mslp", mslp)):
            if f is None:
                continue
            s, n = d.get(name, (0.0, 0))
            d[name] = (s + region(f), n + 1)

    def payload(self, model, run_id, steps=None):
        steps = sorted(self.sums) if steps is None else [s for s in steps if s in self.sums]
        out = dict(META, model=model, run=run_id, steps=steps, z500=[], z500a=[], mslp=[])
        for s in steps:
            d = self.sums[s]
            for name, scale in (("z500", 1), ("z500a", 1), ("mslp", 0.1)):
                if name in d:
                    tot, n = d[name]
                    v = tot / n
                    if name == "mslp" and np.nanmean(v) > 2000:      # Pa -> hPa
                        v = v / 100.0
                    out[name].append([None if not np.isfinite(x) else int(round(x / scale)) for x in v.ravel()])
                else:
                    out[name].append(None)
        return out
