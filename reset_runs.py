#!/usr/bin/env python3
"""Remove stored forecast runs (keeps observed history, maps and typhoons) so the next
ingest recomputes them with the current climatology. Used by Setup after a rebuild."""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_ingest import load_config            # noqa: E402

cfg = load_config(os.path.join(HERE, "config.json"))
d = cfg["data_dir"]
shutil.rmtree(os.path.join(d, "runs"), ignore_errors=True)
mp = os.path.join(d, "manifest.json")
if os.path.exists(mp):
    with open(mp) as f:
        man = json.load(f)
    man["models"] = {}
    with open(mp, "w") as f:
        json.dump(man, f)
cp = os.path.join(cfg["state_dir"], "calibration.json")
if os.path.exists(cp):
    with open(cp) as f:
        cal = json.load(f)
    cal.pop("index_offsets", None)                    # re-measured against CPC after the backfill
    with open(cp, "w") as f:
        json.dump(cal, f, indent=1)
print("forecast runs cleared; the next ingest will recompute the last 36 hours")
