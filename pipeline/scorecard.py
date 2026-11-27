#!/usr/bin/env python3
"""Forecast scorecard: compare every stored forecast run with the observed (analysis) index
at its valid time, by model, index and lead day. Writes <data_dir>/scorecard.json for the
Scorecard tab. Runs are kept for 60 days, so the scores cover roughly the last two months.

Scores per model / index / lead day (lead day L covers lead times 24L-12 .. 24L+11 h):
  n     number of forecast-observation pairs
  bias  mean(forecast - observed)  -> a steady bias shows up as a curve away from zero
  mae   mean |forecast - observed|
  corr  correlation between forecasts and observations
Persistence (observed value at the start time kept unchanged) is scored the same way, over
the same verifying dates, as a no-skill reference. Ensemble runs are scored by their mean.

  python scorecard.py            (run by the Ingest workflow after each ingest)
"""
import datetime as dt
import glob
import json
import logging
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

log = logging.getLogger("tele")
INDICES = ["nao", "ao", "pna", "epo", "aam"]
MAX_LEAD = 16
TFMT = "%Y%m%d%H"


def lead_day(hours):
    return int((hours + 12) // 24)


def _stats(pairs):
    if not pairs:
        return None
    f, o = np.array(pairs, float).T
    e = f - o
    corr = float(np.corrcoef(f, o)[0, 1]) if len(f) >= 5 and f.std() > 0 and o.std() > 0 else None
    return {"n": int(len(e)), "bias": round(float(e.mean()), 3), "mae": round(float(np.abs(e).mean()), 3),
            "corr": None if corr is None else round(corr, 3)}


def build(data_dir):
    with open(os.path.join(data_dir, "analysis.json")) as f:
        an = json.load(f)
    obs = {k: {t: v for t, v in zip(an["times"], an.get(k, [])) if v is not None} for k in INDICES}
    pairs = {}                      # (model, index, lead) -> [(f, o)]
    first, last, nruns = None, None, 0
    for path in sorted(glob.glob(os.path.join(data_dir, "runs", "*", "*.json"))):
        model = os.path.basename(os.path.dirname(path))
        try:
            with open(path) as f:
                run = json.load(f)
            t0 = dt.datetime.strptime(run["run"], TFMT)
        except (OSError, ValueError, KeyError):
            continue
        used = False
        for k in INDICES:
            blk = run.get("indices", {}).get(k)
            series = blk and (blk.get("value") or blk.get("mean"))
            if not series:
                continue
            for h, v in zip(run["steps"], series):
                L = lead_day(h)
                if v is None or L < 1 or L > MAX_LEAD:
                    continue
                vt = (t0 + dt.timedelta(hours=h)).strftime(TFMT)
                o = obs[k].get(vt)
                if o is None:
                    continue
                pairs.setdefault((model, k, L), []).append((v, o))
                used = True
                first = min(first or vt, vt); last = max(last or vt, vt)
        nruns += used
    # persistence reference from the observed series (00Z and 12Z starts)
    pers = {}
    for k in INDICES:
        ser = {dt.datetime.strptime(t, TFMT): v for t, v in obs[k].items()}
        for t0, v0 in ser.items():
            if t0.hour not in (0, 12):
                continue
            for L in range(1, MAX_LEAD + 1):
                tv = t0 + dt.timedelta(days=L)
                v = ser.get(tv)
                if v is not None and first and first <= tv.strftime(TFMT) <= last:
                    pers.setdefault((k, L), []).append((v0, v))
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "first": first, "last": last, "runs": nruns, "max_lead": MAX_LEAD, "models": {}, "persistence": {},
           "obs_sd": {k: (round(float(np.std(list(obs[k].values()))), 3) if obs[k] else None) for k in INDICES}}
    for (model, k, L), p in pairs.items():
        out["models"].setdefault(model, {}).setdefault(k, {})[str(L)] = _stats(p)
    for (k, L), p in pers.items():
        out["persistence"].setdefault(k, {})[str(L)] = _stats(p)
    path = os.path.join(data_dir, "scorecard.json")
    try:
        with open(path) as f:
            prev = json.load(f)
        prev.pop("updated", None)
    except (OSError, ValueError):
        prev = None
    if prev == {k: v for k, v in json.loads(json.dumps(out)).items() if k != "updated"}:
        log.info("scorecard unchanged")
        return out
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    log.info("scorecard: %d runs verified, %d model/index/lead cells, valid times %s .. %s",
             nruns, len(pairs), first, last)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    from run_ingest import load_config
    cfg = load_config(os.path.join(HERE, "config.json"))
    build(cfg["data_dir"])


if __name__ == "__main__":
    main()
