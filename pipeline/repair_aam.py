#!/usr/bin/env python3
"""Correct stored AAM values after the AAM calibration offset changed.

calibrate_aam.py records the offset it replaced as "aam_offset_replaced". Values computed
with that old offset are off by delta = (old - new) / sigma. The observed history at 00Z
and 12Z has just been re-seeded by backfill_analysis.py with the new offset, so it serves as
the reference: any other stored value (06Z/18Z analyses, every forecast run) whose day-0
AAM sits about `delta` away from the reference was made with the old offset and is shifted.
Values that already agree are left alone. Changes smaller than 0.5 sigma are not repaired.

  python repair_aam.py            (run by the Setup workflow after the backfill)
"""
import datetime as dt
import glob
import json
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from run_ingest import load_config          # noqa: E402
from tele.climo import Climatology          # noqa: E402

log = logging.getLogger("tele")
MIN_DELTA = 0.5


def _t(s):
    return dt.datetime.strptime(s, "%Y%m%d%H")


def reference(times, aam):
    """00Z/12Z analysis values (re-seeded with the new offset) -> lookup(datetime) giving
    the value at that time, interpolated between neighbours up to 12 h apart."""
    pts = sorted((_t(t), v) for t, v in zip(times, aam) if v is not None and t[8:] in ("00", "12"))

    def at(when):
        for i, (t, v) in enumerate(pts):
            if t == when:
                return v
            if t > when:
                if i == 0:
                    return None
                t0, v0 = pts[i - 1]
                if (t - t0).total_seconds() > 13 * 3600:
                    return None
                f = (when - t0).total_seconds() / (t - t0).total_seconds()
                return v0 + f * (v - v0)
        if pts and 0 <= (when - pts[-1][0]).total_seconds() <= 12 * 3600:
            return pts[-1][1]
        return None
    return at


def needs_shift(value, ref, delta):
    """True if `value` looks like it was made with the old offset."""
    return value is not None and ref is not None and abs((value + delta) - ref) < abs(value - ref) \
        and abs(value + delta - ref) < abs(delta) / 2


def shift_series(block, delta, sd):
    for k in ("value", "mean"):
        if isinstance(block.get(k), list):
            block[k] = [None if v is None else round(v + delta, 3) for v in block[k]]
    if isinstance(block.get("members"), list):
        block["members"] = [[None if v is None else round(v + delta, 2) for v in m] for m in block["members"]]
    if isinstance(block.get("raw"), list):                       # anomaly in 1e24 kg m2/s
        block["raw"] = [None if v is None else round(v + delta * sd / 1e24, 3) for v in block["raw"]]


def repair(data_dir, delta, sd):
    path = os.path.join(data_dir, "analysis.json")
    with open(path) as f:
        an = json.load(f)
    at = reference(an["times"], an["aam"])
    fixed_an = 0
    for i, t in enumerate(an["times"]):
        if t[8:] in ("00", "12"):
            continue
        v = an["aam"][i]
        if needs_shift(v, at(_t(t)), delta):
            an["aam"][i] = round(v + delta, 3); fixed_an += 1
    with open(path, "w") as f:
        json.dump(an, f, separators=(",", ":"))
    fixed_runs, ok_runs, unknown = [], 0, 0
    for p in sorted(glob.glob(os.path.join(data_dir, "runs", "*", "*.json"))):
        with open(p) as f:
            run = json.load(f)
        blk = run.get("indices", {}).get("aam")
        if not blk:
            continue
        first = (blk.get("value") or blk.get("mean") or [None])[0]
        ref = at(_t(run["run"]))
        if needs_shift(first, ref, delta):
            shift_series(blk, delta, sd)
            with open(p, "w") as f:
                json.dump(run, f, separators=(",", ":"))
            fixed_runs.append(os.path.relpath(p, data_dir))
        elif ref is None:
            unknown += 1
        else:
            ok_runs += 1
    log.info("AAM repair (%+.2f sigma): %d analysis times and %d forecast runs corrected, %d runs already right, "
             "%d runs without a reference (left alone)", delta, fixed_an, len(fixed_runs), ok_runs, unknown)
    for p in fixed_runs:
        log.info("  corrected %s", p)
    return fixed_an, fixed_runs


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config(os.path.join(HERE, "config.json"))
    cpath = os.path.join(cfg["state_dir"], "calibration.json")
    if not os.path.exists(cpath):
        log.info("no calibration file; nothing to repair"); return
    with open(cpath) as f:
        cal = json.load(f)
    old = cal.pop("aam_offset_replaced", None)
    if old is not None:
        sd = Climatology(cfg["climatology"]).idx_sd["aam"]
        delta = (old - cal["aam_offset"]) / sd
        if abs(delta) >= MIN_DELTA:
            repair(cfg["data_dir"], delta, sd)
        else:
            log.info("AAM offset changed by only %+.2f sigma; stored values left as they are", delta)
    else:
        log.info("AAM offset unchanged; nothing to repair")
    with open(cpath, "w") as f:
        json.dump(cal, f, indent=1)


if __name__ == "__main__":
    main()
