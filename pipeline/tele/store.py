"""Read/write the JSON files the web page consumes.

web/data/manifest.json             list of runs available for each model
web/data/runs/<model>/<YYYYMMDDHH>.json   one file per model run
web/data/analysis.json             'observed' index history (black line on charts)
<state_dir>/mjo_history.json       equatorial anomaly profiles (for the RMM 120-day mean)
"""
import datetime as dt
import json
import os

import numpy as np

TFMT = "%Y%m%d%H"


def _round(x, nd=3):
    if x is None:
        return None
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_round(v, nd) for v in x]
    x = float(x)
    return None if not np.isfinite(x) else round(x, nd)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)                    # atomic so the page never reads half a file


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class Store:
    def __init__(self, data_dir, state_dir, retention_days=60, analysis_days=180,
                 map_days=10, analysis_map_days=45):
        self.data_dir = data_dir
        self.state_dir = state_dir
        self.retention_days = retention_days
        self.analysis_days = analysis_days
        self.map_days = map_days
        self.analysis_map_days = analysis_map_days

    # ---- manifest / runs --------------------------------------------------------
    @property
    def manifest_path(self):
        return os.path.join(self.data_dir, "manifest.json")

    def manifest(self):
        return _read_json(self.manifest_path, {"updated": None, "models": {}})

    def has_run(self, model, run):
        return run.strftime(TFMT) in self.manifest()["models"].get(model, {}).get("runs", [])

    def write_run(self, model, run, payload):
        rid = run.strftime(TFMT)
        _write_json(os.path.join(self.data_dir, "runs", model, rid + ".json"), _round_payload(payload))
        man = self.manifest()
        entry = man["models"].setdefault(model, {"runs": []})
        if rid not in entry["runs"]:
            entry["runs"].append(rid)
        entry["runs"].sort(reverse=True)
        cutoff = (run - dt.timedelta(days=self.retention_days)).strftime(TFMT)
        for old in [r for r in entry["runs"] if r < cutoff]:
            entry["runs"].remove(old)
            try:
                os.remove(os.path.join(self.data_dir, "runs", model, old + ".json"))
            except FileNotFoundError:
                pass
        man["updated"] = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ")
        _write_json(self.manifest_path, man)

    # ---- North Pacific maps (Bering Sea Rule) -------------------------------------
    def write_map(self, model, when, payload):
        """model is a model key or "analysis"; files live in data/maps/<model>/<YYYYMMDDHH>.json"""
        rid = when.strftime(TFMT)
        _write_json(os.path.join(self.data_dir, "maps", model, rid + ".json"), payload)
        man = self.manifest()
        lst = man.setdefault("maps", {}).setdefault(model, [])
        if rid not in lst:
            lst.append(rid)
        lst.sort(reverse=True)
        keep = self.analysis_map_days if model == "analysis" else self.map_days
        newest = dt.datetime.strptime(lst[0], TFMT)
        cutoff = (newest - dt.timedelta(days=keep)).strftime(TFMT)
        for old in [r for r in lst if r < cutoff]:
            lst.remove(old)
            try:
                os.remove(os.path.join(self.data_dir, "maps", model, old + ".json"))
            except FileNotFoundError:
                pass
        _write_json(self.manifest_path, man)

    # ---- analysis (observed) ------------------------------------------------------
    @property
    def analysis_path(self):
        return os.path.join(self.data_dir, "analysis.json")

    def update_analysis(self, when, values):
        """values: dict name -> float (nao, ao, pna, epo, aam, rmm1, rmm2)."""
        a = _read_json(self.analysis_path, {"times": []})
        rows = {t: {k: a[k][i] for k in a if k not in ("times", "updated") and i < len(a[k])}
                for i, t in enumerate(a["times"])}
        key = when.strftime(TFMT)
        rows.setdefault(key, {}).update({k: _round(v) for k, v in values.items() if v is not None})
        cutoff = (when - dt.timedelta(days=self.analysis_days)).strftime(TFMT)
        times = sorted(t for t in rows if t >= cutoff)
        names = sorted({k for t in times for k in rows[t]})
        out = {"updated": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%MZ"), "times": times}
        for n in names:
            out[n] = [rows[t].get(n) for t in times]
        _write_json(self.analysis_path, out)

    # ---- MJO equatorial history ---------------------------------------------------
    @property
    def mjo_path(self):
        return os.path.join(self.state_dir, "mjo_history.json")

    def mjo_history(self):
        return _read_json(self.mjo_path, {})

    def add_mjo_history(self, when, profiles):
        h = self.mjo_history()
        h[when.strftime(TFMT)] = {k: _round(v, 2) for k, v in profiles.items() if v is not None}
        cutoff = (when - dt.timedelta(days=200)).strftime(TFMT)
        h = {k: v for k, v in sorted(h.items()) if k >= cutoff}
        _write_json(self.mjo_path, h)

    def mjo_daily(self):
        """date -> {var: mean profile (np.array)} from the stored analyses."""
        acc = {}
        for k, prof in self.mjo_history().items():
            d = dt.datetime.strptime(k, TFMT).date()
            for var, p in prof.items():
                acc.setdefault(d, {}).setdefault(var, []).append(np.asarray(p, float))
        return {d: {v: np.mean(ps, axis=0) for v, ps in vs.items()} for d, vs in acc.items()}


def _round_payload(p):
    out = {}
    for k, v in p.items():
        if isinstance(v, dict):
            out[k] = _round_payload(v)
        elif isinstance(v, (list, np.ndarray)) and len(v) and isinstance(v[0], (list, np.ndarray)):
            out[k] = [_round(m, 2) for m in v]          # ensemble members: 2 decimals
        elif isinstance(v, (list, np.ndarray)) and k not in ("steps",):
            out[k] = _round(v)
        else:
            out[k] = v
    return out
