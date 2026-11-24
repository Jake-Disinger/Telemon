#!/usr/bin/env python3
"""Ingest model runs and write index forecasts for the web page.

  python run_ingest.py                      # auto: every enabled model, any new run in the last 36 h
  python run_ingest.py --model gfs          # auto, one model
  python run_ingest.py --model eps --run 2026112300   # one specific run (re-processes if it exists)

Run it from cron every 30-60 minutes; runs already in the manifest are skipped.
"""
import argparse
import datetime as dt
import fcntl
import json
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from tele.climo import Climatology          # noqa: E402
from tele.sources import make_source, latest_cycles   # noqa: E402
from tele.store import Store               # noqa: E402
from tele import pipeline                  # noqa: E402
from tele import typhoons                  # noqa: E402
from tele.maps import MapAccumulator       # noqa: E402

log = logging.getLogger("tele")


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    for k in ("data_dir", "state_dir", "climatology"):
        cfg[k] = os.path.normpath(os.path.join(base, cfg[k]))
    # environment overrides (used by the GitHub Actions workflows)
    for k, env in (("data_dir", "TELE_DATA_DIR"), ("state_dir", "TELE_STATE_DIR"), ("climatology", "TELE_CLIMATOLOGY")):
        if os.environ.get(env):
            cfg[k] = os.environ[env]
    return cfg


def process(cfg, clim, store, key, run):
    mcfg = cfg["models"][key]
    u_levels = set([850, 200]) | (set(clim.aam_levels) if mcfg.get("aam", True) else set())
    src = make_source(key, mcfg, u_levels)
    log.info("=== %s %s (%d steps)", key, run.strftime("%Y%m%d%H"), len(src.steps))
    maps = MapAccumulator() if cfg.get("maps", {}).get("enabled", True) else None
    steps, members = pipeline.collect(src, run, clim, maps=maps,
                                      map_max_hours=cfg.get("maps", {}).get("max_hours", 360))
    if not members:
        log.error("%s %s: nothing downloaded", key, run)
        return False
    if key == cfg["analysis_model"]:
        pipeline.analysis_update(clim, store, run, members, steps)
        if maps is not None and run.hour == 0 and 0 in maps.sums:
            store.write_map("analysis", run, maps.payload("analysis", run.strftime("%Y%m%d%H"), [0]))
    payload = pipeline.build_payload(src, run, clim, steps, members, store.mjo_daily())
    store.write_run(key, run, payload)
    if maps is not None and maps.sums:
        store.write_map(key, run, maps.payload(key, run.strftime("%Y%m%d%H")))
    log.info("wrote %s %s", key, run.strftime("%Y%m%d%H"))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--model", default="all")
    ap.add_argument("--run", help="YYYYMMDDHH (default: auto-detect new runs)")
    ap.add_argument("--lookback", type=int, default=36, help="hours to look back in auto mode")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(a.config)
    os.makedirs(cfg["state_dir"], exist_ok=True)

    # one ingest at a time (cron overlap protection)
    lock = open(os.path.join(cfg["state_dir"], "ingest.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info("another ingest is running; exiting")
        return

    clim = Climatology(cfg["climatology"], os.path.join(cfg["state_dir"], "calibration.json"))
    mc = cfg.get("maps", {})
    store = Store(cfg["data_dir"], cfg["state_dir"], cfg.get("retention_days", 60),
                  map_days=mc.get("retention_days", 10), analysis_map_days=mc.get("analysis_days", 45))
    keys = [k for k, m in cfg["models"].items() if m.get("enabled", True)] if a.model == "all" else [a.model]
    # analysis model first so the 'observed' history is current for the others
    keys.sort(key=lambda k: k != cfg["analysis_model"])

    for key in keys:
        mcfg = cfg["models"][key]
        if a.run:
            process(cfg, clim, store, key, dt.datetime.strptime(a.run, "%Y%m%d%H"))
            continue
        src = make_source(key, mcfg, [850, 200])
        for run in latest_cycles(src, lookback_hours=a.lookback):
            if store.has_run(key, run):
                continue
            if not src.is_available(run):
                log.debug("%s %s not complete yet", key, run)
                continue
            try:
                process(cfg, clim, store, key, run)
            except Exception:
                log.exception("%s %s failed", key, run)

    tcfg = cfg.get("typhoons", {})
    if tcfg.get("enabled", True):
        try:
            typhoons.update(cfg["data_dir"], tcfg)
        except Exception:
            log.exception("typhoon update failed")


if __name__ == "__main__":
    main()
