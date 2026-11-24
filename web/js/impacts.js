/* "What this means for the US" panels: 1991-2020 composites of US temperature and
   precipitation after MJO / GWO phases, Bering Sea troughs and ridges, and typhoons that
   recurved near Japan. Reads data/composites/index.json and <product>_<MM>.json written
   by pipeline/build_composites.py.
   Exposes window.TeleImpacts = { panel, beringIndex, doyIndex }. */
(function () {
  "use strict";
  const TC = window.TeleCharts, TM = window.TeleMaps, el = TC.el, text = TC.text, DAY = TC.DAY, MON = TC.MON;
  const D2R = Math.PI / 180;
  const LS = "telemon.impacts";
  const BOUNDS = { latN: 50, latS: 24, lonW: 235, lonE: 294 };
  const DEFAULT_WIN = { mjo: 1, gwo: 1, bsr: 2, tr: 1 };
  const CAT_LABEL = { mjo: "Phase", gwo: "Phase", bsr: "Pattern", tr: "Signal" };
  const pad2 = n => String(n).padStart(2, "0");
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtDay = t => { const d = new Date(t); return `${d.getUTCDate()} ${MON[d.getUTCMonth()].charAt(0)}${MON[d.getUTCMonth()].slice(1).toLowerCase()}`; };

  const saved = (() => { try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch (e) { return {}; } })();
  const save = () => { try { localStorage.setItem(LS, JSON.stringify(saved)); } catch (e) { /* storage off */ } };
  const touched = {};                 // choices made by hand this visit (stop following the live signal)
  const files = {};
  let indexP = null;

  function getIndex(ctx) {
    if (!indexP) indexP = ctx.getJSON("composites/index.json", true).catch(() => null);
    return indexP;
  }
  function getFile(ctx, prod, m) {
    const k = `${prod}_${pad2(m)}`;
    if (!files[k]) files[k] = ctx.getJSON(`composites/${k}.json`).catch(() => null);
    return files[k];
  }
  // day index 0..365 on a leap-year calendar (matches the pipeline's cal_index)
  function doyIndex(t) { const d = new Date(t); return Math.round((Date.UTC(2000, d.getUTCMonth(), d.getUTCDate()) - Date.UTC(2000, 0, 1)) / DAY); }

  /* ---------- grid helpers ------------------------------------------------- */
  function hexBits(h, n) {
    const out = new Array(n).fill(false); let k = 0;
    for (const ch of h || "") { const v = parseInt(ch, 16); for (let b = 3; b >= 0; b--) { if (k < n) out[k] = !!((v >> b) & 1); k++; } }
    return out;
  }
  function gridInfo(ix) {
    if (ix._g) return ix._g;
    const g = ix.grid, n = g.nrows * g.ncols, mask = hexBits(ix.cells, n), cells = [];
    mask.forEach((m, i) => { if (m) cells.push(i); });
    const regionCells = {};
    for (const r of ix.regions) {
      regionCells[r.key] = [];
      cells.forEach((ci, k) => {
        const lat = g.lat_n - Math.floor(ci / g.ncols) * g.res, lon = g.lon_w + (ci % g.ncols) * g.res;
        if (lat >= r.lat[0] && lat <= r.lat[1] && lon >= r.lon[0] && lon <= r.lon[1]) regionCells[r.key].push(k);
      });
    }
    return (ix._g = { meta: Object.assign({}, g), n, cells, regionCells });
  }
  function toFull(G, vals, scale) {
    const out = new Array(G.n).fill(null);
    if (vals) G.cells.forEach((ci, k) => { const v = vals[k]; out[ci] = v == null ? null : v * scale; });
    return out;
  }
  function dilate(a, nr, nc, passes) {
    for (let p = 0; p < passes; p++) {
      const b = a.slice();
      for (let r = 0; r < nr; r++) for (let c = 0; c < nc; c++) {
        const i = r * nc + c; if (a[i] != null) continue;
        let s = 0, n = 0;
        for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
          const rr = r + dr, cc = c + dc; if (rr < 0 || cc < 0 || rr >= nr || cc >= nc) continue;
          const v = a[rr * nc + cc]; if (v != null) { s += v; n++; }
        }
        if (n) b[i] = s / n;
      }
      a = b;
    }
    return a;
  }
  const mean = a => { const v = a.filter(x => x != null && isFinite(x)); return v.length ? v.reduce((p, q) => p + q, 0) / v.length : null; };

  /* ---------- fields and colors ---------------------------------------------- */
  const BRBG = [[140, 81, 10], [191, 129, 45], [223, 194, 125], [246, 232, 195], [245, 245, 245], [199, 234, 229], [128, 205, 193], [53, 151, 143], [1, 102, 94]];
  function brbg(v, lim) {
    const t = Math.max(-1, Math.min(1, v / lim)) * 4 + 4, i = Math.min(7, Math.floor(t)), f = t - i, a = BRBG[i], b = BRBG[i + 1];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }
  const FIELDS = {
    t: { label: "Temperature anomaly", short: "Temperature", key: "t", sig: "ts", scale: 0.1, center: 0, lim: 5,
      color: v => TM.divColor(v, 5), fmt: v => v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "°F", ticks: [-5, -2.5, 0, 2.5, 5], tick: v => (v > 0 ? "+" : "") + v + "°F" },
    w: { label: "% of cases warmer than normal", short: "% warm", key: "w", sig: "ts", scale: 1, center: 50, lim: 30,
      color: v => TM.divColor(v - 50, 30), fmt: v => v == null ? "—" : Math.round(v) + "%", ticks: [20, 35, 50, 65, 80], tick: v => v + "%" },
    p: { label: "Precipitation, % of normal", short: "Precipitation", key: "p", sig: "ps", scale: 1, center: 100, lim: 60,
      color: v => brbg(v - 100, 60), fmt: v => v == null ? "—" : Math.round(v) + "%", ticks: [40, 70, 100, 130, 160], tick: v => v + "%" }
  };
  const rgb = c => `rgb(${c.map(Math.round).join(",")})`;
  const soft = c => rgb(c.map(v => v + (255 - v) * 0.45));

  /* ---------- text ------------------------------------------------------------- */
  const ABOUT = {
    mjo: `The Madden–Julian Oscillation is an eastward-moving envelope of enhanced and suppressed tropical rainfall that circles the globe in roughly 30–60 days. Its heating shifts the Pacific jet and sends wave trains into North America, so US effects are strongest in the cool season and usually lag the tropical phase by one to three weeks — compare the "days after" windows. Days with RMM amplitude below 1 (inside the circle) are not used.`,
    gwo: `The Global Wind Oscillation (Weickmann &amp; Berry) follows global relative atmospheric angular momentum (AAM) and its tendency. Phases 2–3 are low AAM (La Niña-like, retracted Pacific jet), 4–5 AAM rising, 6–7 high AAM (El Niño-like, extended Pacific jet), 8–1 AAM falling. Because it includes mid-latitude processes such as mountain torques, it can carry a signal when the MJO is weak. Days with GWO amplitude below 1 are not used.`,
    bsr: `Bering Sea Rule (J. Renken): the 500 mb pattern over the Bering Sea and Aleutians tends to recur over the central and eastern US about 17–21 days later. Here a "Bering trough" day is a 500 mb height anomaly averaged over 50–65N, 165E–160W at least one standard deviation below normal, and a "ridge" day at least one above. The maps show what the US actually did after those days, so you can see where — and in which seasons — the rule has held.`,
    tr: `Typhoon Rule (J. Renken): a typhoon that recurves near Japan tends to be followed by a trough over the eastern US about 6–10 days later, sometimes with ridging just before. Day 0 is the recurvature date of each West Pacific storm of at least 64 kt that recurved near Japan — the same test as the table above — so cases are few outside late summer and fall.`
  };
  const LINKS = {
    mjo: [["https://www.meteonetwork.it/models/mjo/", "MeteoNetwork MJO page"], ["https://www.cpc.ncep.noaa.gov/products/precip/CWlink/MJO/mjo.shtml", "CPC MJO monitoring and composites"]],
    gwo: [["https://psl.noaa.gov/map/clim/wb08_revised_final.pdf", "Weickmann &amp; Berry: The MJO and the Global Wind Oscillation (PDF)"]],
    bsr: [], tr: []
  };
  function methodHtml(ix) {
    return `<p><b>How these are made.</b> For every day from ${ix.period[0]}–${ix.period[1]} on which the signal occurred in the selected 3-month season, the page averages what the contiguous US did over the chosen days afterwards. Temperature is the departure from the ${ix.period[0]}–${ix.period[1]} daily normal (°F); "% of cases" is the share of signal days followed by above-normal temperature (50% = no tendency); precipitation is the total for the window as a percent of normal (left blank where normal is under 0.3 mm/day). Dots mark where the departure is statistically significant at about 95% (t-test that counts each separate event once). Maps are lightly smoothed; data are CPC Global Unified daily temperature and precipitation on a 1° grid.</p>
      <p><b>Use with care.</b> These are averages over many cases. Individual events vary, and ENSO, the NAO/AO or other patterns can overwhelm the signal. Values near 0°F or 50% mean the signal says little for that area.</p>`;
  }

  /* ---------- map ------------------------------------------------------------------- */
  const merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * D2R / 2));
  function usMap(container, s) {
    const W = 760, L = 8, T = 58, MW = W - 16;
    const MH = Math.round(MW * (merc(BOUNDS.latN) - merc(BOUNDS.latS)) / ((BOUNDS.lonE - BOUNDS.lonW) * D2R));
    const H = T + MH + 50;
    const { svg, tip } = TC.makeSvg(container, W, H, s.title);
    const pr = TM.projection(BOUNDS, L, T, MW, MH);
    text(svg, 10, 22, s.title, { "font-size": 17, "font-weight": 700 });
    text(svg, 10, 44, s.sub, { "font-size": 13.5, fill: "#444" });
    const cid = "usclip" + Math.random().toString(36).slice(2);
    let d = "";
    for (const ring of s.us.states) {
      for (let i = 0; i < ring.length; i += 2) d += (i ? "L" : "M") + pr.x(ring[i] < 0 ? ring[i] + 360 : ring[i]).toFixed(1) + "," + pr.y(ring[i + 1]).toFixed(1);
      d += "Z";
    }
    el("path", { d }, el("clipPath", { id: cid }, el("defs", {}, svg)));
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "#eef1f4" }, svg);
    const g = el("g", { "clip-path": `url(#${cid})` }, svg);
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "#fff" }, g);
    if (s.sample) TM.fillImage(g, pr, s.sample, 1, v => s.field.color(v));
    if (s.dots) for (const p of s.dots) el("circle", { cx: pr.x(p[1]).toFixed(1), cy: pr.y(p[0]).toFixed(1), r: 1.4, fill: "#1b1b1b", opacity: 0.55 }, g);
    const fid = cid + "f";
    el("rect", { x: L, y: T, width: MW, height: MH }, el("clipPath", { id: fid }, el("defs", {}, svg)));
    const lines = el("g", { "clip-path": `url(#${fid})` }, svg);
    if (s.us.context) TM.drawLines(lines, s.us.context, pr, { stroke: "#9aa3ad", "stroke-width": 0.8 }, false, MW * 0.3);
    TM.drawLines(lines, s.us.states, pr, { stroke: "#3a3a3a", "stroke-width": 0.7, "stroke-linejoin": "round" }, false, MW * 0.3);
    if (s.home) {
      const x = pr.x(s.home.lon < 0 ? s.home.lon + 360 : s.home.lon), y = pr.y(s.home.lat);
      el("circle", { cx: x, cy: y, r: 5, fill: "#fff", stroke: "#000", "stroke-width": 2 }, svg);
      el("circle", { cx: x, cy: y, r: 1.8, fill: "#000" }, svg);
    }
    if (s.message) {
      el("rect", { x: W / 2 - 230, y: T + MH / 2 - 26, width: 460, height: 44, rx: 5, fill: "#fff", stroke: "#999", opacity: 0.95 }, svg);
      text(svg, W / 2, T + MH / 2 + 2, s.message, { "font-size": 15, "text-anchor": "middle", fill: "#333" });
    }
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "none", stroke: "#000", "stroke-width": 1.2 }, svg);
    // color key
    const f = s.field, kx = W / 2 - 200, ky = T + MH + 14, kw = 400, n = 40;
    for (let i = 0; i < n; i++) {
      const v = f.center - f.lim + (i + 0.5) / n * 2 * f.lim;
      el("rect", { x: kx + i * kw / n, y: ky, width: kw / n + 0.5, height: 11, fill: rgb(f.color(v)) }, svg);
    }
    el("rect", { x: kx, y: ky, width: kw, height: 11, fill: "none", stroke: "#666", "stroke-width": 0.6 }, svg);
    for (const v of f.ticks) {
      const x = kx + (v - (f.center - f.lim)) / (2 * f.lim) * kw;
      el("line", { x1: x, x2: x, y1: ky + 11, y2: ky + 15, stroke: "#333" }, svg);
      text(svg, x, ky + 28, f.tick(v), { "font-size": 11.5, "text-anchor": "middle", fill: "#333" });
    }
    text(svg, kx - 8, ky + 10, f.short, { "font-size": 12, "text-anchor": "end", fill: "#333" });
    if (s.dots) { el("circle", { cx: kx + kw + 16, cy: ky + 6, r: 1.6, fill: "#1b1b1b" }, svg); text(svg, kx + kw + 22, ky + 10, "significant", { "font-size": 11.5, fill: "#333" }); }
    // hover / click
    const inMap = p => p.x >= L && p.x <= L + MW && p.y >= T && p.y <= T + MH;
    svg.addEventListener("mousemove", e => {
      const p = TC.svgPoint(svg, e);
      if (!inMap(p) || !s.hover) { tip.style.display = "none"; return; }
      const html = s.hover(pr.lat(p.y), pr.lon(p.x));
      if (!html) { tip.style.display = "none"; return; }
      TC.placeTip(container, tip, e, html);
    });
    svg.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    if (s.onClick) svg.addEventListener("click", e => { const p = TC.svgPoint(svg, e); if (inMap(p)) s.onClick(pr.lat(p.y), pr.lon(p.x)); });
    svg.style.cursor = s.onClick ? "crosshair" : "";
    return { svg, pr };
  }

  /* ---------- lag curve ------------------------------------------------------------- */
  function lagCurve(container, s) {
    const W = 420, H = 250, L = 46, R = W - 12, T = 52, B = H - 36;
    const { svg, tip } = TC.makeSvg(container, W, H, s.title);
    text(svg, 8, 20, s.title, { "font-size": 14.5, "font-weight": 700 });
    text(svg, 8, 39, s.sub, { "font-size": 12, fill: "#555" });
    const v = s.t.map(x => x == null ? null : x / 10), n = v.length;
    const lim = Math.max(2, Math.ceil(Math.max(...v.filter(x => x != null).map(Math.abs), 0)));
    const sx = i => L + (i + 0.5) / n * (R - L), sy = y => T + (lim - y) / (2 * lim) * (B - T), bw = (R - L) / n * 0.78;
    const [a, b] = s.window;
    el("rect", { x: sx(a) - (R - L) / n / 2, y: T, width: (b - a + 1) * (R - L) / n, height: B - T, fill: "#ffe9a8", opacity: 0.6 }, svg);
    for (let y = -lim; y <= lim; y += lim > 4 ? 2 : 1) {
      el("line", { x1: L, x2: R, y1: sy(y), y2: sy(y), stroke: y ? "#ccc" : "#000", "stroke-width": y ? 1 : 1.4, "stroke-dasharray": y ? "2,4" : null }, svg);
      text(svg, L - 6, sy(y) + 4, (y > 0 ? "+" : "") + y, { "font-size": 11.5, "text-anchor": "end" });
    }
    v.forEach((y, i) => {
      if (y == null) return;
      el("rect", { x: sx(i) - bw / 2, y: Math.min(sy(y), sy(0)), width: bw, height: Math.max(0.8, Math.abs(sy(y) - sy(0))), fill: rgb(TM.divColor(y, 4)), stroke: "#555", "stroke-width": 0.4 }, svg);
    });
    for (let i = 0; i < n; i += 5) text(svg, sx(i), B + 15, String(i), { "font-size": 11.5, "text-anchor": "middle" });
    text(svg, (L + R) / 2, B + 31, "days after the signal", { "font-size": 11.5, "text-anchor": "middle", fill: "#444" });
    text(svg, 12, (T + B) / 2, "°F", { "font-size": 12, "text-anchor": "middle" });
    el("rect", { x: L, y: T, width: R - L, height: B - T, fill: "none", stroke: "#000" }, svg);
    svg.addEventListener("mousemove", e => {
      const p = TC.svgPoint(svg, e), i = Math.floor((p.x - L) / (R - L) * n);
      if (i < 0 || i >= n || p.y < T || p.y > B || v[i] == null) { tip.style.display = "none"; return; }
      TC.placeTip(container, tip, e, `<b>Day ${i}</b> (5-day mean, days ${Math.max(0, i - 2)}–${i + 2})<div>${FIELDS.t.fmt(v[i])}</div><div>${s.w[i]}% of cases warmer than normal</div>`);
    });
    svg.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  }

  /* ---------- panel ------------------------------------------------------------------ */
  async function panel(box, opt) {
    const ctx = opt.ctx, prod = opt.product, C = ctx.C;
    const home = Object.assign({ name: "Jackson, KY", lat: 37.59, lon: -83.32 }, C.home || {});
    box.innerHTML = `<div class="card imp"><div class="imp-title">What this means for the US</div><div class="imp-body">Loading composites…</div></div>`;
    const body = box.querySelector(".imp-body");
    const [ix, us] = await Promise.all([getIndex(ctx), opt.us || fetch("geo/us.json").then(r => r.json()).catch(() => null)]);
    const P = ix && ix.products && ix.products[prod];
    if (!P || !us) {
      body.innerHTML = `<div class="empty">The US composites have not been built yet. Run the <b>Setup (run once)</b> workflow (Actions tab); it builds them in about 20–40 minutes and they appear here afterwards.</div>
        <p class="imp-about-p">${ABOUT[prod]}</p>${linksHtml(prod)}`;
      return;
    }
    const G = gridInfo(ix);
    const st = saved[prod] = Object.assign({ m: new Date().getUTCMonth() + 1, cat: 0, win: DEFAULT_WIN[prod], field: "t", region: "eky" }, saved[prod] || {});
    if (!touched[prod + "m"]) st.m = opt.month || new Date().getUTCMonth() + 1;
    if (!touched[prod + "cat"] && opt.defaultCat != null) st.cat = opt.defaultCat;
    st.cat = Math.min(st.cat, P.cats.length - 1); st.win = Math.min(st.win, P.windows.length - 1);
    let point = null;                                    // clicked point (null = home)
    const catShort = i => prod === "mjo" || prod === "gwo" ? String(i + 1) : P.cats[i].replace("Bering ", "").replace(/^./, c => c.toUpperCase());

    body.innerHTML = `
      <div class="imp-ctl">
        <div class="ctl"><span class="lab">Season</span><select class="impSeason">${ix.seasons.map(s => `<option value="${s.m}">${s.label} (centered on ${MON[s.m - 1].charAt(0)}${MON[s.m - 1].slice(1).toLowerCase()})</option>`).join("")}</select></div>
        <div class="ctl" ${P.cats.length < 2 ? "hidden" : ""}><span class="lab">${CAT_LABEL[prod]}</span><div class="seg impCat"></div></div>
        <div class="ctl"><span class="lab">Days after</span><div class="seg impWin"></div></div>
        <div class="ctl"><span class="lab">Show</span><div class="seg impField"></div></div>
      </div>
      ${opt.signals && opt.signals.length ? `<div class="imp-sigs"><div class="lab">Now and in the forecasts — click a cell to show its composite</div><table class="imp-sigtab"></table><div class="tc-muted imp-signote"></div></div>` : ""}
      <div class="imp-grid">
        <div class="chart impMap"></div>
        <div class="imp-side"><table class="imp-tab"></table><div class="chart impCurve"></div></div>
      </div>
      <div class="imp-sum"></div>
      <details class="imp-about"><summary>About this signal and how the composites are made</summary><p>${ABOUT[prod]}</p>${methodHtml(ix)}${linksHtml(prod)}</details>`;
    const $ = s => body.querySelector(s);
    $(".impSeason").value = st.m;
    $(".impSeason").onchange = e => { st.m = +e.target.value; touched[prod + "m"] = true; save(); draw(); };

    function seg(sel, opts, cur, pick) {
      const b = $(sel); b.innerHTML = "";
      opts.forEach(([v, lab, title]) => { const x = document.createElement("button"); x.textContent = lab; if (title) x.title = title; x.className = v === cur ? "on" : ""; x.onclick = () => pick(v); b.appendChild(x); });
    }
    function controls() {
      seg(".impCat", P.cats.map((c, i) => [i, catShort(i), c]), st.cat, v => { st.cat = v; touched[prod + "cat"] = true; save(); draw(); });
      seg(".impWin", P.windows.map((w, i) => [i, `${w[0]}–${w[1]}`]), st.win, v => { st.win = v; save(); draw(); });
      seg(".impField", [["t", "Temperature"], ["w", "% warm cases"], ["p", "Precipitation"]], st.field, v => { st.field = v; save(); draw(); });
    }

    async function draw() {
      controls();
      const file = await getFile(ctx, prod, st.m);
      const season = ix.seasons.find(s => s.m === st.m).label;
      const c = file && file.cats[st.cat], f = FIELDS[st.field], w = P.windows[st.win];
      const title = `${P.name} — ${P.cats[st.cat]} · ${season} · days ${w[0]}–${w[1]} after`;
      if (!c || c.few) {
        usMap($(".impMap"), { title, sub: f.label, field: f, us, home,
          message: !file ? "Composite file missing" : `Only ${c.events} separate event${c.events === 1 ? "" : "s"} in ${season} — too few to average` });
        $(".imp-tab").innerHTML = ""; $(".impCurve").innerHTML = ""; $(".imp-sum").textContent = "";
        signals(file);
        return;
      }
      const grids = {}, raw = {};
      for (const k of ["t", "w", "p"]) { raw[k] = toFull(G, c[k][st.win], FIELDS[k].scale); grids[k] = TM.gridSampler(G.meta, dilate(raw[k], G.meta.nrows, G.meta.ncols, 3)); }
      const sig = hexBits(c[f.sig][st.win], G.cells.length);
      const dots = [];
      G.cells.forEach((ci, k) => { if (sig[k]) dots.push([G.meta.lat_n - Math.floor(ci / G.meta.ncols) * G.meta.res, G.meta.lon_w + (ci % G.meta.ncols) * G.meta.res]); });
      const at = (k, lat, lon) => { const v = grids[k](lat, lon < 0 ? lon + 360 : lon); return v == null ? null : v; };
      const pt = point || home;
      usMap($(".impMap"), {
        title, sub: `${f.label} · ${c.n} days in ${c.events} separate events, ${ix.period[0]}–${ix.period[1]}${c.events < 15 ? " · small sample" : ""}`,
        field: f, us, home: pt, sample: grids[st.field], dots,
        hover: (lat, lon) => {
          const t = at("t", lat, lon); if (t == null) return null;
          return `<b>${lat.toFixed(1)}N ${(360 - lon).toFixed(1)}W</b><div>Temperature ${FIELDS.t.fmt(t)}</div><div>${FIELDS.w.fmt(at("w", lat, lon))} of cases warmer than normal</div><div>Precipitation ${FIELDS.p.fmt(at("p", lat, lon))} of normal</div><div class="tc-muted">Click to read out this point</div>`;
        },
        onClick: (lat, lon) => { point = { name: `${lat.toFixed(1)}N ${(360 - lon).toFixed(1)}W`, lat, lon: lon - 360 }; draw(); }
      });
      // region table
      const rows = ix.regions.map(r => {
        const ks = G.regionCells[r.key];
        const avg = k => mean(ks.map(j => { const v = c[k][st.win][j]; return v == null ? null : v * FIELDS[k].scale; }));
        return { r, t: avg("t"), w: avg("w"), p: avg("p") };
      });
      const ptRow = { r: { key: "_pt", name: pt.name }, t: at("t", pt.lat, pt.lon), w: at("w", pt.lat, pt.lon), p: at("p", pt.lat, pt.lon) };
      const cellBg = (k, v) => v == null ? "" : `style="background:${soft(FIELDS[k].color(v))}"`;
      $(".imp-tab").innerHTML = `<tr><th></th><th>Temp</th><th>% warm</th><th>Precip</th></tr>` +
        [ptRow].concat(rows).map(x => `<tr class="${x.r.key === st.region ? "on" : ""} ${x.r.key === "_pt" ? "pt" : ""}" data-k="${x.r.key}"><td>${x.r.key === "_pt" ? "◉ " : ""}${esc(x.r.name)}</td><td ${cellBg("t", x.t)}>${FIELDS.t.fmt(x.t)}</td><td ${cellBg("w", x.w)}>${FIELDS.w.fmt(x.w)}</td><td ${cellBg("p", x.p)}>${FIELDS.p.fmt(x.p)}</td></tr>`).join("") +
        (point ? `<tr><td colspan="4"><a href="#" class="impHome">Back to ${esc(home.name)}</a></td></tr>` : "");
      body.querySelectorAll(".imp-tab tr[data-k]").forEach(tr => { if (tr.dataset.k !== "_pt") tr.onclick = () => { st.region = tr.dataset.k; save(); draw(); }; });
      const hb = body.querySelector(".impHome"); if (hb) hb.onclick = e => { e.preventDefault(); point = null; draw(); };
      const reg = ix.regions.find(r => r.key === st.region) || ix.regions[0];
      const cv = c.curves && c.curves[reg.key];
      if (cv) lagCurve($(".impCurve"), { title: `${reg.name}: temperature after ${P.cats[st.cat].replace("Bering ", "a Bering ").replace("Recurving typhoon near Japan", "recurvature")}`, sub: `${season} · 5-day mean anomaly · shaded = selected days`, t: cv.t, w: cv.w, window: w });
      $(".imp-sum").innerHTML = summary(rows, ptRow, c, season);
      signals(file);
    }

    function summary(rows, ptRow, c, season) {
      const f = st.field === "p" ? "p" : "t";
      const ok = rows.filter(x => x[f] != null);
      const hiT = st.field === "p" ? 110 : 0.75, loT = st.field === "p" ? 90 : -0.75;
      const desc = x => f === "p" ? `${x.r.name} (${FIELDS.p.fmt(x.p)} of normal)` : `${x.r.name} (${FIELDS.t.fmt(x.t)}, ${FIELDS.w.fmt(x.w)} warm)`;
      const hi = ok.filter(x => x[f] >= hiT).sort((a, b) => b[f] - a[f]).slice(0, 3), lo = ok.filter(x => x[f] <= loT).sort((a, b) => a[f] - b[f]).slice(0, 3);
      const words = f === "p" ? ["Wetter than normal", "Drier than normal"] : ["Warmest", "Coldest"];
      let s = "";
      if (hi.length) s += `<b>${words[0]}:</b> ${hi.map(desc).join(", ")}. `;
      if (lo.length) s += `<b>${words[1]}:</b> ${lo.map(desc).join(", ")}. `;
      if (!hi.length && !lo.length) s += f === "p" ? "No region departs much from normal precipitation (all within 90–110%). " : "No strong temperature signal: every region is within ±0.75°F of normal. ";
      s += `<b>${esc(ptRow.r.name)}:</b> ${FIELDS.t.fmt(ptRow.t)}, ${FIELDS.w.fmt(ptRow.w)} of cases warm, precipitation ${FIELDS.p.fmt(ptRow.p)} of normal.`;
      if (c.events < 15) s += ` <span class="warn">Only ${c.events} separate events in ${season} — treat as a rough guide.</span>`;
      return s;
    }

    // "now and forecast" table; cells colored by the composite temperature at the readout point
    function signals(file) {
      const tab = $(".imp-sigtab"); if (!tab) return;
      const pt = point || home;
      const tAt = cat => {
        const c = file && file.cats[cat]; if (!c || c.few) return null;
        return TM.gridSampler(G.meta, dilate(toFull(G, c.t[st.win], 0.1), G.meta.nrows, G.meta.ncols, 3))(pt.lat, pt.lon < 0 ? pt.lon + 360 : pt.lon);
      };
      const memo = {};
      tab.innerHTML = opt.signals.map((row, ri) => `<tr><th style="color:${row.color || "#222"}">${esc(row.label)}</th>${row.cells.map((cell, ci) => {
        let style = "", title = "";
        if (cell.cat != null) {
          if (!(cell.cat in memo)) memo[cell.cat] = tAt(cell.cat);
          const v = memo[cell.cat];
          if (v != null) { style = `background:${soft(FIELDS.t.color(v))}`; title = `${P.cats[cell.cat]}: ${pt.name} ${FIELDS.t.fmt(v)} on average, days ${P.windows[st.win][0]}–${P.windows[st.win][1]} after (${ix.seasons.find(s => s.m === st.m).label})`; }
        }
        return `<td class="${cell.cat != null ? "pick" : "weak"} ${cell.cat === st.cat && cell.cat != null ? "on" : ""}" data-r="${ri}" data-c="${ci}" style="${style}" title="${esc(title)}"><span>${esc(cell.head || "")}</span><b>${esc(cell.text || "")}</b></td>`;
      }).join("")}</tr>`).join("");
      tab.querySelectorAll("td.pick").forEach(td => td.onclick = () => {
        const cell = opt.signals[+td.dataset.r].cells[+td.dataset.c];
        st.cat = cell.cat; touched[prod + "cat"] = true; save(); draw();
      });
      const note = $(".imp-signote");
      if (note) note.textContent = `Cell color = average ${ix.seasons.find(s => s.m === st.m).label} temperature at ${pt.name} ${P.windows[st.win][0]}–${P.windows[st.win][1]} days after that ${prod === "mjo" || prod === "gwo" ? "phase" : "signal"}. ${opt.signalNote || ""}`;
    }

    draw();
  }
  function linksHtml(prod) {
    const l = LINKS[prod] || [];
    return l.length ? `<p class="imp-links">${l.map(([u, t]) => `<a href="${u}" target="_blank" rel="noopener">${t}</a>`).join(" · ")}</p>` : "";
  }

  /* ---------- Bering Sea index from the stored North Pacific maps -------------------- */
  // map: one map JSON (2.5 deg, rows N->S from lat_n, cols from lon_w); si: step index.
  function beringIndex(map, si, box) {
    const a = map.z500a && map.z500a[si]; if (!a) return null;
    let s = 0, wsum = 0;
    for (let r = 0; r < map.nrows; r++) {
      const lat = map.lat_n - r * map.res; if (lat < box.lat[0] - 1e-6 || lat > box.lat[1] + 1e-6) continue;
      for (let c = 0; c < map.ncols; c++) {
        const lon = map.lon_w + c * map.res; if (lon < box.lon[0] - 1e-6 || lon > box.lon[1] + 1e-6) continue;
        const v = a[r * map.ncols + c]; if (v == null) continue;
        const w = Math.cos(lat * D2R); s += v * w; wsum += w;
      }
    }
    return wsum ? s / wsum : null;
  }

  window.TeleImpacts = { panel, beringIndex, doyIndex, fmtDay, getIndex };
})();
