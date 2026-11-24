/* SVG chart renderer styled after weathermodels.com teleconnection graphics.
   No dependencies. Exposes window.TeleCharts = { lineChart, boxChart, phaseDiagram, exportPNG }. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const FONT = "Arial, Helvetica, 'Liberation Sans', sans-serif";
  const MON = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
  const DAY = 86400000;

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, str, a) {
    const t = el("text", Object.assign({ x, y, "font-family": FONT, "font-size": 18, fill: "#000" }, a || {}), parent);
    t.textContent = str;
    return t;
  }
  const pad2 = n => String(n).padStart(2, "0");
  const dLabel = t => { const d = new Date(t); return pad2(d.getUTCDate()) + MON[d.getUTCMonth()]; };
  const fmtNum = (v, n) => (v === null || v === undefined || !isFinite(v)) ? "—" : (v >= 0 ? "+" : "") + v.toFixed(n === undefined ? 2 : n);

  function marker(parent, kind, filled, color, x, y, r, extra) {
    const common = Object.assign({ fill: filled ? color : "#fff", stroke: color, "stroke-width": filled ? 1 : 1.7 }, extra || {});
    if (kind === "square") return el("rect", Object.assign({ x: x - r, y: y - r, width: 2 * r, height: 2 * r }, common), parent);
    return el("circle", Object.assign({ cx: x, cy: y, r }, common), parent);
  }

  function makeSvg(container, w, h, label) {
    container.innerHTML = "";
    container.classList.add("tc-wrap");
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%", role: "img", "aria-label": label || "chart",
      preserveAspectRatio: "xMidYMid meet", style: "display:block;background:#fff" }, container);
    el("rect", { x: 0, y: 0, width: w, height: h, fill: "#fff" }, svg);
    const tip = document.createElement("div");
    tip.className = "tc-tip";
    container.appendChild(tip);
    return { svg, tip };
  }

  function svgPoint(svg, evt) {
    const p = svg.createSVGPoint();
    p.x = evt.clientX; p.y = evt.clientY;
    return p.matrixTransform(svg.getScreenCTM().inverse());
  }
  function placeTip(container, tip, evt, html) {
    tip.innerHTML = html;
    tip.style.display = "block";
    const r = container.getBoundingClientRect();
    let x = evt.clientX - r.left + 16, y = evt.clientY - r.top + 12;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    if (x + tw > r.width - 4) x = evt.clientX - r.left - tw - 16;
    if (y + th > r.height - 4) y = r.height - th - 4;
    tip.style.left = Math.max(2, x) + "px";
    tip.style.top = Math.max(2, y) + "px";
  }

  function niceRange(vals, lo, hi) {
    let mn = lo, mx = hi;
    for (const v of vals) if (v !== null && isFinite(v)) { if (v < mn) mn = Math.floor(v); if (v > mx) mx = Math.ceil(v); }
    const m = Math.max(Math.abs(mn), Math.abs(mx));
    return [-m, m];
  }

  /* -------- title block + legend (shared) ---------------------------------- */
  function header(svg, spec, w) {
    text(svg, 55, 24, spec.title, { "font-size": 19, "font-weight": 500 });
    if (spec.sub) {
      const t = text(svg, 55, 46, spec.sub, { "font-size": 17 });
      if (spec.site) {
        const s = el("tspan", { fill: "#1a5cff", dx: 10, "font-size": 15 }, t);
        s.textContent = spec.site;
      }
    }
  }
  function legend(svg, items, x0, y0, colW, perRow) {
    items.forEach((it, i) => {
      const col = i % perRow, row = Math.floor(i / perRow);
      const x = x0 + col * colW, y = y0 + row * 22;
      if (it.swatch === "box") el("rect", { x: x - 7, y: y - 8, width: 14, height: 15, fill: "#c8c8c8", stroke: "#000" }, svg);
      else if (it.swatch === "whisker") {
        el("line", { x1: x, x2: x, y1: y - 9, y2: y + 8, stroke: it.color, "stroke-width": 2 }, svg);
        el("line", { x1: x - 6, x2: x + 6, y1: y - 9, y2: y - 9, stroke: it.color, "stroke-width": 2 }, svg);
        el("line", { x1: x - 6, x2: x + 6, y1: y + 8, y2: y + 8, stroke: it.color, "stroke-width": 2 }, svg);
      } else if (it.swatch === "line") {
        el("line", { x1: x - 9, x2: x + 9, y1: y, y2: y, stroke: it.color, "stroke-width": 3, opacity: it.opacity || 1 }, svg);
      } else marker(svg, it.symbol, it.filled, it.color, x, y, 6.5, { opacity: it.dim ? 0.35 : 1 });
      text(svg, x + 13, y + 6, it.label, { "font-size": 17, fill: it.textColor || it.color, opacity: it.dim ? 0.45 : 1 });
    });
  }

  /* -------- multi-series line chart --------------------------------------- */
  function lineChart(container, spec) {
    const W = spec.width || 1200, H = spec.height || 600;
    const { svg, tip } = makeSvg(container, W, H, spec.title);
    const L = 58, R = W - 25, T = spec.top || 70, B = H - 55;
    header(svg, spec, W);
    const all = [];
    for (const s of spec.series) for (const p of s.points) all.push(p.v);
    let [y0, y1] = spec.yFixed ? [spec.yMin, spec.yMax] : niceRange(all, spec.yMin === undefined ? -5 : spec.yMin, spec.yMax === undefined ? 5 : spec.yMax);
    if (spec.yMin === 0 && spec.yFixed !== true) y0 = 0;
    const x0 = spec.x0, x1 = spec.x1;
    const sx = t => L + (t - x0) / (x1 - x0) * (R - L);
    const sy = v => T + (y1 - v) / (y1 - y0) * (B - T);
    const g = el("g", {}, svg);
    // grid: dotted lines every unit / every day
    const ystep = (y1 - y0) > 12 ? 2 : 1;
    for (let v = Math.ceil(y0); v <= y1; v += ystep) {
      if (v !== 0) el("line", { x1: L, x2: R, y1: sy(v), y2: sy(v), stroke: "#9a9a9a", "stroke-width": 1, "stroke-dasharray": "1.5,5" }, g);
      text(g, L - 10, sy(v) + 7, String(v), { "text-anchor": "end", "font-size": 19 });
    }
    const firstDay = Math.ceil(x0 / DAY) * DAY;
    let labelled = 0, lastYear = null;
    const phase = spec.labelPhase || 0, every = spec.labelEvery || 2;
    for (let t = firstDay; t <= x1; t += DAY) {
      const d = Math.round((t - firstDay) / DAY);
      el("line", { x1: sx(t), x2: sx(t), y1: T, y2: B, stroke: "#9a9a9a", "stroke-dasharray": "1.5,5" }, g);
      if ((d + phase) % every === 0) {
        el("line", { x1: sx(t), x2: sx(t), y1: B, y2: B + 7, stroke: "#000" }, g);
        text(g, sx(t), B + 26, dLabel(t), { "text-anchor": "middle", "font-size": 18 });
        const yr = new Date(t).getUTCFullYear();
        if (labelled === 0 || yr !== lastYear) text(g, sx(t), B + 47, String(yr), { "text-anchor": "middle", "font-size": 18 });
        labelled++; lastYear = yr;
      } else el("line", { x1: sx(t), x2: sx(t), y1: B, y2: B + 4, stroke: "#000" }, g);
    }
    if (y0 < 0 && y1 > 0) el("line", { x1: L, x2: R, y1: sy(0), y2: sy(0), stroke: "#000", "stroke-width": 3.2 }, g);
    if (spec.initTime) el("line", { x1: sx(spec.initTime), x2: sx(spec.initTime), y1: T, y2: B, stroke: "#777", "stroke-width": 1 }, g);

    // clip to plot
    const cid = "clip" + Math.random().toString(36).slice(2);
    const cp = el("clipPath", { id: cid }, el("defs", {}, svg));
    el("rect", { x: L, y: T, width: R - L, height: B - T }, cp);
    const plot = el("g", { "clip-path": `url(#${cid})` }, svg);

    for (const s of spec.series) {
      const pts = s.points.filter(p => p.v !== null && isFinite(p.v) && p.t >= x0 - DAY && p.t <= x1 + DAY);
      if (!pts.length) continue;
      const grp = el("g", { opacity: s.opacity === undefined ? 1 : s.opacity }, plot);
      if (s.line !== false) {
        // break the line across gaps larger than 1.5x the typical spacing
        let d = "", prev = null;
        for (const p of pts) {
          const gap = prev && (p.t - prev.t) > (s.maxGap || 1.6 * DAY);
          d += (!prev || gap ? "M" : "L") + sx(p.t).toFixed(1) + "," + sy(p.v).toFixed(1);
          prev = p;
        }
        el("path", { d, fill: "none", stroke: s.color, "stroke-width": s.lw || 1.6 }, grp);
      }
      if (s.ms !== 0) for (const p of pts) marker(grp, s.symbol, s.filled, s.color, sx(p.t), sy(p.v), s.ms || 6);
    }
    el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "none", stroke: "#000", "stroke-width": 2 }, svg);
    if (spec.yTitle) text(svg, 16, (T + B) / 2, spec.yTitle, { "font-size": 14, "text-anchor": "middle", transform: `rotate(-90 16 ${(T + B) / 2})` });
    if (spec.watermark) text(svg, R - 8, B - 10, spec.watermark, { "text-anchor": "end", "font-size": 14, fill: "#888" });

    const items = spec.legend || spec.series.filter(s => s.legend !== false).map(s => ({ label: s.label, color: s.color, symbol: s.symbol, filled: s.filled, dim: s.dim }));
    legend(svg, items, spec.legendX || 595, spec.legendY || 17, spec.legendColW || 228, spec.legendPerRow || 3);

    // hover: crosshair + tooltip listing every series at the nearest time
    const hair = el("line", { y1: T, y2: B, stroke: "#333", "stroke-width": 1, "stroke-dasharray": "4,3", visibility: "hidden" }, svg);
    const dots = el("g", { "pointer-events": "none" }, svg);
    const hit = el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "transparent" }, svg);
    const times = Array.from(new Set(spec.series.flatMap(s => s.points.map(p => p.t)))).filter(t => t >= x0 && t <= x1).sort((a, b) => a - b);
    hit.addEventListener("mousemove", evt => {
      if (!times.length) return;
      const pt = svgPoint(svg, evt);
      const t = x0 + (pt.x - L) / (R - L) * (x1 - x0);
      let best = times[0];
      for (const tt of times) if (Math.abs(tt - t) < Math.abs(best - t)) best = tt;
      hair.setAttribute("x1", sx(best)); hair.setAttribute("x2", sx(best)); hair.setAttribute("visibility", "visible");
      dots.innerHTML = "";
      const rows = [];
      for (const s of spec.series) {
        if (s.tooltip === false) continue;
        const p = s.points.find(q => q.t === best);
        if (!p || p.v === null) continue;
        el("circle", { cx: sx(best), cy: sy(p.v), r: 4, fill: s.color, stroke: "#fff", "stroke-width": 2 }, dots);
        rows.push({ s, p });
      }
      rows.sort((a, b) => b.p.v - a.p.v);
      const d = new Date(best);
      const head = `${pad2(d.getUTCHours())}Z ${pad2(d.getUTCDate())} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
      placeTip(container, tip, evt, `<b>${head}</b>` + (rows.length ? "" : "<div class=tc-muted>no data</div>") +
        rows.map(r => `<div class=tc-row><span class=tc-key style="background:${r.s.color}"></span><span class=tc-lab>${r.s.tipLabel || r.s.label}</span><span class=tc-val>${fmtNum(r.p.v)}</span>${r.p.extra ? `<span class=tc-ext>${r.p.extra}</span>` : ""}</div>`).join(""));
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; hair.setAttribute("visibility", "hidden"); dots.innerHTML = ""; });
    return svg;
  }

  /* -------- ensemble box & whisker (ECMWF EPS style) ----------------------- */
  function boxChart(container, spec) {
    const W = spec.width || 1000, H = spec.height || 500;
    const { svg, tip } = makeSvg(container, W, H, spec.title);
    const L = 48, R = W - 40, T = 68, B = H - 40;
    text(svg, 58, 21, spec.title, { "font-size": 17 });
    text(svg, 58, 42, spec.sub, { "font-size": 17 });
    if (spec.site) text(svg, 410, 42, spec.site, { "font-size": 15, fill: "#1a5cff" });
    const vals = [];
    spec.stats.forEach(s => { if (s) vals.push(s.p05, s.p95); });
    if (spec.showMembers) (spec.members || []).forEach(m => m.forEach(v => vals.push(v)));
    const [y0, y1] = niceRange(vals, -6, 6);
    const ts = spec.times, x0 = ts[0], x1 = ts[ts.length - 1];
    const sx = t => L + (t - x0) / (x1 - x0) * (R - L);
    const sy = v => T + (y1 - v) / (y1 - y0) * (B - T);
    for (let v = y0; v <= y1; v++) text(svg, L - 8, sy(v) + 6, String(v), { "text-anchor": "end", "font-size": 17 });
    el("line", { x1: L, x2: R, y1: sy(0), y2: sy(0), stroke: "#555", "stroke-width": 1 }, svg);
    for (let t = Math.ceil(x0 / DAY) * DAY; t <= x1; t += DAY) {
      const d = new Date(t);
      el("line", { x1: sx(t), x2: sx(t), y1: B, y2: B + 5, stroke: "#000" }, svg);
      text(svg, sx(t), B + 23, `${pad2(d.getUTCDate())}/00z`, { "text-anchor": "middle", "font-size": 16 });
    }
    const step = ts.length > 1 ? (sx(ts[1]) - sx(ts[0])) : 20;
    const bw = Math.max(3, Math.min(16, step * 0.55));
    if (spec.members && spec.showMembers) {
      const mg = el("g", { opacity: 0.35 }, svg);
      spec.members.forEach(m => {
        let d = "", pen = false;
        m.forEach((v, i) => { if (v === null) { pen = false; return; } d += (pen ? "L" : "M") + sx(ts[i]).toFixed(1) + "," + sy(v).toFixed(1); pen = true; });
        el("path", { d, fill: "none", stroke: spec.memberColor || "#5b8fd9", "stroke-width": 1 }, mg);
      });
    }
    const wcol = "#3d8be8";
    spec.stats.forEach((s, i) => {
      if (!s) return;
      const x = sx(ts[i]);
      el("line", { x1: x, x2: x, y1: sy(s.p95), y2: sy(s.p75), stroke: wcol, "stroke-width": 1.6 }, svg);
      el("line", { x1: x, x2: x, y1: sy(s.p25), y2: sy(s.p05), stroke: wcol, "stroke-width": 1.6 }, svg);
      el("line", { x1: x - bw * 0.6, x2: x + bw * 0.6, y1: sy(s.p95), y2: sy(s.p95), stroke: wcol, "stroke-width": 1.6 }, svg);
      el("line", { x1: x - bw * 0.6, x2: x + bw * 0.6, y1: sy(s.p05), y2: sy(s.p05), stroke: wcol, "stroke-width": 1.6 }, svg);
      el("rect", { x: x - bw / 2, y: sy(s.p75), width: bw, height: Math.max(1, sy(s.p25) - sy(s.p75)), fill: "#c4c4c4", stroke: "#000", "stroke-width": 1 }, svg);
      el("line", { x1: x - bw / 2, x2: x + bw / 2, y1: sy(s.p50), y2: sy(s.p50), stroke: "#000", "stroke-width": 1 }, svg);
    });
    if (spec.obs && spec.obs.length) {
      let d = "";
      spec.obs.filter(p => p.t >= x0 && p.t <= x1).forEach((p, i) => { d += (i ? "L" : "M") + sx(p.t) + "," + sy(p.v); });
      el("path", { d, fill: "none", stroke: "#000", "stroke-width": 2 }, svg);
    }
    const mc = spec.meanColor || "#1fbf1f";
    let d = "", pen = false;
    spec.stats.forEach((s, i) => { if (!s) { pen = false; return; } d += (pen ? "L" : "M") + sx(ts[i]) + "," + sy(s.mean); pen = true; });
    el("path", { d, fill: "none", stroke: mc, "stroke-width": 1.6 }, svg);
    spec.stats.forEach((s, i) => { if (s) marker(svg, "square", false, mc, sx(ts[i]), sy(s.mean), 5, { "stroke-width": 2 }); });
    el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "none", stroke: "#000", "stroke-width": 1.5 }, svg);
    // legend (two rows like the EPS graphic)
    legend(svg, [{ swatch: "box", label: "25-75%", textColor: "#000" }], 690, 14, 0, 1);
    legend(svg, [{ swatch: "whisker", color: wcol, label: "5-95%", textColor: "#000" }], 860, 14, 0, 1);
    legend(svg, [{ symbol: "square", filled: false, color: mc, label: "Ensemble Mean", textColor: "#000" }], 690, 37, 0, 1);

    const hit = el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "transparent" }, svg);
    const hair = el("line", { y1: T, y2: B, stroke: "#333", "stroke-dasharray": "4,3", visibility: "hidden", "pointer-events": "none" }, svg);
    hit.addEventListener("mousemove", evt => {
      const pt = svgPoint(svg, evt);
      let bi = 0;
      ts.forEach((t, i) => { if (Math.abs(sx(t) - pt.x) < Math.abs(sx(ts[bi]) - pt.x)) bi = i; });
      const s = spec.stats[bi]; if (!s) return;
      hair.setAttribute("x1", sx(ts[bi])); hair.setAttribute("x2", sx(ts[bi])); hair.setAttribute("visibility", "visible");
      const dd = new Date(ts[bi]);
      placeTip(container, tip, evt, `<b>${pad2(dd.getUTCHours())}Z ${pad2(dd.getUTCDate())} ${MON[dd.getUTCMonth()]}</b>` +
        [["95th", s.p95], ["75th", s.p75], ["Median", s.p50], ["Mean", s.mean], ["25th", s.p25], ["5th", s.p05]]
          .map(([k, v]) => `<div class=tc-row><span class=tc-lab>${k}</span><span class=tc-val>${fmtNum(v)}</span></div>`).join("") +
        `<div class=tc-muted>${s.pos} of ${s.n} members &gt; 0</div>`);
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; hair.setAttribute("visibility", "hidden"); });
    return svg;
  }

  /* -------- phase-space layouts (MJO RMM and GWO) ------------------------- */
  const LAYOUTS = {
    mjo: {
      xLabel: "RMM1", yLabel: "RMM2",
      center: p => -180 + (p - 0.5) * 45,                          // degrees
      phaseOf: (x, y) => (Math.floor((Math.atan2(y, x) * 180 / Math.PI + 180) / 45) % 8) + 1,
      regions: { top: "Western Pacific", bottom: "Indian Ocean", right: "Maritime Continent", left: "Western Hem. and Africa" },
      ampLabel: "Amplitude"
    },
    // Weickmann & Berry GWO: x = AAM anomaly, y = AAM tendency, clockwise orbit;
    // phases 2-3 low AAM (La Nina-like), 4-5 rising, 6-7 high AAM (El Nino-like), 8-1 falling.
    gwo: {
      xLabel: "Relative AAM anomaly (σ)", yLabel: "AAM tendency (σ)",
      center: p => 292.5 - 45 * p,
      phaseOf: (x, y) => { const th = Math.atan2(y, x) * 180 / Math.PI; return Math.floor((((270 - th) % 360) + 360) % 360 / 45) + 1; },
      regions: { top: "AAM rising", bottom: "AAM falling", right: "High AAM (El Niño-like)", left: "Low AAM (La Niña-like)" },
      ampLabel: "Amplitude"
    }
  };

  /* -------- MJO RMM / GWO phase diagram ----------------------------------- */
  function phaseDiagram(container, spec) {
    const W = spec.width || 760;
    const L = 70, R = W - 30, T = 150, B = T + (R - L), H = B + 58;
    const { svg, tip } = makeSvg(container, W, H, spec.title);
    header(svg, { title: spec.title, sub: spec.sub, site: spec.site }, W);
    const lim = spec.lim || 4;
    const LY = LAYOUTS[spec.kind || "mjo"];
    const sx = v => L + (v + lim) / (2 * lim) * (R - L);
    const sy = v => T + (lim - v) / (2 * lim) * (B - T);
    const cx = sx(0), cy = sy(0);
    const g = el("g", {}, svg);
    for (let v = -lim; v <= lim; v++) {
      text(g, sx(v), B + 22, String(v), { "text-anchor": "middle", "font-size": 15 });
      text(g, L - 8, sy(v) + 5, String(v), { "text-anchor": "end", "font-size": 15 });
    }
    text(g, (L + R) / 2, B + 44, LY.xLabel, { "text-anchor": "middle", "font-size": 16 });
    text(g, 18, (T + B) / 2, LY.yLabel, { "text-anchor": "middle", "font-size": 16, transform: `rotate(-90 18 ${(T + B) / 2})` });
    const dot = { stroke: "#8a8a8a", "stroke-dasharray": "3,4", "stroke-width": 1 };
    el("line", Object.assign({ x1: L, x2: R, y1: cy, y2: cy }, dot), g);
    el("line", Object.assign({ x1: cx, x2: cx, y1: T, y2: B }, dot), g);
    el("line", Object.assign({ x1: L, y1: T, x2: sx(-1 / Math.SQRT2), y2: sy(1 / Math.SQRT2) }, dot), g);
    el("line", Object.assign({ x1: sx(1 / Math.SQRT2), y1: sy(-1 / Math.SQRT2), x2: R, y2: B }, dot), g);
    el("line", Object.assign({ x1: R, y1: T, x2: sx(1 / Math.SQRT2), y2: sy(1 / Math.SQRT2) }, dot), g);
    el("line", Object.assign({ x1: sx(-1 / Math.SQRT2), y1: sy(-1 / Math.SQRT2), x2: L, y2: B }, dot), g);
    el("circle", { cx, cy, r: sx(1) - cx, fill: "#ececec", stroke: "#555", "stroke-width": 1.2 }, g);
    // phase numbers at the octants, region names on the sides
    for (let p = 1; p <= 8; p++) {
      const ang = LY.center(p) * Math.PI / 180, rr = lim * 0.86;
      text(g, sx(rr * Math.cos(ang)), sy(rr * Math.sin(ang)) + 8, String(p), { "text-anchor": "middle", "font-size": 24, "font-weight": 700, fill: "#9b9b9b" });
    }
    const reg = { "font-size": 17, fill: "#444", "text-anchor": "middle", "font-style": "italic" };
    text(g, (L + R) / 2, T + 24, LY.regions.top, reg);
    text(g, (L + R) / 2, B - 10, LY.regions.bottom, reg);
    text(g, R - 12, (T + B) / 2, LY.regions.right, Object.assign({ transform: `rotate(90 ${R - 12} ${(T + B) / 2})` }, reg));
    text(g, L + 18, (T + B) / 2, LY.regions.left, Object.assign({ transform: `rotate(-90 ${L + 18} ${(T + B) / 2})` }, reg));
    el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "none", stroke: "#000", "stroke-width": 2 }, svg);

    const cid = "clip" + Math.random().toString(36).slice(2);
    const cp = el("clipPath", { id: cid }, el("defs", {}, svg));
    el("rect", { x: L, y: T, width: R - L, height: B - T }, cp);
    const plot = el("g", { "clip-path": `url(#${cid})` }, svg);
    const hoverPts = [];
    for (const tr of spec.tracks) {
      const pts = tr.points.filter(p => p.x !== null && p.y !== null && isFinite(p.x) && isFinite(p.y));
      if (pts.length < 1) continue;
      const grp = el("g", { opacity: tr.opacity === undefined ? 1 : tr.opacity }, plot);
      el("path", { d: pts.map((p, i) => (i ? "L" : "M") + sx(p.x).toFixed(1) + "," + sy(p.y).toFixed(1)).join(""), fill: "none", stroke: tr.color, "stroke-width": tr.lw || 2, "stroke-linejoin": "round" }, grp);
      if (tr.ms !== 0) pts.forEach((p, i) => {
        const big = tr.dayMarks && p.lead !== undefined && p.lead % 5 === 0;
        marker(grp, tr.symbol || "circle", tr.filled || big, tr.color, sx(p.x), sy(p.y), big ? (tr.ms || 4) + 1.5 : (tr.ms || 4));
      });
      if (tr.startMark) marker(grp, "square", true, tr.color, sx(pts[0].x), sy(pts[0].y), 6, { stroke: "#000" });
      if (tr.endLabel) {
        const p = pts[pts.length - 1];
        text(grp, sx(p.x) + 8, sy(p.y) - 6, tr.endLabel, { "font-size": 13, fill: tr.color, "font-weight": 700 });
      }
      if (tr.tooltip !== false) pts.forEach(p => hoverPts.push({ tr, p }));
    }
    if (spec.legend) legend(svg, spec.legend, spec.legendX || 380, 72, spec.legendColW || 190, spec.legendPerRow || 2);

    const hit = el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "transparent" }, svg);
    const ring = el("circle", { r: 7, fill: "none", stroke: "#000", "stroke-width": 2, visibility: "hidden", "pointer-events": "none" }, svg);
    hit.addEventListener("mousemove", evt => {
      const pt = svgPoint(svg, evt);
      let best = null, bd = 1e9;
      for (const h of hoverPts) { const d = Math.hypot(sx(h.p.x) - pt.x, sy(h.p.y) - pt.y); if (d < bd) { bd = d; best = h; } }
      if (!best || bd > 25) { tip.style.display = "none"; ring.setAttribute("visibility", "hidden"); return; }
      ring.setAttribute("cx", sx(best.p.x)); ring.setAttribute("cy", sy(best.p.y)); ring.setAttribute("visibility", "visible");
      const d = new Date(best.p.t);
      const amp = Math.hypot(best.p.x, best.p.y);
      const ph = LY.phaseOf(best.p.x, best.p.y);
      placeTip(container, tip, evt, `<b>${best.tr.tipLabel || best.tr.label}</b><div>${pad2(d.getUTCHours())}Z ${pad2(d.getUTCDate())} ${MON[d.getUTCMonth()]}${best.p.lead !== undefined ? ` (day ${best.p.lead})` : ""}</div>` +
        `<div class=tc-row><span class=tc-lab>Phase</span><span class=tc-val>${amp < 1 ? ph + " (weak)" : ph}</span></div>` +
        `<div class=tc-row><span class=tc-lab>Amplitude</span><span class=tc-val>${amp.toFixed(2)}</span></div>` +
        `<div class=tc-row><span class=tc-lab>${LY.xLabel.split(" (")[0].replace("Relative AAM anomaly","AAM")} / ${LY.yLabel.split(" (")[0].replace("AAM tendency","tendency")}</span><span class=tc-val>${best.p.x.toFixed(2)} / ${best.p.y.toFixed(2)}</span></div>`);
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; ring.setAttribute("visibility", "hidden"); });
    return svg;
  }

  /* -------- PNG export ------------------------------------------------------ */
  function exportPNG(svg, filename) {
    const vb = svg.viewBox.baseVal, scale = 2;
    const xml = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = vb.width * scale; c.height = vb.height * scale;
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      const a = document.createElement("a");
      a.download = filename; a.href = c.toDataURL("image/png"); a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }

  window.TeleCharts = { lineChart, boxChart, phaseDiagram, exportPNG, dLabel, MON, DAY, LAYOUTS, el, text, marker, makeSvg, svgPoint, placeTip, legend };
})();
