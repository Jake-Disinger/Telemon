/* Teleconnection Monitor — page logic. Reads data/manifest.json, data/analysis.json and
   data/runs/<model>/<YYYYMMDDHH>.json written by pipeline/run_ingest.py. */
(function () {
  "use strict";
  const C = window.TELE_CONFIG, TC = window.TeleCharts, DAY = TC.DAY, MON = TC.MON;
  const EMBED = window.TELE_EMBED || null;              // single-file demo build
  const TABS = ["overview", "nao", "ao", "pna", "epo", "aam", "mjo", "outlooks"];
  const LINE_IDX = ["nao", "ao", "pna", "epo", "aam"];
  const MODEL_KEYS = Object.keys(C.models);
  const $ = s => document.querySelector(s);

  const state = { tab: "pna", view: "all", model: "eps", cycle: null, follow: true, n: 6, members: false };
  let manifest = { models: {} }, analysis = null;
  const cache = {};

  /* ---------- data ------------------------------------------------------- */
  const pad2 = n => String(n).padStart(2, "0");
  const runMs = r => Date.UTC(+r.slice(0, 4), +r.slice(4, 6) - 1, +r.slice(6, 8), +r.slice(8, 10));
  const runLabel = r => `${r.slice(8, 10)}Z ${r.slice(6, 8)}${MON[+r.slice(4, 6) - 1]}`;
  const initLabel = r => `${r.slice(8, 10)}Z${r.slice(6, 8)}${MON[+r.slice(4, 6) - 1]}${r.slice(0, 4)}`;

  async function getJSON(path, nocache) {
    if (EMBED) {
      if (path === "manifest.json") return EMBED.manifest;
      if (path === "analysis.json") return EMBED.analysis;
      const m = path.match(/runs\/(\w+)\/(\d+)\.json/);
      return m ? EMBED.runs[m[1]][m[2]] : null;
    }
    const r = await fetch(C.dataPath + path, nocache ? { cache: "no-store" } : {});
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  }
  async function loadRun(model, run) {
    const k = model + "/" + run;
    if (!(k in cache)) cache[k] = getJSON(`runs/${model}/${run}.json`).catch(() => null);
    return cache[k];
  }
  const runsOf = m => (manifest.models[m] && manifest.models[m].runs) || [];
  function allCycles() {
    const s = new Set();
    MODEL_KEYS.forEach(m => runsOf(m).forEach(r => s.add(r)));
    return Array.from(s).sort().reverse();
  }
  function runAtOrBefore(model, cycle, maxH) {
    const lim = runMs(cycle) - (maxH === undefined ? Infinity : maxH * 3600e3);
    return runsOf(model).find(r => r <= cycle && runMs(r) >= lim) || null;
  }
  const times = j => j.steps.map(s => runMs(j.run) + s * 3600e3);

  function pct(sorted, p) {
    if (!sorted.length) return null;
    const i = (sorted.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  }
  function ensStats(members, i) {
    const v = members.map(m => m[i]).filter(x => x !== null && x !== undefined).sort((a, b) => a - b);
    if (!v.length) return null;
    return { p05: pct(v, .05), p25: pct(v, .25), p50: pct(v, .5), p75: pct(v, .75), p95: pct(v, .95),
      mean: v.reduce((a, b) => a + b, 0) / v.length, n: v.length, pos: v.filter(x => x > 0).length };
  }
  function centralSeries(j, idx) {
    const d = j && j.indices[idx];
    if (!d) return null;
    const vals = d.value || d.mean;
    const ts = times(j);
    return ts.map((t, i) => {
      const p = { t, v: vals[i] };
      if (idx === "aam" && d.raw && d.raw[i] !== null && d.raw[i] !== undefined) p.extra = `${d.raw[i] >= 0 ? "+" : ""}${d.raw[i].toFixed(1)}e24`;
      if (d.members) { const s = ensStats(d.members, i); if (s) p.extra = `5–95%: ${s.p05.toFixed(1)} to ${s.p95.toFixed(1)}`; }
      return p;
    });
  }
  function obsSeries(idx, t0, t1) {
    if (!analysis || !analysis[idx]) return [];
    return analysis.times.map((r, i) => ({ t: runMs(r), v: analysis[idx][i] }))
      .filter(p => p.v !== null && p.t >= t0 && p.t <= t1 && new Date(p.t).getUTCHours() % 12 === 0);
  }
  const OBS = { label: "Observed (analysis)", color: "#000", symbol: "circle", filled: false, lw: 2.2, ms: 6, legend: false };

  /* ---------- UI scaffolding ---------------------------------------------- */
  function buildTabs() {
    const nav = $("#tabs");
    nav.innerHTML = "";
    TABS.forEach(t => {
      const b = document.createElement("button");
      b.textContent = t === "overview" ? "Overview" : t === "outlooks" ? "CPC Outlooks" : C.indices[t].abbr;
      b.dataset.tab = t;
      b.className = t === state.tab ? "on" : "";
      b.onclick = () => { state.tab = t; render(); };
      nav.appendChild(b);
    });
  }
  function seg(id, opts, cur, onPick) {
    const box = $(id);
    box.innerHTML = "";
    opts.forEach(([v, lab]) => {
      const b = document.createElement("button");
      b.textContent = lab; b.className = v === cur ? "on" : "";
      b.onclick = () => onPick(v);
      box.appendChild(b);
    });
  }
  function buildControls() {
    const isIdx = !["overview", "outlooks"].includes(state.tab);
    $("#controls").style.display = state.tab === "outlooks" ? "none" : "";
    $("#viewGroup").style.display = isIdx ? "" : "none";
    seg("#viewSeg", [["all", "All Models"], ["model", "Single Model"], ["trend", "Run Trend"]], state.view, v => { state.view = v; render(); });
    const showModel = isIdx && state.view !== "all";
    $("#modelGroup").style.display = showModel ? "" : "none";
    const ms = $("#modelSel");
    ms.innerHTML = MODEL_KEYS.map(k => `<option value="${k}" ${k === state.model ? "selected" : ""} ${runsOf(k).length ? "" : "disabled"}>${C.models[k].short}${C.models[k].kind === "ens" ? " (ens)" : ""}</option>`).join("");
    $("#trendGroup").style.display = isIdx && state.view === "trend" ? "" : "none";
    $("#trendN").value = String(state.n);
    const ens = C.models[state.model] && C.models[state.model].kind === "ens";
    $("#memGroup").style.display = isIdx && state.view === "model" && ens ? "" : "none";
    $("#memChk").checked = state.members;
    // run selector: every cycle (all-model) or the chosen model's runs
    const list = (isIdx && state.view !== "all") ? runsOf(state.model) : allCycles();
    const rs = $("#runSel");
    const cur = (isIdx && state.view !== "all") ? (runAtOrBefore(state.model, state.cycle) || list[0]) : state.cycle;
    rs.innerHTML = list.map(r => {
      const d = new Date(runMs(r));
      return `<option value="${r}" ${r === cur ? "selected" : ""}>${r}  (${pad2(d.getUTCHours())}Z ${["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getUTCDay()]} ${pad2(d.getUTCDate())} ${MON[d.getUTCMonth()]})</option>`;
    }).join("");
    $("#latestBtn").classList.toggle("on", state.follow);
  }
  function stepRun(dir) {
    const opts = Array.from($("#runSel").options).map(o => o.value);
    const i = opts.indexOf($("#runSel").value);
    const j = Math.min(opts.length - 1, Math.max(0, i - dir));   // list is newest first
    if (opts[j]) { state.cycle = opts[j]; state.follow = j === 0; render(); }
  }

  function writeHash() {
    const h = `tab=${state.tab}&view=${state.view}&model=${state.model}&n=${state.n}&mem=${state.members ? 1 : 0}` + (state.follow ? "" : `&run=${state.cycle}`);
    try { history.replaceState(null, "", "#" + h); } catch (e) { /* sandboxed */ }
  }
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (TABS.includes(p.get("tab"))) state.tab = p.get("tab");
    if (["all", "model", "trend"].includes(p.get("view"))) state.view = p.get("view");
    if (C.models[p.get("model")]) state.model = p.get("model");
    if (p.get("n")) state.n = Math.max(2, Math.min(12, +p.get("n")));
    state.members = p.get("mem") === "1";
    if (p.get("run")) { state.cycle = p.get("run"); state.follow = false; }
  }

  /* ---------- chart builders ---------------------------------------------- */
  function legendAll(present) {
    return MODEL_KEYS.map(k => ({ label: C.models[k].label, color: C.models[k].color, symbol: C.models[k].symbol, filled: C.models[k].filled, dim: !present[k] }));
  }
  function xRange(cycle) {
    const t = runMs(cycle);
    return [t - C.obsDaysBefore * DAY, t + C.daysAfter * DAY];
  }

  async function allModelsChart(container, idx, cycle, compact) {
    const [x0, x1] = xRange(cycle);
    const series = [], present = {}, used = [];
    const runs = await Promise.all(MODEL_KEYS.map(m => {
      const r = runAtOrBefore(m, cycle, C.sameCycleHours);
      return r ? loadRun(m, r).then(j => [m, r, j]) : Promise.resolve([m, null, null]);
    }));
    // draw order: ensembles under deterministic, like the reference graphic
    const order = ["geps", "gefs", "eps", "aifs", "gfs", "hres"].filter(k => C.models[k]).concat(MODEL_KEYS.filter(k => !["geps", "gefs", "eps", "aifs", "gfs", "hres"].includes(k)));
    const byKey = Object.fromEntries(runs.map(x => [x[0], x]));
    for (const m of order) {
      const [, r, j] = byKey[m] || [];
      const pts = j && centralSeries(j, idx);
      if (!pts) continue;
      present[m] = true;
      used.push(`${C.models[m].short} ${runLabel(r)}`);
      const md = C.models[m];
      series.push({ label: md.label, tipLabel: md.label + (r !== cycle ? ` (${runLabel(r)})` : ""), color: md.color, symbol: md.symbol, filled: md.filled, points: pts, ms: 6 });
    }
    const obs = obsSeries(idx, x0, runMs(cycle));
    series.unshift(Object.assign({ points: obs }, OBS));
    const info = C.indices[idx];
    TC.lineChart(container, {
      title: `${info.name} [${info.abbr}] Forecast`, sub: `Updated --> ${cycle}`, site: C.siteLabel,
      x0, x1, series, legend: legendAll(present), initTime: runMs(cycle), labelPhase: 1,
      yTitle: idx === "aam" ? "global relative AAM, standardized (σ)" : null
    });
    return used;
  }

  async function singleChart(container, idx, model) {
    const r = runAtOrBefore(model, state.cycle) || runsOf(model)[0];
    if (!r) return note(container, "No runs available for this model yet.");
    const j = await loadRun(model, r);
    const md = C.models[model], info = C.indices[idx];
    if (!j || !j.indices[idx]) return note(container, `${md.short} ${r} has no ${info.abbr} data.`);
    const d = j.indices[idx], ts = times(j);
    if (d.members) {
      const nd = Math.round((ts[ts.length - 1] - ts[0]) / DAY);
      TC.boxChart(container, {
        title: `${md.short} ${info.name} [${info.abbr}]   ${d.members.length}-member ensemble`,
        sub: `${nd}-day Forecast Init: ${initLabel(r)}`, site: C.siteLabel,
        times: ts, stats: ts.map((_, i) => ensStats(d.members, i)), members: d.members,
        showMembers: state.members, memberColor: md.color
      });
    } else {
      const [x0, x1] = xRange(r);
      TC.lineChart(container, {
        title: `${md.short} ${info.name} [${info.abbr}] Forecast`, sub: `Updated --> ${r}`, site: C.siteLabel,
        x0, x1, initTime: runMs(r), labelPhase: 1,
        series: [Object.assign({ points: obsSeries(idx, x0, runMs(r)) }, OBS),
                 { label: md.label, color: md.color, symbol: md.symbol, filled: md.filled, points: centralSeries(j, idx), ms: 6 }],
        legend: [{ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled }, { label: "OBSERVED", color: "#000", symbol: "circle", filled: false }]
      });
    }
    return [`${md.short} ${runLabel(r)}`];
  }

  function shade(hex, f) {   // f=0 -> light, 1 -> full color
    const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    const mix = c => Math.round(c * (0.25 + 0.75 * f) + 235 * (1 - (0.25 + 0.75 * f)));
    return `rgb(${mix(r)},${mix(g)},${mix(b)})`;
  }

  async function trendChart(container, idx, model) {
    const all = runsOf(model).filter(r => r <= state.cycle).slice(0, state.n);
    if (!all.length) return note(container, "No runs available for this model yet.");
    const js = await Promise.all(all.map(r => loadRun(model, r)));
    const md = C.models[model], info = C.indices[idx];
    const [x0, x1] = xRange(all[0]);
    const series = [Object.assign({ points: obsSeries(idx, x0, runMs(all[0])) }, OBS)];
    const legend = [];
    const k = all.length;
    for (let i = k - 1; i >= 0; i--) {
      const pts = js[i] && centralSeries(js[i], idx);
      if (!pts) continue;
      const f = k === 1 ? 1 : (k - 1 - i) / (k - 1);
      const col = i === 0 ? md.color : shade(md.color, f * 0.85);
      series.push({ label: runLabel(all[i]), color: col, symbol: md.symbol, filled: i === 0, points: pts, ms: i === 0 ? 6 : 4, lw: i === 0 ? 2.4 : 1.4 });
      legend.unshift({ label: runLabel(all[i]), color: col, symbol: md.symbol, filled: i === 0, textColor: i === 0 ? md.color : "#555" });
    }
    TC.lineChart(container, {
      title: `${md.short}${md.kind === "ens" ? " mean" : ""} ${info.abbr} — last ${k} runs`, sub: `Updated --> ${all[0]}`, site: C.siteLabel,
      x0, x1, series, legend, initTime: runMs(all[0]), labelPhase: 1,
      legendX: 610, legendColW: 140, legendPerRow: 4, top: 70 + Math.max(0, Math.ceil(k / 4) - 2) * 22
    });
    return all.map(runLabel);
  }

  /* ---------- MJO ---------------------------------------------------------- */
  function mjoPts(j, which) {
    const d = j && j.indices.mjo;
    if (!d) return null;
    const ts = times(j), t0 = runMs(j.run);
    const a = which === undefined ? d.rmm1 : d.members_rmm1[which], b = which === undefined ? d.rmm2 : d.members_rmm2[which];
    return ts.map((t, i) => ({ t, x: a[i], y: b[i], lead: Math.round((t - t0) / DAY * 10) / 10 }))
      .filter(p => p.x !== null && p.y !== null && Number.isInteger(p.lead));     // one point per day
  }
  function mjoObs(cycle, days) {
    if (!analysis || !analysis.rmm1) return [];
    const t1 = runMs(cycle), t0 = t1 - days * DAY;
    return analysis.times.map((r, i) => ({ t: runMs(r), x: analysis.rmm1[i], y: analysis.rmm2[i] }))
      .filter(p => p.x !== null && p.x !== undefined && p.t >= t0 && p.t <= t1 && new Date(p.t).getUTCHours() === 0);
  }
  async function mjoView(phaseBox, ampBox) {
    const cyc = state.cycle, tracks = [], ampSeries = [], legend = [];
    let windOnly = [], used = [];
    const obs = mjoObs(cyc, 40);
    const obsTrack = { label: "Observed (40 days)", color: "#222", lw: 2.2, ms: 2.5, points: obs, endLabel: obs.length ? "OBS" : null };
    const ampOf = pts => pts.map(p => ({ t: p.t, v: Math.hypot(p.x, p.y) }));
    let title = `${C.indices.mjo.name} [MJO] RMM Forecast`, sub = `Updated --> ${cyc}`;
    if (state.view === "all") {
      for (const m of MODEL_KEYS) {
        const r = runAtOrBefore(m, cyc, C.sameCycleHours);
        const j = r && await loadRun(m, r);
        const pts = j && mjoPts(j);
        const md = C.models[m];
        legend.push({ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled, dim: !pts });
        if (!pts) continue;
        if (j.indices.mjo.wind_only) windOnly.push(md.short);
        used.push(`${md.short} ${runLabel(r)}`);
        tracks.push({ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled, points: pts, ms: 3.5, lw: 2, dayMarks: true, startMark: false });
        ampSeries.push({ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled, points: ampOf(pts), ms: 4 });
      }
    } else {
      const m = state.model, md = C.models[m];
      const runs = state.view === "trend" ? runsOf(m).filter(r => r <= cyc).slice(0, state.n) : [runAtOrBefore(m, cyc) || runsOf(m)[0]].filter(Boolean);
      const js = await Promise.all(runs.map(r => loadRun(m, r)));
      if (state.view === "model" && js[0]) {
        const d = js[0].indices.mjo;
        if (d && d.members_rmm1) d.members_rmm1.forEach((_, i) => tracks.push({ label: `member ${i}`, color: md.color, opacity: 0.22, lw: 1, ms: 0, points: mjoPts(js[0], i), tooltip: true, tipLabel: `${md.short} member ${i}` }));
        const pts = mjoPts(js[0]);
        if (pts) {
          tracks.push({ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled, points: pts, ms: 4, lw: 3, dayMarks: true });
          ampSeries.push({ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled, points: ampOf(pts), ms: 5 });
          legend.push({ label: md.label, color: md.color, symbol: md.symbol, filled: md.filled });
          if (d.members_rmm1) legend.push({ swatch: "line", label: `${d.members_rmm1.length} members`, color: md.color, opacity: 0.35, textColor: "#555" });
          if (d.wind_only) windOnly.push(md.short);
          used.push(`${md.short} ${runLabel(runs[0])}`);
        }
        title = `${md.short} MJO RMM Forecast`; sub = `Init: ${initLabel(runs[0])}`;
      } else {
        const k = runs.length;
        for (let i = k - 1; i >= 0; i--) {
          const pts = js[i] && mjoPts(js[i]);
          if (!pts) continue;
          const col = i === 0 ? md.color : shade(md.color, k === 1 ? 1 : (k - 1 - i) / (k - 1) * 0.85);
          tracks.push({ label: runLabel(runs[i]), color: col, symbol: md.symbol, filled: i === 0, points: pts, ms: i === 0 ? 4 : 3, lw: i === 0 ? 3 : 1.5, dayMarks: i === 0 });
          ampSeries.push({ label: runLabel(runs[i]), color: col, symbol: md.symbol, filled: i === 0, points: ampOf(pts), ms: i === 0 ? 5 : 3, lw: i === 0 ? 2.4 : 1.3 });
          legend.unshift({ label: runLabel(runs[i]), color: col, symbol: md.symbol, filled: i === 0, textColor: i === 0 ? md.color : "#555" });
        }
        used = runs.map(runLabel);
        title = `${md.short} MJO — last ${k} runs`; sub = `Latest: ${initLabel(runs[0] || cyc)}`;
      }
    }
    tracks.unshift(obsTrack);
    TC.phaseDiagram(phaseBox, { title, sub, site: C.siteLabel, tracks, legend, legendX: 395, legendColW: 185, legendPerRow: 2 });
    const t = runMs(cyc);
    ampSeries.unshift(Object.assign({}, OBS, { points: obs.map(p => ({ t: p.t, v: Math.hypot(p.x, p.y) })), ms: 4 }));
    TC.lineChart(ampBox, {
      title: "MJO Amplitude", sub: "RMM amplitude (≥ 1 = active MJO)", x0: t - 20 * DAY, x1: t + 16 * DAY, yMin: 0, yMax: 4, yFixed: true,
      series: ampSeries, legend: [], initTime: t, width: 760, height: 520, labelEvery: 4, labelPhase: 0
    });
    return { used, windOnly };
  }

  /* ---------- render ------------------------------------------------------- */
  function note(container, msg) { container.innerHTML = `<div class="empty">${msg}</div>`; return []; }

  async function render() {
    const cycles = allCycles();
    if (cycles.length && (state.follow || !state.cycle || !cycles.includes(state.cycle))) state.cycle = cycles[0];
    buildTabs(); buildControls(); writeHash();
    const main = $("#main");
    if (!cycles.length && state.tab !== "outlooks") {
      main.innerHTML = `<div class="empty">No model runs yet. Run <code>pipeline/run_ingest.py</code> to populate <code>${C.dataPath}</code>.</div>`;
      return;
    }
    $("#updated").textContent = manifest.updated ? `Data updated ${manifest.updated.replace("T", " ")}` : "";
    const tab = state.tab;
    if (tab === "outlooks") return renderOutlooks(main);
    if (tab === "overview") {
      main.innerHTML = `<div class="grid">${LINE_IDX.map(i => `<div class="card click" data-go="${i}"><div class="chart" id="ov-${i}"></div></div>`).join("")}<div class="card click" data-go="mjo"><div class="chart" id="ov-mjo"></div></div></div>`;
      main.querySelectorAll("[data-go]").forEach(c => c.onclick = () => { state.tab = c.dataset.go; state.view = "all"; render(); window.scrollTo(0, 0); });
      await Promise.all(LINE_IDX.map(i => allModelsChart($("#ov-" + i), i, state.cycle, true)));
      const v = state.view; state.view = "all";
      const tmp = document.createElement("div");
      await mjoView($("#ov-mjo"), tmp);
      state.view = v;
      return;
    }
    if (tab === "mjo") {
      main.innerHTML = `<div class="mjo"><div class="card"><div class="chart" id="phase"></div></div><div class="card"><div class="chart" id="amp"></div><div class="notes" id="mjoNotes"></div></div></div><div class="runs" id="runsUsed"></div>`;
      const { used, windOnly } = await mjoView($("#phase"), $("#amp"));
      $("#runsUsed").textContent = used.length ? "Runs shown: " + used.join(" · ") : "";
      $("#mjoNotes").innerHTML = `<p>Large markers every 5 days of lead time. Points inside the gray circle (amplitude &lt; 1) are a weak or incoherent MJO.</p>` +
        (windOnly.length ? `<p><b>Wind-only RMM</b> (no OLR in the model output): ${windOnly.join(", ")}. These tend to show less amplitude than the full index.</p>` : "") +
        `<p>Observed track: last 40 days from the analysis history.</p>`;
      return;
    }
    main.innerHTML = `<div class="card"><div class="chart" id="chart"></div></div><div class="runs" id="runsUsed"></div>`;
    let used;
    if (state.view === "all") used = await allModelsChart($("#chart"), tab, state.cycle);
    else if (state.view === "model") used = await singleChart($("#chart"), tab, state.model);
    else used = await trendChart($("#chart"), tab, state.model);
    $("#runsUsed").textContent = used && used.length ? "Runs shown: " + used.join(" · ") : "";
  }

  function renderOutlooks(main) {
    main.innerHTML = C.outlooks.map(g => `<h2 class="grp">${g.group}</h2><div class="ogrid">` + g.items.map(it =>
      `<a class="card ocard" href="${it.link || it.img}" target="_blank" rel="noopener"><div class="otitle">${it.title}</div><img loading="lazy" src="${it.img}?t=${Math.floor(Date.now() / 3.6e6)}" alt="${it.title}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'empty',textContent:'Image unavailable — check the URL in js/config.js'}))"></a>`).join("") + `</div>`).join("");
  }

  /* ---------- wiring ------------------------------------------------------- */
  async function refresh(first) {
    try {
      const m = await getJSON("manifest.json", true);
      const changed = JSON.stringify(m.models) !== JSON.stringify(manifest.models);
      manifest = m;
      if (changed || first) {
        analysis = await getJSON("analysis.json", true).catch(() => null);
        if (!runsOf(state.model).length) state.model = MODEL_KEYS.find(k => runsOf(k).length) || state.model;
        $("#status").textContent = m.demo ? "DEMO DATA — synthetic values, not real forecasts" : "";
        render();
      }
    } catch (e) {
      $("#status").textContent = "Could not load data (" + e.message + "). Serve this folder over http(s).";
      if (first) render();
    }
  }

  function init() {
    document.title = C.siteLabel;
    $("#siteTitle").textContent = C.siteLabel;
    readHash();
    $("#modelSel").onchange = e => { state.model = e.target.value; render(); };
    $("#runSel").onchange = e => { state.cycle = e.target.value; state.follow = e.target.selectedIndex === 0; render(); };
    $("#prevRun").onclick = () => stepRun(-1);
    $("#nextRun").onclick = () => stepRun(1);
    $("#latestBtn").onclick = () => { state.follow = true; state.cycle = null; render(); };
    $("#trendN").onchange = e => { state.n = +e.target.value; render(); };
    $("#memChk").onchange = e => { state.members = e.target.checked; render(); };
    $("#pngBtn").onclick = () => {
      const svgs = document.querySelectorAll("#main svg");
      svgs.forEach((s, i) => TC.exportPNG(s, `${state.tab}_${state.view}_${state.cycle}${svgs.length > 1 ? "_" + (i + 1) : ""}.png`));
    };
    document.addEventListener("keydown", e => {
      if (["INPUT", "SELECT"].includes(document.activeElement.tagName)) return;
      if (e.key === "ArrowLeft") stepRun(-1);
      if (e.key === "ArrowRight") stepRun(1);
    });
    refresh(true);
    if (!EMBED) setInterval(() => refresh(false), C.refreshMinutes * 60000);
  }
  document.addEventListener("DOMContentLoaded", init);
})();
