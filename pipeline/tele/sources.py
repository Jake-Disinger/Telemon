"""Model data sources. Every source returns, for one forecast step, a dict
member -> {"z500": 2-D, "z1000": 2-D, "u": {level: 2-D}, "olr": 2-D or None,
"ttr": 2-D or None} on the 2.5 deg grid. URL templates live in config.json so they
can be changed without touching code when a provider reorganizes its server."""
import datetime as dt
import logging

from . import gribio

log = logging.getLogger("tele")


def fmt(template, run, step=0, **kw):
    return template.format(
        ymd=run.strftime("%Y%m%d"), hh=run.strftime("%H"), ymdh=run.strftime("%Y%m%d%H"),
        step=step, fff=f"{step:03d}", **kw)


class Source:
    def __init__(self, key, cfg, u_levels):
        self.key = key
        self.cfg = cfg
        self.kind = cfg["kind"]                       # "det" or "ens"
        self.u_levels = sorted(set(u_levels))
        self.steps = list(range(0, cfg["max_hours"] + 1, cfg["step_hours"]))

    def cycles(self):
        return self.cfg["cycles"]

    def is_available(self, run):
        """True when the last forecast step is on the server."""
        return gribio.url_exists(self.probe_url(run))

    def empty(self):
        return {"z500": None, "z1000": None, "u": {}, "olr": None, "ttr": None}


# ---- NCEP (GFS / GEFS) -------------------------------------------------------
class NCEPSource(Source):
    def wanted(self):
        keys = {"HGT:500 mb": ("z500", None), "HGT:1000 mb": ("z1000", None),
                "ULWRF:top of atmosphere": ("olr", None)}
        for l in self.u_levels:
            keys[f"UGRD:{l} mb"] = ("u", l)
        return keys

    def members(self):
        return self.cfg.get("members", ["main"])

    def url(self, run, step, member):
        return fmt(self.cfg["url"], run, step, member=member)

    def probe_url(self, run):
        return self.url(run, self.steps[-1], self.members()[-1]) + ".idx"

    def fetch_step(self, run, step):
        out = {}
        wanted = self.wanted()
        for mi, mem in enumerate(self.members()):
            url = self.url(run, step, mem)
            idx = gribio.http_get(url + ".idx")
            if idx is None:
                log.warning("%s missing %s", self.key, url)
                continue
            recs, seen = [], set()
            for r in gribio.ncep_idx(idx.decode()):
                if r["key"] in wanted and r["key"] not in seen:
                    seen.add(r["key"])
                    recs.append(r)
            blobs = gribio.fetch_ranges(url, recs)
            d = self.empty()
            for r, b in zip(recs, blobs):
                if not b:
                    continue
                for _meta, fld in gribio.decode_bytes(b):
                    name, lev = wanted[r["key"]]
                    if name == "u":
                        d["u"][lev] = fld
                    else:
                        d[name] = fld
            out[mi] = d
        return out


# ---- ECMWF open data (HRES, ENS, AIFS) ---------------------------------------
class ECMWFSource(Source):
    def wanted(self):
        keys = {"gh:500": ("z500", None), "gh:1000": ("z1000", None), "ttr": ("ttr", None)}
        for l in self.u_levels:
            keys[f"u:{l}"] = ("u", l)
        return keys

    def url(self, run, step):
        return fmt(self.cfg["url"], run, step)

    def probe_url(self, run):
        return self.url(run, self.steps[-1]).replace(".grib2", ".index")

    def fetch_step(self, run, step):
        url = self.url(run, step)
        idx = gribio.http_get(url.replace(".grib2", ".index"))
        if idx is None:
            log.warning("%s missing %s", self.key, url)
            return {}
        wanted = self.wanted()
        recs = [r for r in gribio.ecmwf_index(idx.decode()) if r["key"] in wanted]
        blobs = gribio.fetch_ranges(url, recs, workers=self.cfg.get("workers", 8))
        out = {}
        for r, b in zip(recs, blobs):
            if not b:
                continue
            d = out.setdefault(r["member"], self.empty())
            for _meta, fld in gribio.decode_bytes(b):
                name, lev = wanted[r["key"]]
                if name == "u":
                    d["u"][lev] = fld
                else:
                    d[name] = fld
        return out


# ---- MSC Datamart (GEPS) -----------------------------------------------------
class MSCSource(Source):
    def files(self):
        f = {("z500", None): ("HGT", "ISBL_0500"), ("z1000", None): ("HGT", "ISBL_1000")}
        for l in self.u_levels:
            f[("u", l)] = ("UGRD", f"ISBL_{l:04d}")
        return f

    def url(self, run, step, var, lev):
        return fmt(self.cfg["url"], run, step, var=var, lev=lev)

    def probe_url(self, run):
        return self.url(run, self.steps[-1], "HGT", "ISBL_0500")

    def fetch_step(self, run, step):
        out = {}
        for (name, lev), (var, levs) in self.files().items():
            blob = gribio.http_get(self.url(run, step, var, levs))
            if blob is None:
                log.warning("%s missing %s %s f%03d", self.key, var, levs, step)
                continue
            for meta, fld in gribio.decode_bytes(blob):
                d = out.setdefault(meta["member"], self.empty())
                if name == "u":
                    d["u"][lev] = fld
                else:
                    d[name] = fld
        return out


TYPES = {"ncep": NCEPSource, "ecmwf": ECMWFSource, "msc": MSCSource}


def make_source(key, cfg, u_levels):
    return TYPES[cfg["provider"]](key, cfg, u_levels)


def latest_cycles(source, now=None, lookback_hours=36):
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    base = now.replace(minute=0, second=0, microsecond=0)
    runs = []
    for h in range(lookback_hours, -1, -1):
        t = base - dt.timedelta(hours=h)
        if t.hour in source.cycles():
            runs.append(t)
    return runs
