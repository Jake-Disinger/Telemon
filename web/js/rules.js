/* Bering Sea Rule and Typhoon Rule tabs. Exposes window.TeleRules = { bsr, typhoon }. */
(function () {
  "use strict";
  const TC = window.TeleCharts, TM = window.TeleMaps, DAY = TC.DAY, MON = TC.MON;
  const pad2 = n => String(n).padStart(2, "0");
  const LS_KEY = "telemon.bsr";
  const geoCache = {};

  function loadGeo(name) {
    if (window.TELE_EMBED && window.TELE_EMBED.geo) return Promise.resolve(window.TELE_EMBED.geo[name]);
    if (!geoCache[name]) geoCache[name] = fetch("geo/" + name + ".json").then(r => r.json()).catch(() => null);
    return geoCache[name];
  }
  function readLS() { try { return JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch (e) { return {}; } }
  function writeLS(v) { try { localStorage.setItem(LS_KEY, JSON.stringify(v)); } catch (e) { /* storage off */ } }
  const ridMs = r => Date.UTC(+r.slice(0, 4), +r.slice(4, 6) - 1, +r.slice(6, 8), +r.slice(8, 10));
  const fmtDay = t => { const d = new Date(t); return `${["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getUTCDay()]} ${pad2(d.getUTCDate())} ${MON[d.getUTCMonth()]}`; };
  const fmtValid = t => { const d = new Date(t); return `${pad2(d.getUTCHours())}Z ${pad2(d.getUTCDate())} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* ======================= Bering Sea Rule ======================================= */
  async function bsr(main, ctx) {
    const C = ctx.C, cfg = C.bsr, man = ctx.manifest();
    const saved = readLS();
    const st = Object.assign({ source: "models", lag: cfg.lagDays, field: "mslp", model: "analysis", run: null, idx: null, adjust: false }, saved.view || {});
    const overlay = Object.assign({}, cfg.overlay, saved.overlay2 || {});
    const cals = Object.assign({}, ...cfg.opc.filter(o => o.cal).map(o => ({ [o.key]: o.cal })), saved.cal || {});
    const save = () => writeLS({ view: { source: st.source, lag: st.lag, field: st.field, model: st.model }, overlay2: overlay, cal: cals });
    const [coast, us] = await Promise.all([loadGeo("coast"), loadGeo("us")]);
    const maps = (man.maps) || {};
    const MODEL_OPTS = [["analysis", "Observed (GFS analysis)"]].concat(Object.keys(C.models).map(k => [k, C.models[k].label.replace(" MEAN", "") + (C.models[k].kind === "ens" ? " mean" : "")]));

    main.innerHTML = `
      <div class="rules-bar card">
        <div class="ctl"><span class="lab">Source</span><div class="seg" id="bsrSrc"></div></div>
        <div class="ctl"><span class="lab">Lag</span><select id="bsrLag">${Array.from({ length: 16 }, (_, i) => 10 + i).map(d => `<option value="${d}" ${d === st.lag ? "selected" : ""}>${d} days</option>`).join("")}</select></div>
        <div class="ctl" id="bsrModelCtl"><span class="lab">Maps</span><select id="bsrModel"></select><select id="bsrRun"></select></div>
        <div class="ctl" id="bsrFieldCtl"><span class="lab">Field</span><div class="seg" id="bsrField"></div></div>
        <div class="ctl right"><button id="bsrAdjBtn">Adjust overlay</button></div>
      </div>
      <div class="card adjust" id="bsrAdj" hidden>
        <b>US overlay placement</b> — where the center of the US map (39N 96W) lands, its size relative to the chart, and its rotation. The default matches the classic Bering Sea Rule charts.
        <div class="adjrow">
          <label>Latitude <input type="range" id="ovLat" min="35" max="62" step="0.25"><span id="ovLatV"></span></label>
          <label>Longitude <input type="range" id="ovLon" min="160" max="205" step="0.25"><span id="ovLonV"></span></label>
          <label>Size <input type="range" id="ovScale" min="0.8" max="1.7" step="0.01"><span id="ovScaleV"></span></label>
          <label>Rotate <input type="range" id="ovRot" min="-20" max="20" step="0.5"><span id="ovRotV"></span></label>
          <button id="ovReset">Reset</button><button id="ovCopy">Copy settings</button>
        </div>
        <div class="tc-muted" id="ovMsg">Changes are remembered in this browser. To make them the default for everyone, use "Copy settings" and paste into <code>bsr.overlay</code> in <code>js/config.js</code>.</div>
      </div>
      <div id="bsrBody"></div>
      <div class="notes">Bering Sea Rule (J. Renken): the pattern over the Bering Sea / Aleutians tends to repeat over the central and eastern US about 17–21 days later — a trough there suggests a trough here. The US outline is drawn where the rule maps it; the date in the corner is the valid time plus the lag. This is a forecaster heuristic, not a verified index.</div>`;

    TC_seg("#bsrSrc", [["opc", "OPC charts"], ["models", "Model maps"]], st.source, v => { st.source = v; save(); draw(); });
    TC_seg("#bsrField", [["mslp", "Sea-level pressure"], ["z500a", "500 mb height anomaly"]], st.field, v => { st.field = v; save(); draw(); });
    const $ = s => main.querySelector(s);
    $("#bsrLag").onchange = e => { st.lag = +e.target.value; save(); draw(); };
    $("#bsrAdjBtn").onclick = () => { st.adjust = !st.adjust; $("#bsrAdj").hidden = !st.adjust; };
    const sliders = [["ovLat", "lat", v => v.toFixed(2) + "N"], ["ovLon", "lon", v => (v <= 180 ? v.toFixed(2) + "E" : (360 - v).toFixed(2) + "W")], ["ovScale", "scale", v => v.toFixed(2) + "×"], ["ovRot", "rot", v => v.toFixed(1) + "°"]];
    const syncSliders = () => sliders.forEach(([id, k, f]) => { $("#" + id).value = overlay[k]; $("#" + id + "V").textContent = f(+overlay[k]); });
    sliders.forEach(([id, k, f]) => { $("#" + id).oninput = e => { overlay[k] = +e.target.value; $("#" + id + "V").textContent = f(overlay[k]); save(); redrawOverlayOnly(); }; });
    $("#ovReset").onclick = () => { Object.assign(overlay, cfg.overlay); syncSliders(); save(); draw(); };
    $("#ovCopy").onclick = () => {
      const txt = `overlay: { lat: ${overlay.lat}, lon: ${overlay.lon}, scale: ${overlay.scale}, rot: ${overlay.rot} },`;
      (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => { $("#ovMsg").textContent = "Copied: " + txt; }, () => { $("#ovMsg").textContent = txt; });
    };
    syncSliders();

    let redrawOverlayOnly = () => draw();

    function fillModels() {
      const sel = $("#bsrModel");
      sel.innerHTML = MODEL_OPTS.map(([k, lab]) => `<option value="${k}" ${k === st.model ? "selected" : ""} ${(maps[k] || []).length ? "" : "disabled"}>${lab}</option>`).join("");
      if (!(maps[st.model] || []).length) { const f = MODEL_OPTS.find(([k]) => (maps[k] || []).length); if (f) { st.model = f[0]; sel.value = f[0]; } }
      sel.onchange = e => { st.model = e.target.value; st.run = null; st.idx = null; save(); draw(); };
    }

    async function draw() {
      $("#bsrModelCtl").style.display = st.source === "models" ? "" : "none";
      $("#bsrFieldCtl").style.display = st.source === "models" ? "" : "none";
      TC_seg("#bsrSrc", [["opc", "OPC charts"], ["models", "Model maps"]], st.source, v => { st.source = v; save(); draw(); });
      TC_seg("#bsrField", [["mslp", "Sea-level pressure"], ["z500a", "500 mb height anomaly"]], st.field, v => { st.field = v; save(); draw(); });
      if (st.source === "opc") return drawOPC();
      fillModels();
      const body = $("#bsrBody");
      const list = maps[st.model] || [];
      const runSel = $("#bsrRun");
      if (!list.length) {
        runSel.style.display = "none";
        body.innerHTML = `<div class="card empty">No North Pacific maps saved yet. They are written by each new model run (and the Setup backfill for observed maps), so they appear after the next ingest.</div>`;
        return;
      }
      let frames;                       // [{label, mapFile, stepIndex, valid}]
      if (st.model === "analysis") {
        runSel.style.display = "none";
        frames = list.slice().reverse().map(r => ({ file: r, si: 0, valid: ridMs(r) }));
      } else {
        runSel.style.display = "";
        if (!st.run || !list.includes(st.run)) st.run = list[0];
        runSel.innerHTML = list.map(r => `<option value="${r}" ${r === st.run ? "selected" : ""}>${r.slice(8, 10)}Z ${r.slice(6, 8)} ${MON[+r.slice(4, 6) - 1]}</option>`).join("");
        runSel.onchange = e => { st.run = e.target.value; st.idx = null; draw(); };
        const j = await getMap(st.model, st.run);
        frames = j ? j.steps.map((s, i) => ({ file: st.run, si: i, valid: ridMs(st.run) + s * 3600e3, step: s })) : [];
      }
      if (!frames.length) { body.innerHTML = `<div class="card empty">This map file could not be loaded.</div>`; return; }
      if (st.idx == null || st.idx >= frames.length) st.idx = st.model === "analysis" ? frames.length - 1 : 0;
      body.innerHTML = `
        <div class="card"><div class="slider-row">
          <button id="fPrev">◀</button><input type="range" id="fIdx" min="0" max="${frames.length - 1}" value="${st.idx}"><button id="fNext">▶</button>
          <span id="fLab" class="flab"></span></div>
          <div class="chart" id="bsrMap"></div>
          <div class="strip" id="bsrStrip"></div></div>`;
      const go = i => { st.idx = Math.max(0, Math.min(frames.length - 1, i)); $("#fIdx").value = st.idx; render1(); };
      $("#fIdx").oninput = e => go(+e.target.value);
      $("#fPrev").onclick = () => go(st.idx - 1);
      $("#fNext").onclick = () => go(st.idx + 1);
      // strip: every frame's projected date, clickable
      $("#bsrStrip").innerHTML = frames.map((f, i) => `<button data-i="${i}" class="${i === st.idx ? "on" : ""}">${fmtDay(f.valid)}<br><b>→ ${fmtDay(f.valid + st.lag * DAY)}</b></button>`).join("");
      $("#bsrStrip").querySelectorAll("button").forEach(b => b.onclick = () => go(+b.dataset.i));
      async function render1() {
        const f = frames[st.idx];
        $("#bsrStrip").querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i === st.idx));
        const j = await getMap(st.model, f.file);
        if (!j) return;
        const proj = f.valid + st.lag * DAY;
        const name = MODEL_OPTS.find(m => m[0] === st.model)[1];
        $("#fLab").innerHTML = `Valid <b>${fmtValid(f.valid)}</b>${f.step != null ? ` (+${f.step} h)` : ""} &nbsp;→&nbsp; projects to <b>${fmtDay(proj)}</b> in the eastern US`;
        const fieldName = st.field === "mslp" ? "Sea-level pressure" : "500 mb height (dam) and anomaly";
        const opts = {
          title: `${name} — ${fieldName}`, sub: `Valid ${fmtValid(f.valid)}${f.step != null ? `  ·  init ${fmtValid(ridMs(f.file))}` : ""}  ·  lag ${st.lag} days`,
          badge: fmtDay(proj).slice(4), bounds: cfg.mapBounds,
          meta: j, field: st.field, mslp: j.mslp[f.si], z500: j.z500[f.si], z500a: j.z500a[f.si], coast, us, overlay
        };
        TM.bsrMap($("#bsrMap"), opts);
        redrawOverlayOnly = () => TM.bsrMap($("#bsrMap"), Object.assign(opts, { overlay }));
      }
      render1();
    }

    const mapCache = {};
    function getMap(model, run) {
      const k = model + "/" + run;
      if (!mapCache[k]) mapCache[k] = ctx.getJSON(`maps/${model}/${run}.json`).catch(() => null);
      return mapCache[k];
    }

    function drawOPC() {
      const body = $("#bsrBody");
      const now = Date.now();
      const base00 = Math.floor((now - 4 * 3600e3) / (6 * 3600e3)) * 6 * 3600e3;   // latest analysis time (approx.)
      const base12 = Math.floor((now - 5 * 3600e3) / (12 * 3600e3)) * 12 * 3600e3;  // latest forecast issuance (approx.)
      body.innerHTML = `<div class="ogrid opc">` + cfg.opc.map(o => {
        const valid = (o.lead ? base12 : base00) + o.lead * 3600e3, proj = valid + st.lag * DAY;
        return `<div class="card ocard" data-key="${o.key}">
          <div class="otitle">${esc(o.title)} <span class="tc-muted">valid ≈ ${fmtValid(valid)} → <b>${fmtDay(proj)}</b></span>
            <span class="obtns"><button data-act="cal">Calibrate</button>${cals[o.key] ? `<button data-act="grid">Check grid</button>` : ""}</span></div>
          <div class="calmsg" hidden></div>
          <div class="opcwrap"><img src="${esc(o.url)}?t=${Math.floor(now / 1.8e6)}" alt="${esc(o.title)}"><svg class="opcsvg"></svg>
            <div class="opcdate">${fmtDay(proj).slice(4)}</div></div></div>`;
      }).join("") + `</div><div class="notes">OPC chart valid times above are estimated from the current time (check the chart's own label); the projected date follows from it. Charts need a one-time calibration so the overlay lands on the right latitudes and longitudes — click <b>Calibrate</b> and follow the two prompts.</div>`;
      body.querySelectorAll(".ocard").forEach(card => {
        const o = cfg.opc.find(x => x.key === card.dataset.key);
        const img = card.querySelector("img"), svg = card.querySelector("svg"), msg = card.querySelector(".calmsg");
        let showGrid = false;
        const paint = () => {
          if (!img.naturalWidth) return;
          svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
          svg.innerHTML = "";
          if (cals[o.key]) TM.chartOverlay(svg, cals[o.key], us, overlay, { width: img.naturalWidth / 520, grid: showGrid });
        };
        img.onload = paint;
        img.onerror = () => { card.querySelector(".opcwrap").innerHTML = `<div class="empty">Chart image unavailable — check its URL in <code>js/config.js</code> (bsr.opc).</div>`; };
        if (img.complete) paint();
        const wire = () => card.querySelectorAll("button[data-act]").forEach(b => b.onclick = () => {
          if (b.dataset.act === "grid") { showGrid = !showGrid; b.classList.toggle("on", showGrid); paint(); return; }
          startCal(o, img, svg, msg, () => {
            showGrid = true;
            let gb = card.querySelector("button[data-act=grid]");
            if (!gb) { gb = document.createElement("button"); gb.dataset.act = "grid"; gb.textContent = "Check grid"; card.querySelector(".obtns").appendChild(gb); wire(); }
            gb.classList.add("on");
            paint();
          });
        });
        wire();
      });
      redrawOverlayOnly = () => body.querySelectorAll(".ocard").forEach(card => { const img = card.querySelector("img"); if (img && img.onload) img.onload(); });
    }

    function startCal(o, img, svg, msg, done) {
      const pts = [], targets = [{ lat: 50, lon: 160 }, { lat: 30, lon: 220 }];
      msg.hidden = false;
      const ask = () => {
        const t = targets[pts.length];
        msg.innerHTML = `Step ${pts.length + 1} of 2 — click a grid intersection on the chart and enter its position:
          <input type="number" class="cl" value="${t.lat}" step="1"> °N
          <input type="number" class="cn" value="${t.lon <= 180 ? t.lon : 360 - t.lon}" step="1"> <select class="ce"><option ${t.lon <= 180 ? "selected" : ""}>E</option><option ${t.lon > 180 ? "selected" : ""}>W</option></select>
          &nbsp;Projection <select class="cp"><option value="mercator">Mercator (straight grid)</option><option value="polar">Polar stereographic (curved grid)</option></select>
          <button class="cx">Cancel</button>`;
        msg.querySelector(".cx").onclick = () => { svg.onclick = null; svg.style.cursor = ""; msg.hidden = true; };
      };
      ask();
      svg.style.cursor = "crosshair";
      svg.onclick = evt => {
        const p = svg.createSVGPoint(); p.x = evt.clientX; p.y = evt.clientY;
        const q = p.matrixTransform(svg.getScreenCTM().inverse());
        const lat = +msg.querySelector(".cl").value, lonv = +msg.querySelector(".cn").value, ew = msg.querySelector(".ce").value;
        const kind = msg.querySelector(".cp").value;
        pts.push({ x: q.x, y: q.y, lat, lon: ew === "E" ? lonv : 360 - lonv, kind });
        TC.el("circle", { cx: q.x, cy: q.y, r: 6, fill: "none", stroke: "#e0007a", "stroke-width": 3 }, svg);
        if (pts.length < 2) { ask(); msg.querySelector(".cp").value = kind; return; }
        svg.onclick = null; svg.style.cursor = "";
        cals[o.key] = TM.solveCal(pts[1].kind, pts[0], pts[1]);
        save(); done();
        const snippet = `cal: ${JSON.stringify(cals[o.key])}`;
        msg.innerHTML = `Calibrated (saved in this browser). Use <b>Check grid</b> to confirm the pink lat/lon lines sit on the chart's grid. To share it, paste this into the <code>${o.key}</code> entry in <code>js/config.js</code>:<br><code class="snip">${esc(snippet)}</code> <button class="cc">Copy</button> <button class="cx">Close</button>`;
        msg.querySelector(".cx").onclick = () => { msg.hidden = true; };
        msg.querySelector(".cc").onclick = () => { if (navigator.clipboard) navigator.clipboard.writeText(snippet); };
      };
    }

    draw();
  }

  // segmented control helper (same look as the main controls)
  function TC_seg(sel, opts, cur, onPick) {
    const box = document.querySelector(sel); if (!box) return;
    box.innerHTML = "";
    opts.forEach(([v, lab]) => { const b = document.createElement("button"); b.textContent = lab; b.className = v === cur ? "on" : ""; b.onclick = () => onPick(v); box.appendChild(b); });
  }

  /* ======================= Typhoon Rule ========================================== */
  async function typhoon(main, ctx) {
    const C = ctx.C, cfg = C.typhoon;
    const [coast, data] = await Promise.all([loadGeo("coast"), ctx.getJSON("typhoons.json").catch(() => null)]);
    if (!data) {
      main.innerHTML = `<div class="card empty">No typhoon data yet. The ingest downloads NOAA IBTrACS West Pacific tracks every 6 hours; they will appear after the next run.</div>`;
      return;
    }
    const now = Date.now(), cutoff = now - cfg.daysShown * DAY;
    const storms = data.storms.filter(s => ridMs(s.last) >= cutoff);
    const updated = data.updated.replace("T", " ");
    main.innerHTML = `
      <div class="card"><div class="chart" id="tyMap"></div></div>
      <div class="card"><div class="chart" id="tyLine"></div></div>
      <div class="card"><table class="ty"><thead><tr><th>Storm</th><th>Active</th><th>Peak wind</th><th>Recurvature</th><th>Near Japan</th><th>Eastern-US trough window</th></tr></thead><tbody id="tyRows"></tbody></table></div>
      <div class="notes">Typhoon Rule (J. Renken): a typhoon that recurves near Japan tends to be followed by a trough and storminess over the eastern US about ${cfg.lagDays[0]}–${cfg.lagDays[1]} days later. Recurvature here is the westernmost point of a track that then moves at least 4° east and 3° north; "near Japan" means the recurvature or later track passes through the shaded box. Red bars and stars are typhoon-strength storms (≥64 kt); gray ones are weaker storms that recurved near Japan. Tracks come from NOAA IBTrACS (updated about three times a week, with a short delay), so the newest positions can lag real time by a day or more. This is a forecaster heuristic, not a verified index.</div>`;
    TM.trackMap(main.querySelector("#tyMap"), {
      title: `West Pacific tropical cyclones — last ${cfg.daysShown} days`,
      sub: `Source: ${data.source}, processed ${updated}. ★ = recurvature`,
      bounds: cfg.mapBounds, japanBox: cfg.japanBox, coast,
      storms: storms.map(s => Object.assign({}, s, { dim: !s.rule && !s.active }))
    });
    const rows = storms.filter(s => s.window).sort((a, b) => a.window[0] < b.window[0] ? 1 : -1).map(s => ({
      label: `${s.name} (${s.max_wind || "?"} kt)`, strong: s.rule, color: s.rule ? "#c0234a" : "#9aa3ad",
      a: ridMs(s.window[0]), b: ridMs(s.window[1]), mark: ridMs(s.recurve.t),
      tip: `<b>${esc(s.name)}</b><div>Recurved ${fmtValid(ridMs(s.recurve.t))} near ${s.recurve.lat}N ${s.recurve.lon}E</div><div>Trough window ${fmtDay(ridMs(s.window[0]))} – ${fmtDay(ridMs(s.window[1]))}</div>`
    }));
    TM.timeline(main.querySelector("#tyLine"), {
      title: "Typhoon Rule: implied eastern-US trough windows (tick = recurvature)",
      rows, t0: now - 21 * DAY, t1: now + 14 * DAY, now,
      empty: "No storms have recurved near Japan in this period"
    });
    main.querySelector("#tyRows").innerHTML = storms.length ? storms.map(s => `<tr class="${s.rule ? "rule" : ""}">
      <td><b>${esc(s.name)}</b>${s.active ? ' <span class="pill">active</span>' : ""}</td>
      <td>${fmtDay(ridMs(s.first))} – ${fmtDay(ridMs(s.last))}</td>
      <td>${s.max_wind == null ? "—" : s.max_wind + " kt"}</td>
      <td>${s.recurve ? `${fmtValid(ridMs(s.recurve.t))}<br><span class="tc-muted">${s.recurve.lat}N ${s.recurve.lon}E</span>` : "—"}</td>
      <td>${s.near_japan ? "Yes" : "—"}</td>
      <td>${s.window ? `<b>${fmtDay(ridMs(s.window[0]))} – ${fmtDay(ridMs(s.window[1]))}</b>${s.rule ? "" : ' <span class="tc-muted">(below typhoon strength)</span>'}` : "—"}</td></tr>`).join("")
      : `<tr><td colspan="6" class="tc-muted">No West Pacific storms in the last ${cfg.daysShown} days.</td></tr>`;
  }

  window.TeleRules = { bsr, typhoon };
})();
