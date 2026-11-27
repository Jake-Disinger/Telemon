# Teleconnection Monitor

A self-hosted page for NAO, AO, PNA, EPO, AAM and MJO forecasts from several models on one chart. Every model run is saved as its own file, so you can step back through earlier runs.

```
telemon/
├── web/                     ← serve this folder (static files only, no external libraries)
│   ├── index.html
│   ├── js/config.js         ← site label, model colors/symbols, outlook image URLs
│   ├── js/charts.js         ← SVG chart renderer (multi-model, box-whisker, MJO phase)
│   ├── js/app.js
│   └── data/                ← written by the pipeline (currently SYNTHETIC demo data)
└── pipeline/
    ├── config.json          ← models, cycles, forecast steps, download URL templates
    ├── build_climatology.py ← run once: 1991–2020 climatology, EOF patterns, RMM EOFs
    ├── backfill_analysis.py ← run once: seeds the observed line + MJO 120-day history
    ├── run_ingest.py        ← run from cron: finds new model runs and processes them
    ├── make_demo_data.py    ← writes the synthetic demo data
    ├── tele/                ← library code (index math, GRIB I/O, sources, storage)
    └── tests/               ← python -m pytest tests -q
```

## Page features

- **Tabs:** Overview (all six indices on one screen), NAO, AO, PNA, EPO, AAM, MJO, and CPC Outlooks.
- **All Models view:** one chart with ECMWF HRES, EPS mean, AIFS, GFS, GEFS mean and GEPS mean, with the observed index as the dark gray line. Legend entries for models without data are greyed out.
- **Single Model view:**
  - Deterministic models get a line chart.
  - Ensembles get the ECMWF-style box-and-whisker chart: 25–75% box, 5–95% whiskers, green ensemble mean. **Show members** adds the spaghetti lines.
- **Run Trend view:** overlays the last N runs of one model. Older runs fade, so changes from run to run are easy to see.
- **Run history:** the ◀ ▶ buttons (or the ← → keys) step through runs, and the dropdown lists every saved run. **Latest** follows new runs automatically. The page checks for new data every 5 minutes, so it can run unattended on a wall display.
- **MJO tab:** a Wheeler–Hendon RMM phase diagram with the last 40 days observed, large markers every 5 days of lead time, and member tracks for ensembles. An amplitude chart sits beside it.
- **Hover tooltips:** show every model's value at a given time, ensemble 5–95% ranges, and MJO phase and amplitude.
- **Save PNG:** exports the chart at 2× resolution for briefings.
- **Shareable URLs:** the URL hash keeps the current state, e.g. `#tab=pna&view=model&model=eps&run=2026112300`.

## Rule-based and AAM tools

- **GWO tab:** the Weickmann–Berry Global Wind Oscillation.
  - x is the global relative AAM anomaly and y its tendency, both standardized, after a 5-day running mean. The tendency uses a 5-point, 4th-order difference. Orbits run clockwise.
  - Forecast tracks continue the observed AAM series with each run's daily-mean AAM.
  - EPS has no AAM unless `"aam": true` is set for it in `pipeline/config.json`.
- **Bering Sea Rule tab:**
  - **Model maps:** daily North Pacific maps (sea-level pressure with H/L centers, or 500 mb heights and anomalies) from the GFS analysis (45 days) and every model run (10 days). The US outline sits where the rule maps it, and each map is labeled with the projected date (valid time + lag; the lag is selectable, default 18 days).
  - **OPC charts:** OPC's Pacific surface charts with the same overlay. Each chart needs a one-time two-click calibration; paste the result into `bsr.opc[].cal` in `web/js/config.js` to share it.
  - **Adjust overlay:** moves or resizes the US outline; paste the settings into `bsr.overlay` in `web/js/config.js` to share them.
- **Typhoon Rule tab:** West Pacific tracks from NOAA IBTrACS, refreshed every 6 hours.
  - Recurvature is the westernmost point of a track that then moves at least 4° east and 3° north.
  - Storms that recurve near Japan (the shaded box) get an implied eastern-US trough window 6–10 days later. Typhoon-strength storms (≥64 kt) are highlighted.
  - IBTrACS updates about three times a week, so the newest positions can lag real time.

Both rules are forecaster heuristics and are labeled that way on the page.

## Setup

**No Python on your computer? Use GitHub (recommended):** see `GITHUB_SETUP.md`. GitHub Actions runs the pipeline on a schedule and GitHub Pages hosts the page, all set up from a browser.

**On your own Linux/Mac/Windows machine with Python:**

```bash
cd telemon/pipeline
python3 -m pip install -r requirements.txt
python3 -m pytest tests -q                 # optional sanity check (no network needed)
python3 build_climatology.py               # once; ~30–60 min, ~1 GB over OPeNDAP from NOAA PSL
python3 backfill_analysis.py --days 150    # once; observed line + MJO history
python3 run_ingest.py -v --model gfs       # first real run (overwrites the demo files)
crontab -e                                 # add the line from crontab.example
```

Serve `web/` with Apache, nginx or IIS. It can also live alongside your other displays. For a quick local look, run `cd web && python3 -m http.server 8000`. Opening `index.html` directly from disk will not load the data; browsers block that.

