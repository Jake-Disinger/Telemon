"""NCEP/NCAR Reanalysis-1 and interpolated OLR access through the NOAA PSL THREDDS
OPeNDAP server (only the slices we need are transferred).

PSL rate-limits heavy users (HTTP 429), so every open/read is retried with a growing
pause, requests are spaced out, and finished yearly reads are cached on disk
(TELE_CACHE_DIR) so an interrupted build resumes instead of starting over."""
import datetime as dt
import hashlib
import logging
import os
import time

import numpy as np

log = logging.getLogger("tele")

PSL = "https://psl.noaa.gov/thredds/dodsC/Datasets"
URLS = {
    "daily": PSL + "/ncep.reanalysis.dailyavgs/pressure/{var}.{year}.nc",
    "monthly": PSL + "/ncep.reanalysis.derived/pressure/{var}.mon.mean.nc",
    "olr": PSL + "/interp_OLR/olr.day.mean.nc",
}
PAUSE = float(os.environ.get("TELE_PSL_PAUSE", "4"))        # seconds between requests
WAITS = [30, 60, 120, 240, 300, 300, 300, 300]               # back-off after a failure
CACHE = os.environ.get("TELE_CACHE_DIR", "")


def _retry(what, fn):
    for i, wait in enumerate([0] + WAITS):
        if wait:
            log.warning("PSL refused/failed (%s); waiting %ds before retry %d/%d", what, wait, i, len(WAITS))
            time.sleep(wait)
        try:
            out = fn()
            time.sleep(PAUSE)
            return out
        except (OSError, RuntimeError) as e:
            err = e
    raise err


def check_payload(arr, what):
    """PSL sometimes truncates large responses ("DAP DATADDS packet is apparently too
    short") and netCDF then hands back zeros or fill values without raising. Treat a
    large read with no variation as a failed download so it is retried."""
    a = np.ma.asarray(arr)
    if a.size >= 1000:
        vals = a.compressed() if np.ma.is_masked(a) else np.asarray(a).ravel()
        if vals.size == 0 or not np.isfinite(vals).any() or np.nanstd(vals) == 0:
            raise RuntimeError(f"empty or truncated data from PSL ({what})")


class _Var:
    """netCDF variable whose slicing re-opens the dataset and retries on failure."""
    def __init__(self, ds, name):
        self._ds, self._name = ds, name

    def __getitem__(self, key):
        def read():
            try:
                out = self._ds._handle().variables[self._name][key]
                check_payload(out, f"{self._name} {self._ds.url}")
                return out
            except (OSError, RuntimeError):
                self._ds.close()          # drop the connection; the retry re-opens it
                raise
        return _retry(f"{self._name} {self._ds.url}", read)

    def __getattr__(self, attr):
        return getattr(self._ds._handle().variables[self._name], attr)


class RetryDataset:
    def __init__(self, url):
        self.url = url
        self._h = None
        self._handle()

    def _handle(self):
        if self._h is None:
            import netCDF4
            def opener():
                return netCDF4.Dataset(self.url)
            self._h = _retry(f"open {self.url}", opener)
        return self._h

    @property
    def variables(self):
        return {k: _Var(self, k) for k in self._handle().variables}

    def close(self):
        if self._h is not None:
            try:
                self._h.close()
            except Exception:                                   # noqa: BLE001
                pass
            self._h = None


def open_nc(url):
    log.info("open %s", url)
    return RetryDataset(url)


def times(ds):
    import netCDF4
    t = ds.variables["time"]
    out = netCDF4.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
    return [dt.datetime(x.year, x.month, x.day, getattr(x, "hour", 0)) for x in out]


def level_index(ds, levels):
    lv = list(np.asarray(ds.variables["level"][:]).astype(int))
    return [lv.index(int(l)) for l in levels]


def check_grid(ds):
    lat = np.asarray(ds.variables["lat"][:])
    lon = np.asarray(ds.variables["lon"][:])
    assert lat.size == 73 and abs(lat[0] - 90) < 1e-3, "expected 2.5 deg grid, 90N first"
    assert lon.size == 144 and abs(lon[0]) < 1e-3, "expected 0..357.5 longitudes"


def read_levels(var, year, levels, lat_slice=slice(None), url=None):
    """-> times, array (time, nlev, lat, lon) for the requested pressure levels."""
    url = (url or URLS["daily"]).format(var=var, year=year)
    cpath = None
    # cache finished past years only (the current year keeps growing)
    if CACHE and year < dt.date.today().year:
        key = hashlib.md5(f"{url}|{levels}|{lat_slice}".encode()).hexdigest()[:12]
        cpath = os.path.join(CACHE, f"{var}_{year}_{key}.npz")
        if os.path.exists(cpath):
            c = np.load(cpath)
            log.info("cached %s", os.path.basename(cpath))
            return [dt.datetime.fromisoformat(s) for s in c["t"]], c["a"].astype(float)
    ds = open_nc(url)
    check_grid(ds)
    ts = times(ds)
    li = level_index(ds, levels)
    v = ds.variables[var]
    arr = np.stack([np.ma.filled(v[:, i, lat_slice, :].astype(float), np.nan) for i in li], axis=1)
    ds.close()
    if cpath:
        os.makedirs(CACHE, exist_ok=True)
        np.savez(cpath, t=np.array([t.isoformat() for t in ts]), a=arr.astype(np.float32))
    return ts, arr


def read_olr_eq(dates, lat_slice):
    """Daily interpolated OLR for the given dates -> (t, lat, lon), aligned to `dates`.
    Read one calendar year per request (large requests get truncated by the server)
    and cached per year like the other reanalysis reads."""
    ds = open_nc(URLS["olr"])
    to = times(ds)
    pos = {t.date(): i for i, t in enumerate(to)}
    missing = [d for d in dates if d not in pos]
    if missing:
        raise RuntimeError(f"OLR file has no data for {len(missing)} requested days (first {missing[0]})")
    out = {}
    for y in sorted({d.year for d in dates}):
        idx = [pos[d] for d in dates if d.year == y]
        i0, i1 = min(idx), max(idx)
        cpath = None
        if CACHE:
            key = hashlib.md5(f"{URLS['olr']}|{lat_slice}|{i0}|{i1}".encode()).hexdigest()[:12]
            cpath = os.path.join(CACHE, f"olr_{y}_{key}.npz")
            if os.path.exists(cpath):
                log.info("cached %s", os.path.basename(cpath))
                block = np.load(cpath)["a"].astype(float)
            else:
                cpath_new = cpath
                cpath = None
        if cpath is None:
            log.info("OLR %d", y)
            block = np.ma.filled(ds.variables["olr"][i0:i1 + 1, lat_slice, :].astype(float), np.nan)
            if not (100 < np.nanmean(block) < 350):
                raise RuntimeError(f"OLR {y} looks wrong (mean {np.nanmean(block):.1f} W/m2)")
            if CACHE:
                os.makedirs(CACHE, exist_ok=True)
                np.savez(cpath_new, a=block.astype(np.float32))
        for d in dates:
            if d.year == y:
                out[d] = block[pos[d] - i0]
    ds.close()
    return np.stack([out[d] for d in dates])
