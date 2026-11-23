"""Common analysis grid (2.5 deg, same as NCEP/NCAR Reanalysis-1) and regridding."""
import numpy as np
from scipy.interpolate import RegularGridInterpolator

LAT = 90.0 - 2.5 * np.arange(73)      # 90 .. -90 (north to south)
LON = 2.5 * np.arange(144)            # 0 .. 357.5 (degrees east)
NLAT, NLON = LAT.size, LON.size

# Equatorial band used by the RMM (MJO) index
EQ_MASK = (LAT >= -15.0) & (LAT <= 15.0)


def lat_index(lat):
    return int(np.argmin(np.abs(LAT - lat)))


def lon_index(lon):
    return int(np.argmin(np.abs(LON - (lon % 360.0))))


def regrid(values, lats, lons):
    """Bilinear-interpolate a regular lat/lon field to the 2.5 deg target grid.

    values: 2-D array shaped (len(lats), len(lons)); lats/lons in degrees, any order,
    lons may be -180..180 or 0..360.
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float) % 360.0
    v = np.asarray(values, dtype=float)
    # sort latitude ascending
    lo = np.argsort(lats)
    lats, v = lats[lo], v[lo, :]
    # sort longitude ascending (after wrapping) and add periodic column
    oo = np.argsort(lons)
    lons, v = lons[oo], v[:, oo]
    lons = np.concatenate([lons, [lons[0] + 360.0]])
    v = np.concatenate([v, v[:, :1]], axis=1)
    f = RegularGridInterpolator((lats, lons), v, bounds_error=False, fill_value=None)
    tl, tn = np.meshgrid(LAT, LON, indexing="ij")
    tn = np.where(tn < lons[0], tn + 360.0, tn)
    return f(np.stack([tl.ravel(), tn.ravel()], axis=-1)).reshape(NLAT, NLON)