Before going live, delete the synthetic files with `rm -rf web/data/runs web/data/*.json`. While demo data is loaded, the page shows a red **DEMO DATA** banner.

## How the indices are computed

Each model run is interpolated to a 2.5° grid. Anomalies are taken against a 1991–2020 NCEP/NCAR Reanalysis-1 daily climatology, smoothed to 3 annual harmonics.

| Index | Definition |
|---|---|
| **AO** | Daily 1000 hPa anomalies, 20–90N, projected on the leading EOF of monthly anomalies (CPC method). Positive means low heights over the pole. |
| **NAO** | CPC method: the NAO mode of a varimax-rotated PCA of standardized monthly 500 hPa anomalies, 20–90N, 1991–2020, with a separate pattern for each calendar month (3-month windows). Daily values are projections onto that month's pattern, blended between neighbouring months. |
| **PNA** | CPC method: the PNA mode of the same rotated PCA. |
| **EPO** | Z500 anomaly over 20–35N,160–125W minus 55–65N,160–125W. A ridge over Alaska gives a negative EPO. |
| **AAM** | Global relative angular momentum, (2πa³/g)∬[u]cos²φ dφ dp, over 850–50 hPa, shown as a standardized anomaly. The tooltip gives the raw anomaly ×10²⁴ kg m² s⁻¹. |
| **MJO** | Wheeler & Hendon (2004) RMM. Inputs are 15S–15N OLR, u850 and u200 anomalies, with the prior 120-day mean removed. Days after the init time use the forecast itself, as in Gottschalck et al. 2010. The EOFs are computed from 1991–2020 data, with sign conventions matching BoM/CPC. |

AO, EPO and AAM are divided by the standard deviation of the 1991–2020 monthly-mean index. NAO and PNA are scaled by the standard deviation of their monthly index for that calendar month. Both are CPC's convention, so daily values sit on the familiar ±3 scale. Setup's last step downloads CPC's official daily NAO, AO and PNA and logs how closely the site's observed values agree (`data/verification.json`).

The black **observed** line comes from GFS f000 analyses, set by `analysis_model` in `config.json`. Its history is seeded from Reanalysis-1 by `backfill_analysis.py`.

## Models and data sources (pipeline/config.json)

| Key | Source | Default cycles / steps | Notes |
|---|---|---|---|
| gfs | NOAA AWS (`noaa-gfs-bdp-pds`), 1.0° | 00/06/12/18, 12 h to 384 h | also provides the observed line |
| gefs | NOAA AWS (`noaa-gefs-pds`), 0.5°, 31 members | 00/12, 12 h to 384 h | |
| hres | ECMWF open data, 0.25° | 00/12, 12 h to 240 h | |
| eps | ECMWF open data, 0.25°, 51 members | 00/12, 24 h to 360 h | `"aam": false` by default (bandwidth) |
| aifs | ECMWF open data (`aifs-single`), 0.25° | 00/12, 12 h to 360 h | |
| geps | MSC Datamart, 21 members | 00/12, 24 h to 384 h | no OLR, so the MJO is wind-only (flagged on the page) |

Downloads use HTTP byte ranges from the `.idx` / `.index` files, so only the needed GRIB messages come down. Rough sizes per run: GFS ~50 MB, HRES/AIFS ~300 MB, GEFS ~3–4 GB, EPS ~3–5 GB.

Each model has three knobs for bandwidth: `cycles`, `step_hours` and `"aam": false`. Set `"enabled": false` to turn a model off. You can switch the NOAA URLs to NOMADS, but NOMADS throttles heavy users, so AWS is the default.

**Adding a model** means two edits: an entry in `pipeline/config.json` (provider `ncep`, `ecmwf` or `msc`) and a matching entry in `web/js/config.js` (label, color, symbol).

## Things to verify on first run

The index math is covered by the tests. The download code was written without network access, so check these against the live servers:

1. **GEPS URL.** MSC reorganized the Datamart (dated directories and new file names). If GEPS 404s, update the `geps.url` template.
2. **ECMWF `ttr`.** If `ttr` (top thermal radiation, used for OLR) isn't in the open-data index for HRES/ENS/AIFS, that model's MJO falls back to wind-only and the page labels it.
3. **PSL OPeNDAP paths** in `tele/reanalysis.py` (`URLS`). They point at `psl.noaa.gov/thredds/dodsC/Datasets/...`. If PSL has moved a file, adjust them there.
4. **Plausibility.** Compare the first few days of GFS AO/NAO/PNA with CPC's daily values. They won't match exactly, because CPC uses rotated EOFs for NAO and PNA, but they should track closely.

## Data format (for other tools)

- `web/data/manifest.json`: `{"updated": "...", "models": {"gfs": {"runs": ["2026112300", ...]}}}`
- `web/data/runs/<model>/<YYYYMMDDHH>.json`: `steps` (forecast hours) and `indices.<name>`:
  - deterministic models: `{"value": [...]}`
  - ensembles: `{"mean": [...], "members": [[...], ...]}`
  - MJO: `rmm1`/`rmm2` (plus `members_rmm1`/`members_rmm2` and `wind_only`)
- `web/data/analysis.json`: observed history, with `times` plus one array per index.
- Runs older than `retention_days` (default 60) are pruned automatically.
