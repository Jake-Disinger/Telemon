"""NCEP/NCAR Reanalysis-1 and interpolated OLR access through the NOAA PSL THREDDS
OPeNDAP server (only the slices we need are transferred)."""
import datetime as dt
import logging

import numpy as np

log = logging.getLogger("tele")

PSL = "https://psl.noaa.gov/thredds/dodsC/Datasets"
URLS = {
    "daily": PSL + "/ncep.reanalysis.dailyavgs/pressure/{var}.{year}.nc",
    "monthly": PSL + "/ncep.reanalysis.derived/pressure/{var}.mon.mean.nc",
    "olr": PSL + "/interp_OLR/olr.day.mean.nc",
}


def open_nc(url):
    import netCDF4
    log.info("open %s", url)
    return netCDF4.Dataset(url)


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
    ds = open_nc((url or URLS["daily"]).format(var=var, year=year))
    check_grid(ds)
    ts = times(ds)
    li = level_index(ds, levels)
    v = ds.variables[var]
    arr = np.stack([np.ma.filled(v[:, i, lat_slice, :].astype(float), np.nan) for i in li], axis=1)
    ds.close()
    return ts, arr
