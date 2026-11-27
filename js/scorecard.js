/* Scorecard tab: how each model's index forecasts have verified against the observed
   (analysis) index, by lead day. Reads data/scorecard.json (pipeline/scorecard.py).
   Exposes window.TeleScore = { render }. */
(function () {
  "use strict";
  const TC = window.TeleCharts, el = TC.el, text = TC.text;
  const INDICES = ["nao", "ao", "pna", "epo", "aam"];
  const METRICS = {
    bias: { label: "Average error (bias)", short: "Bias", desc: "forecast minus observed, averaged. Above zero = the model has been forecasting the index too high at that lead; below = too low.", sym: true },
    mae: { label: "Typical error (mean absolute error)", short: "Typical error", desc: "average size of the miss, ignoring sign. The gray dashed line is persistence (today's value held constant); a model is useful where it stays below it.", sym: false },
    corr: { label: "Correlation with observed", short: "Correlation", desc: "how well the forecasts track the ups and downs (1 = perfectly, 0 = not at all). The gray dashed line is persistence.", sym: false, fixed: [-0.2, 1] }
  };
  const MIN_N = 8;          // fewer pairs than this: drawn faded, not flagged
  const st = { idx: "nao", metric: "bias" };
  const fmt = (v, m) => v == null ? "—" : (m === "corr" ? v.toFixed(2) : (v > 0 && m === "bias" ? "+" : "") + v.toFixed(2));

  async function render(main, ctx) {
    const C = ctx.C;
    main.innerHTML = `<div class="card"><div class="score-ctl">
        <div class="ctl"><span class="lab">Index</span><div class="seg" id="scIdx"></div></div>
        <div class="ctl"><span class="lab">Score</span><div class="seg" id="scMet"></div></div></div>
      <div class="chart" id="scChart"></div><div class="notes" id="scNote"></div></div>
      <div class="card"><div class="score-tabwrap"><table class="score-tab" id="scTab"></table></div><div class="notes" id="scTabNote"></div></div>`;
    let sc = null;
    try { sc = await ctx.getJSON("scorecard.json", true); } catch (e) { sc = null; }
    if (!sc || !sc.models || !Object.keys(sc.models).length) {
      main.innerHTML = `<div class="empty">No scores yet. The scorecard is filled in by each ingest once forecasts start verifying; it needs a day or two of runs for the first lead days and about two weeks for days 10–15.</div>`;
      return;
    }
    const models = Object.keys(C.models).filter(k => sc.models[k]);
    function seg(id, opts, cur, pick) {
      const box = main.querySelector(id); box.innerHTML = "";
      opts.forEach(([v, l]) => { const b = document.createElement("button"); b.textContent = l; b.className = v === cur ? "on" : ""; b.onclick = () => pick(v); box.appendChild(b); });
    }
    function draw() {
      seg("#scIdx", INDICES.map(i => [i, C.indices[i] ? C.indices[i].abbr : i.toUpperCase()]), st.idx, v => { st.idx = v; draw(); });
      seg("#scMet", Object.entries(METRICS).map(([k, m]) => [k, m.short]), st.metric, v => { st.metric = v; draw(); });
      const M = METRICS[st.metric], k = st.idx;
      const maxL = Math.min(sc.max_lead || 16, 15);
      const series = models.map(m => ({ m, md: C.models[m], pts: [...Array(maxL)].map((_, i) => { const s = (sc.models[m][k] || {})[String(i + 1)]; return s ? { L: i + 1, v: s[st.metric], n: s.n } : null; }).filter(p => p && p.v != null) }));
      const pers = st.metric === "bias" ? [] : [...Array(maxL)].map((_, i) => { const s = (sc.persistence[k] || {})[String(i + 1)]; return s && s[st.metric] != null ? { L: i + 1, v: s[st.metric], n: s.n } : null; }).filter(Boolean);
      chart(main.querySelector("#scChart"), { title: `${C.indices[k] ? C.indices[k].name : k.toUpperCase()} — ${M.label}`,
        sub: `Forecasts verified ${sc.first ? sc.first.slice(4, 6) + "/" + sc.first.slice(6, 8) : "?"}–${sc.last ? sc.last.slice(4, 6) + "/" + sc.last.slice(6, 8) : "?"} · ${sc.runs} runs · updated ${sc.updated.replace("T", " ")}`,
        series, pers, metric: st.metric, maxL });
      main.querySelector("#scNote").innerHTML = `<b>${M.label}:</b> ${M.desc} Lead day 1 = 12–35 h after the start time. Faded points rest on fewer than ${MIN_N} forecasts. ` +
        `Ensembles are scored by their mean, which is naturally smoother, so their typical error is smaller at long leads. The "observed" value is our analysis (GFS), not CPC.`;
      // table
      const leads = [1, 2, 3, 5, 7, 10, 12, 15].filter(L => L <= maxL);
      const flag = (s) => st.metric === "bias" && s && s.n >= MIN_N && Math.abs(s.bias) >= 0.3;
      main.querySelector("#scTab").innerHTML = `<tr><th>${C.indices[k] ? C.indices[k].abbr : k} · ${M.short}</th>${leads.map(L => `<th>Day ${L}</th>`).join("")}</tr>` +
        models.map(m => `<tr><td style="color:${C.models[m].color}">${C.models[m].label}</td>${leads.map(L => {
          const s = (sc.models[m][k] || {})[String(L)];
          return `<td class="${s && s.n < MIN_N ? "few" : ""} ${flag(s) ? "flag" : ""}" title="${s ? s.n + " forecasts" : "no forecasts verified yet"}">${s ? fmt(s[st.metric], st.metric) : "—"}${s ? `<span>n=${s.n}</span>` : ""}</td>`;
        }).join("")}</tr>`).join("") +
        (st.metric !== "bias" ? `<tr class="pers"><td>Persistence</td>${leads.map(L => { const s = (sc.persistence[k] || {})[String(L)]; return `<td>${s ? fmt(s[st.metric], st.metric) : "—"}</td>`; }).join("")}</tr>` : "");
      main.querySelector("#scTabNote").innerHTML = st.metric === "bias"
        ? `Highlighted: a bias of 0.3 or more from at least ${MIN_N} forecasts. A bias that stays the same sign across several lead days and keeps showing up week after week is a candidate for correction; one that flips around is just this period's weather.`
        : `n = number of forecasts verified at that lead.`;
    }
    draw();
  }

  function chart(box, s) {
    const W = 1200, H = 470, L = 70, R = W - 30, T = 100, B = H - 56;
    const { svg, tip } = TC.makeSvg(box, W, H, s.title);
    el("rect", { x: 14, y: 8, width: 5, height: 42, rx: 2, fill: "#14243a" }, svg);
    text(svg, 28, 26, s.title, { "font-size": 19, "font-weight": 700, fill: "#1f2933" });
    text(svg, 28, 46, s.sub, { "font-size": 14, fill: "#5f6b7a" });
    // y range
    const vals = s.series.flatMap(x => x.pts.map(p => p.v)).concat(s.pers.map(p => p.v));
    let y0, y1;
    if (METRICS[s.metric].fixed) [y0, y1] = METRICS[s.metric].fixed;
    else if (METRICS[s.metric].sym) { const a = Math.max(0.5, Math.ceil(Math.max(0, ...vals.map(Math.abs)) * 4) / 4); y0 = -a; y1 = a; }
    else { y0 = 0; y1 = Math.max(0.5, Math.ceil(Math.max(0, ...vals) * 4) / 4); }
    const sx = l => L + (l - 0.5) / s.maxL * (R - L), sy = v => T + (y1 - v) / (y1 - y0) * (B - T);
    el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "#fbfcfd" }, svg);
    const step = (y1 - y0) > 3 ? 1 : (y1 - y0) > 1.2 ? 0.5 : 0.25;
    for (let v = Math.ceil(y0 / step) * step; v <= y1 + 1e-9; v += step) {
      el("line", { x1: L, x2: R, y1: sy(v), y2: sy(v), stroke: Math.abs(v) < 1e-9 ? "#475569" : "#e3e8ee", "stroke-width": Math.abs(v) < 1e-9 ? 1.6 : 1 }, svg);
      text(svg, L - 8, sy(v) + 5, (s.metric === "bias" && v > 0 ? "+" : "") + (+v.toFixed(2)), { "font-size": 13.5, "text-anchor": "end", fill: "#5f6b7a" });
    }
    if (s.metric === "bias") for (const b of [0.3, -0.3]) if (b > y0 && b < y1) el("line", { x1: L, x2: R, y1: sy(b), y2: sy(b), stroke: "#e8590c", "stroke-dasharray": "3,5", opacity: 0.6 }, svg);
    for (let l = 1; l <= s.maxL; l++) {
      el("line", { x1: sx(l), x2: sx(l), y1: B, y2: B + 4, stroke: "#b8c2cc" }, svg);
      text(svg, sx(l), B + 20, String(l), { "font-size": 13.5, "text-anchor": "middle", fill: "#1f2933" });
    }
    text(svg, (L + R) / 2, B + 42, "lead time (days)", { "font-size": 13.5, "text-anchor": "middle", fill: "#5f6b7a" });
    const line = (pts, attrs) => { const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.L).toFixed(1)},${sy(p.v).toFixed(1)}`).join(""); if (pts.length > 1) el("path", Object.assign({ d, fill: "none" }, attrs), svg); };
    if (s.pers.length) line(s.pers, { stroke: "#8a96a3", "stroke-width": 2, "stroke-dasharray": "6,5" });
    const hits = [];
    for (const x of s.series) {
      line(x.pts, { stroke: x.md.color, "stroke-width": 2 });
      for (const p of x.pts) {
        marker(svg, x.md, sx(p.L), sy(p.v), p.n < MIN_N ? 0.35 : 1);
        hits.push({ x: sx(p.L), y: sy(p.v), html: `<b>${x.md.label}</b> · day ${p.L}<div>${METRICS[s.metric].short}: ${fmt(p.v, s.metric)}</div><div>${p.n} forecasts</div>` });
      }
    }
    for (const p of s.pers) hits.push({ x: sx(p.L), y: sy(p.v), html: `<b>Persistence</b> · day ${p.L}<div>${fmt(p.v, s.metric)}</div><div>${p.n} cases</div>` });
    el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "none", stroke: "#b8c2cc" }, svg);
    // legend
    const items = s.series.map(x => ({ label: x.md.label, color: x.md.color, symbol: x.md.symbol, filled: x.md.filled }));
    TC.legend(svg, items, 600, 17, 200, 3);
    if (s.pers.length) { el("line", { x1: 28, x2: 52, y1: 72, y2: 72, stroke: "#8a96a3", "stroke-width": 2, "stroke-dasharray": "6,5" }, svg); text(svg, 58, 77, "Persistence (no-skill reference)", { "font-size": 13.5, fill: "#1f2933" }); }
    if (s.metric === "bias") text(svg, 28, 77, "Dashed orange: ±0.3, the level worth watching", { "font-size": 13, fill: "#5f6b7a" });
    svg.addEventListener("mousemove", e => {
      const p = TC.svgPoint(svg, e); let best = null, bd = 400;
      for (const h of hits) { const d = (h.x - p.x) ** 2 + (h.y - p.y) ** 2; if (d < bd) { bd = d; best = h; } }
      if (!best) { tip.style.display = "none"; return; }
      TC.placeTip(box, tip, e, best.html);
    });
    svg.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  }
  function marker(svg, md, x, y, op) { TC.marker(svg, md.symbol, md.filled, md.color, x, y, 5, { opacity: op }); }

  window.TeleScore = { render };
})();
