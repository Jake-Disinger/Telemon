/* Map rendering for the Bering Sea Rule and Typhoon Rule tabs (no dependencies).
   Exposes window.TeleMaps. Longitudes are degrees east 0..360 on the Pacific maps. */
(function () {
  "use strict";
  const TC = window.TeleCharts, el = TC.el, text = TC.text;
  const R_KM = 6371.0, D2R = Math.PI / 180;

  /* ---------- geometry ------------------------------------------------------ */
  const merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * D2R / 2));
  const imerc = m => (2 * Math.atan(Math.exp(m)) - Math.PI / 2) / D2R;

  function projection(b, L, T, W, H) {
    const m0 = merc(b.latN), m1 = merc(b.latS);
    return {
      x: lon => L + ((((lon - b.lonW) % 360) + 360) % 360) / (b.lonE - b.lonW) * W,
      y: lat => T + (m0 - merc(lat)) / (m0 - m1) * H,
      lon: x => b.lonW + (x - L) / W * (b.lonE - b.lonW),
      lat: y => imerc(m0 - (y - T) / H * (m0 - m1)),
      L, T, W, H, b
    };
  }

  // azimuthal equidistant forward/inverse (km) - used to move the US outline while
  // keeping its true shape and size, as on the classic Bering Sea Rule overlays
  function aeqdF(lat, lon, lat0, lon0) {
    const p = lat * D2R, l = lon * D2R, p0 = lat0 * D2R, l0 = lon0 * D2R;
    const cc = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * Math.cos(p) * Math.cos(l - l0);
    const c = Math.acos(Math.max(-1, Math.min(1, cc))), k = c > 1e-9 ? c / Math.sin(c) : 1;
    return [R_KM * k * Math.cos(p) * Math.sin(l - l0), R_KM * k * (Math.cos(p0) * Math.sin(p) - Math.sin(p0) * Math.cos(p) * Math.cos(l - l0))];
  }
  function aeqdI(x, y, lat0, lon0) {
    const p0 = lat0 * D2R, l0 = lon0 * D2R, rho = Math.hypot(x, y), c = rho / R_KM;
    if (rho < 1e-9) return [lat0, lon0];
    const lat = Math.asin(Math.cos(c) * Math.sin(p0) + y * Math.sin(c) * Math.cos(p0) / rho);
    const lon = l0 + Math.atan2(x * Math.sin(c), rho * Math.cos(p0) * Math.cos(c) - y * Math.sin(p0) * Math.sin(c));
    return [lat / D2R, ((lon / D2R) % 360 + 360) % 360];
  }
  const US_ANCHOR = [39.0, -96.0];

  // Lambert conformal conic US map (standard parallels 33N/45N, centered 39N 96W), in km
  function lccUS(lat, lon) {
    const f = d => d * D2R, p1 = f(33), p2 = f(45), lat0 = f(US_ANCHOR[0]), lon0 = US_ANCHOR[1];
    const n = Math.log(Math.cos(p1) / Math.cos(p2)) / Math.log(Math.tan(Math.PI / 4 + p2 / 2) / Math.tan(Math.PI / 4 + p1 / 2));
    const F = Math.cos(p1) * Math.pow(Math.tan(Math.PI / 4 + p1 / 2), n) / n;
    const rho = R_KM * F / Math.pow(Math.tan(Math.PI / 4 + f(lat) / 2), n);
    const rho0 = R_KM * F / Math.pow(Math.tan(Math.PI / 4 + lat0 / 2), n);
    const th = n * f(lon - lon0);
    return [rho * Math.sin(th), rho0 - rho * Math.cos(th)];
  }
  /** The classic Bering Sea Rule overlay: a flat US map pasted onto the chart at one scale.
   *  P = {lat, lon} where the US center lands, `scale` relative to the chart's own scale at
   *  that point, `rot` degrees counter-clockwise. projFn(lat, lon) -> [x, y] in chart pixels.
   *  Returns a function mapping US (lat, lon) -> chart pixels. */
  function pasteOverlay(P, projFn) {
    const A = projFn(P.lat, P.lon), d = 0.25;
    const E = projFn(P.lat, P.lon + d), N = projFn(P.lat + d, P.lon);
    const kmE = d * 111.32 * Math.cos(P.lat * D2R), kmN = d * 110.6;
    const e = [(E[0] - A[0]) / kmE, (E[1] - A[1]) / kmE];       // pixels per km toward east
    const nn = [(N[0] - A[0]) / kmN, (N[1] - A[1]) / kmN];      // pixels per km toward north
    const r = (P.rot || 0) * D2R, c = Math.cos(r), sn = Math.sin(r), s = P.scale;
    return (lat, lon) => {
      const [x0, y0] = lccUS(lat, lon), x = (c * x0 - sn * y0) * s, y = (sn * x0 + c * y0) * s;
      return [A[0] + x * e[0] + y * nn[0], A[1] + x * e[1] + y * nn[1]];
    };
  }
  function drawPixelLines(g, lines, toPx, attrs, maxJump) {
    let d = "";
    for (const ln of lines) {
      let prev = null;
      for (let i = 0; i < ln.length; i += 2) {
        const [x, y] = toPx(ln[i + 1], ln[i]);
        d += (!prev || Math.hypot(x - prev[0], y - prev[1]) > maxJump ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
        prev = [x, y];
      }
    }
    return el("path", Object.assign({ d, fill: "none" }, attrs), g);
  }
  /** US (lat, lon) -> (lat, lon 0..360) on the Pacific for overlay params {lat, lon, scale, rot} */
  function bsrTransform(lat, lon, P) {
    let [x, y] = aeqdF(lat, lon, US_ANCHOR[0], US_ANCHOR[1]);
    x *= P.scale; y *= P.scale;
    const r = (P.rot || 0) * D2R, c = Math.cos(r), s = Math.sin(r);
    return aeqdI(c * x - s * y, s * x + c * y, P.lat, P.lon);
  }

  /* ---------- outlines -------------------------------------------------------- */
  function drawLines(g, lines, pr, attrs, lon360, maxJumpPx) {
    let d = "";
    const jump = maxJumpPx || pr.W * 0.5;
    for (const ln of lines) {
      let prev = null;
      for (let i = 0; i < ln.length; i += 2) {
        let lon = ln[i]; const lat = ln[i + 1];
        if (!lon360 && lon < 0) lon += 360;
        const x = pr.x(lon), y = pr.y(lat);
        d += (!prev || Math.abs(x - prev[0]) > jump ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
        prev = [x, y];
      }
    }
    return el("path", Object.assign({ d, fill: "none" }, attrs), g);
  }
  function overlayLines(g, us, pr, P, attrs) {
    const toPx = pasteOverlay(P, (la, lo) => [pr.x(lo), pr.y(la)]);
    if (us.context) drawPixelLines(g, us.context, toPx, Object.assign({}, attrs, { "stroke-width": (attrs["stroke-width"] || 1.4) * 0.7, opacity: 0.6 }), pr.W * 0.3);
    drawPixelLines(g, us.states, toPx, attrs, pr.W * 0.3);
  }
  function graticule(g, pr, step) {
    const b = pr.b, dot = { stroke: "#8a8a8a", "stroke-width": 0.7, "stroke-dasharray": "1.5,4" };
    for (let lon = Math.ceil(b.lonW / step) * step; lon <= b.lonE; lon += step) {
      el("line", Object.assign({ x1: pr.x(lon), x2: pr.x(lon), y1: pr.T, y2: pr.T + pr.H }, dot), g);
      const lab = lon === 180 ? "180" : lon < 180 ? lon + "E" : (360 - lon) + "W";
      text(g, pr.x(lon), pr.T + pr.H + 16, lab, { "text-anchor": "middle", "font-size": 12, fill: "#333" });
    }
    for (let lat = Math.ceil(b.latS / step) * step; lat <= b.latN; lat += step) {
      el("line", Object.assign({ x1: pr.L, x2: pr.L + pr.W, y1: pr.y(lat), y2: pr.y(lat) }, dot), g);
      text(g, pr.L + pr.W + 4, pr.y(lat) + 4, lat + "N", { "font-size": 12, fill: "#333" });
    }
  }

  /* ---------- gridded fields ------------------------------------------------------ */
  function gridSampler(meta, vals) {
    const nr = meta.nrows, nc = meta.ncols, res = meta.res;
    return (lat, lon) => {
      const fr = (meta.lat_n - lat) / res, fc = (((lon - meta.lon_w) % 360) + 360) % 360 / res;
      if (fr < 0 || fc < 0 || fr > nr - 1 || fc > nc - 1) return null;
      const r0 = Math.min(nr - 2, Math.floor(fr)), c0 = Math.min(nc - 2, Math.floor(fc)), dr = fr - r0, dc = fc - c0;
      const v00 = vals[r0 * nc + c0], v01 = vals[r0 * nc + c0 + 1], v10 = vals[(r0 + 1) * nc + c0], v11 = vals[(r0 + 1) * nc + c0 + 1];
      if (v00 == null || v01 == null || v10 == null || v11 == null) return null;
      return v00 * (1 - dr) * (1 - dc) + v01 * (1 - dr) * dc + v10 * dr * (1 - dc) + v11 * dr * dc;
    };
  }
  // diverging blue-white-red for 500 mb anomalies (m)
  const DIV = [[33, 82, 171], [82, 143, 214], [158, 198, 235], [222, 236, 247], [255, 255, 255], [252, 224, 210], [244, 163, 132], [214, 91, 75], [165, 28, 45]];
  function divColor(v, lim) {
    const t = Math.max(-1, Math.min(1, v / lim)) * 4 + 4, i = Math.min(7, Math.floor(t)), f = t - i;
    const a = DIV[i], b = DIV[i + 1];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }
  function fillImage(g, pr, sample, lim) {
    const cw = Math.round(pr.W / 2), ch = Math.round(pr.H / 2);
    const cv = document.createElement("canvas"); cv.width = cw; cv.height = ch;
    const ctx = cv.getContext("2d"), img = ctx.createImageData(cw, ch);
    for (let j = 0; j < ch; j++) {
      const lat = pr.lat(pr.T + (j + 0.5) / ch * pr.H);
      for (let i = 0; i < cw; i++) {
        const v = sample(lat, pr.lon(pr.L + (i + 0.5) / cw * pr.W)), k = (j * cw + i) * 4;
        if (v == null) { img.data[k + 3] = 0; continue; }
        const c = divColor(v, lim);
        img.data[k] = c[0]; img.data[k + 1] = c[1]; img.data[k + 2] = c[2]; img.data[k + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    el("image", { href: cv.toDataURL(), x: pr.L, y: pr.T, width: pr.W, height: pr.H, preserveAspectRatio: "none" }, g);
  }
  // marching squares on a refined lat/lon grid -> contour path per level
  function contours(g, pr, sample, levels, attrs, labelFn) {
    const b = pr.b, step = 0.625;
    const lats = [], lons = [];
    for (let la = b.latN; la >= b.latS - 1e-6; la -= step) lats.push(la);
    for (let lo = b.lonW; lo <= b.lonE + 1e-6; lo += step) lons.push(lo);
    const V = lats.map(la => lons.map(lo => sample(la, lo)));
    const P = (r, c) => [pr.x(lons[c]), pr.y(lats[r])];
    for (const lev of levels) {
      let d = "", labelled = 0;
      for (let r = 0; r < lats.length - 1; r++) for (let c = 0; c < lons.length - 1; c++) {
        const a = V[r][c], bb = V[r][c + 1], cc = V[r + 1][c + 1], dd = V[r + 1][c];
        if (a == null || bb == null || cc == null || dd == null) continue;
        const idx = (a > lev) | ((bb > lev) << 1) | ((cc > lev) << 2) | ((dd > lev) << 3);
        if (idx === 0 || idx === 15) continue;
        const pa = P(r, c), pb = P(r, c + 1), pc = P(r + 1, c + 1), pd = P(r + 1, c);
        const lerp = (p, q, vp, vq) => { const t = (lev - vp) / (vq - vp); return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]; };
        const top = () => lerp(pa, pb, a, bb), right = () => lerp(pb, pc, bb, cc), bottom = () => lerp(pd, pc, dd, cc), left = () => lerp(pa, pd, a, dd);
        const segs = { 1: [[left, top]], 2: [[top, right]], 3: [[left, right]], 4: [[right, bottom]], 5: [[left, top], [right, bottom]], 6: [[top, bottom]], 7: [[left, bottom]],
          8: [[bottom, left]], 9: [[bottom, top]], 10: [[top, right], [bottom, left]], 11: [[bottom, right]], 12: [[right, left]], 13: [[right, top]], 14: [[top, left]] }[idx];
        for (const [f1, f2] of segs) {
          const p1 = f1(), p2 = f2();
          d += "M" + p1[0].toFixed(1) + "," + p1[1].toFixed(1) + "L" + p2[0].toFixed(1) + "," + p2[1].toFixed(1);
          if (labelFn && labelled < 2 && (r * 7 + c * 13 + Math.round(lev)) % 97 === 0) {
            labelled++;
            text(g, p1[0], p1[1], labelFn(lev), { "font-size": 10, fill: attrs.stroke, "text-anchor": "middle", stroke: "#fff", "stroke-width": 3, "paint-order": "stroke" });
          }
        }
      }
      el("path", Object.assign({ d, fill: "none" }, attrs), g);
    }
  }
  function extrema(meta, vals, kind) {
    const nr = meta.nrows, nc = meta.ncols, out = [];
    for (let r = 2; r < nr - 2; r++) for (let c = 2; c < nc - 2; c++) {
      const v = vals[r * nc + c]; if (v == null) continue;
      let isMin = true, isMax = true;
      for (let dr = -2; dr <= 2; dr++) for (let dc = -2; dc <= 2; dc++) {
        if (!dr && !dc) continue;
        const w = vals[(r + dr) * nc + c + dc]; if (w == null) continue;
        if (w <= v) isMin = false; if (w >= v) isMax = false;
      }
      if (isMin && kind !== "max") out.push({ r, c, v, t: "L" });
      if (isMax && kind !== "min") out.push({ r, c, v, t: "H" });
    }
    return out;
  }

  /* ---------- Bering Sea Rule map ------------------------------------------------- */
  function bsrMap(container, spec) {
    const W = spec.width || 1000, H = spec.height || 640;
    const { svg } = TC.makeSvg(container, W, H, spec.title);
    const L = 20, T = 64, MW = W - 70, MH = H - T - 34;
    const pr = projection(spec.bounds, L, T, MW, MH);
    text(svg, 22, 24, spec.title, { "font-size": 19 });
    text(svg, 22, 47, spec.sub, { "font-size": 15, fill: "#333" });
    if (spec.badge) {
      const bw = 18 + spec.badge.length * 10.5;
      el("rect", { x: W - bw - 28, y: 10, width: bw, height: 42, rx: 4, fill: "#14243a" }, svg);
      text(svg, W - 28 - bw / 2, 39, spec.badge, { "font-size": 22, "font-weight": 700, fill: "#fff", "text-anchor": "middle" });
    }
    const cid = "mclip" + Math.random().toString(36).slice(2);
    el("rect", { x: L, y: T, width: MW, height: MH }, el("clipPath", { id: cid }, el("defs", {}, svg)));
    const g = el("g", { "clip-path": `url(#${cid})` }, svg);
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "#f4f6f8" }, g);
    const f = spec.field, meta = spec.meta;
    if (f === "z500a" && spec.z500a) {
      fillImage(g, pr, gridSampler(meta, spec.z500a), 240);
      if (spec.z500) contours(g, pr, gridSampler(meta, spec.z500), range(4800, 6000, 60), { stroke: "#222", "stroke-width": 1 }, v => String(v / 10));
    }
    if (spec.coast) drawLines(g, spec.coast.lines, pr, { stroke: f === "z500a" ? "#555" : "#8c7b5f", "stroke-width": 0.9 }, true);
    if (f === "mslp" && spec.mslp) {
      const hpa = spec.mslp.map(v => v == null ? null : v / 10);
      contours(g, pr, gridSampler(meta, hpa), range(948, 1056, 4), { stroke: "#c0392b", "stroke-width": 1.1 }, v => String(v).slice(-2));
      for (const e of extrema(meta, hpa)) {
        const lat = meta.lat_n - e.r * meta.res, lon = meta.lon_w + e.c * meta.res;
        if ((e.t === "L" && e.v > 1012) || (e.t === "H" && e.v < 1018)) continue;
        const x = pr.x(lon), y = pr.y(lat);
        text(g, x, y + 8, e.t, { "font-size": 26, "font-weight": 700, fill: e.t === "L" ? "#c0392b" : "#1f4fb5", "text-anchor": "middle" });
        text(g, x, y + 24, String(Math.round(e.v)), { "font-size": 12, "font-weight": 700, fill: "#222", "text-anchor": "middle", stroke: "#fff", "stroke-width": 3, "paint-order": "stroke" });
      }
    }
    graticule(svg, pr, 10);
    if (spec.us && spec.overlay) overlayLines(g, spec.us, pr, spec.overlay, { stroke: "#000", "stroke-width": 1.5, "stroke-linejoin": "round" });
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "none", stroke: "#000", "stroke-width": 1.5 }, svg);
    if (f === "z500a") {   // color key
      const kx = L + 10, ky = T + MH - 24;
      el("rect", { x: kx - 6, y: ky - 18, width: 278, height: 36, fill: "#fff", opacity: 0.85, rx: 3 }, svg);
      for (let i = 0; i < 24; i++) { const c = divColor(-240 + i * 20.87, 240); el("rect", { x: kx + i * 11, y: ky - 12, width: 11, height: 12, fill: `rgb(${c.map(Math.round)})` }, svg); }
      text(svg, kx, ky + 13, "-240 m", { "font-size": 11 }); text(svg, kx + 132, ky + 13, "0", { "font-size": 11, "text-anchor": "middle" });
      text(svg, kx + 264, ky + 13, "+240", { "font-size": 11, "text-anchor": "end" });
    }
    return { svg, pr };
  }
  function range(a, b, s) { const o = []; for (let v = a; v <= b; v += s) o.push(v); return o; }

  /* ---------- Typhoon track map -------------------------------------------------- */
  const CAT = [[34, "#5ea8e0", "Depression"], [64, "#3aa35b", "Tropical storm"], [96, "#f2c12e", "Typhoon"], [130, "#e8762c", "Strong typhoon"], [999, "#c0234a", "Super typhoon"]];
  const catOf = w => w == null ? CAT[0] : CAT.find(c => w < c[0]);
  function trackMap(container, spec) {
    const W = spec.width || 1000, H = spec.height || 640;
    const { svg, tip } = TC.makeSvg(container, W, H, spec.title);
    const L = 20, T = 64, MW = W - 70, MH = H - T - 34;
    const pr = projection(spec.bounds, L, T, MW, MH);
    text(svg, 22, 24, spec.title, { "font-size": 19 });
    text(svg, 22, 47, spec.sub, { "font-size": 15, fill: "#333" });
    const cid = "tclip" + Math.random().toString(36).slice(2);
    el("rect", { x: L, y: T, width: MW, height: MH }, el("clipPath", { id: cid }, el("defs", {}, svg)));
    const g = el("g", { "clip-path": `url(#${cid})` }, svg);
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "#eef3f7" }, g);
    // Japan box used by the rule
    const jb = spec.japanBox;
    if (jb) el("rect", { x: pr.x(jb.lon[0]), y: pr.y(jb.lat[1]), width: pr.x(jb.lon[1]) - pr.x(jb.lon[0]), height: pr.y(jb.lat[0]) - pr.y(jb.lat[1]), fill: "#fff3c4", stroke: "#d6b54a", "stroke-dasharray": "5,4" }, g);
    if (spec.coast) drawLines(g, spec.coast.lines, pr, { stroke: "#6b6b6b", "stroke-width": 1 }, true);
    graticule(svg, pr, 10);
    const hits = [];
    for (const s of spec.storms) {
      const sg = el("g", { opacity: s.dim ? 0.45 : 1 }, g);
      const pts = s.pts.map(p => ({ t: p[0], lat: p[1], lon: p[2], w: p[3], x: pr.x(p[2]), y: pr.y(p[1]) }));
      el("path", { d: pts.map((p, i) => (i ? "L" : "M") + p.x.toFixed(1) + "," + p.y.toFixed(1)).join(""), fill: "none", stroke: "#333", "stroke-width": s.rule ? 2.2 : 1.2 }, sg);
      pts.forEach((p, i) => {
        if (i % 2 && i !== pts.length - 1) return;                         // every 12 h
        el("circle", { cx: p.x, cy: p.y, r: 3.6, fill: catOf(p.w)[1], stroke: "#222", "stroke-width": 0.6 }, sg);
        hits.push({ s, p });
      });
      const last = pts[pts.length - 1];
      text(sg, last.x + 7, last.y - 6, s.name, { "font-size": 13, "font-weight": 700, fill: "#111", stroke: "#fff", "stroke-width": 3, "paint-order": "stroke" });
      if (s.recurve) {
        const x = pr.x(s.recurve.lon), y = pr.y(s.recurve.lat), r = 9, star = [];
        for (let k = 0; k < 10; k++) { const a = -Math.PI / 2 + k * Math.PI / 5, rr = k % 2 ? r * 0.45 : r; star.push((x + rr * Math.cos(a)).toFixed(1) + "," + (y + rr * Math.sin(a)).toFixed(1)); }
        el("polygon", { points: star.join(" "), fill: s.rule ? "#c0234a" : "#888", stroke: "#fff", "stroke-width": 1.2 }, sg);
      }
    }
    el("rect", { x: L, y: T, width: MW, height: MH, fill: "none", stroke: "#000", "stroke-width": 1.5 }, svg);
    // legend
    const lx = W - 250, ly = 14;
    CAT.forEach((c, i) => { el("circle", { cx: lx + (i % 3) * 82, cy: ly + Math.floor(i / 3) * 18 + 4, r: 5, fill: c[1], stroke: "#222", "stroke-width": 0.6 }, svg); text(svg, lx + (i % 3) * 82 + 9, ly + Math.floor(i / 3) * 18 + 8, c[2].replace(" typhoon", " TY").replace("Tropical storm", "Trop. storm"), { "font-size": 11 }); });
    const hit = el("rect", { x: L, y: T, width: MW, height: MH, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", evt => {
      const pt = TC.svgPoint(svg, evt);
      let best = null, bd = 1e9;
      for (const h of hits) { const d = Math.hypot(h.p.x - pt.x, h.p.y - pt.y); if (d < bd) { bd = d; best = h; } }
      if (!best || bd > 14) { tip.style.display = "none"; return; }
      const t = best.p.t;
      TC.placeTip(container, tip, evt, `<b>${best.s.name}</b><div>${t.slice(8, 10)}Z ${t.slice(6, 8)} ${TC.MON[+t.slice(4, 6) - 1]}</div>` +
        `<div class=tc-row><span class=tc-lab>Position</span><span class=tc-val>${best.p.lat.toFixed(1)}N ${best.p.lon <= 180 ? best.p.lon.toFixed(1) + "E" : (360 - best.p.lon).toFixed(1) + "W"}</span></div>` +
        `<div class=tc-row><span class=tc-lab>Max wind</span><span class=tc-val>${best.p.w == null ? "—" : best.p.w + " kt"}</span></div>` +
        `<div class=tc-muted>${catOf(best.p.w)[2]}</div>`);
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    return { svg, pr };
  }

  /* ---------- simple date timeline (Typhoon Rule windows) ------------------------ */
  function timeline(container, spec) {
    const rows = spec.rows, W = spec.width || 1000, rowH = 30, H = 70 + Math.max(1, rows.length) * rowH;
    const { svg, tip } = TC.makeSvg(container, W, H, spec.title);
    const L = 190, R = W - 20, T = 46, B = H - 22, DAY = TC.DAY;
    const sx = t => L + (t - spec.t0) / (spec.t1 - spec.t0) * (R - L);
    text(svg, 12, 24, spec.title, { "font-size": 17 });
    for (let t = Math.ceil(spec.t0 / DAY) * DAY; t <= spec.t1; t += DAY) {
      const d = new Date(t), major = d.getUTCDate() % 5 === 0 && d.getUTCDate() < 31;
      el("line", { x1: sx(t), x2: sx(t), y1: T - 4, y2: B, stroke: major ? "#c9ced4" : "#eceff2" }, svg);
      if (major) text(svg, sx(t), T - 10, TC.dLabel(t), { "font-size": 12, "text-anchor": "middle", fill: "#333" });
    }
    if (!rows.length) text(svg, (L + R) / 2, T + 30, spec.empty || "No qualifying storms", { "text-anchor": "middle", "font-size": 14, fill: "#777" });
    rows.forEach((r, i) => {
      const y = T + 8 + i * rowH;
      text(svg, L - 10, y + 15, r.label, { "font-size": 13, "text-anchor": "end", "font-weight": r.strong ? 700 : 400 });
      if (r.mark) el("line", { x1: sx(r.mark), x2: sx(r.mark), y1: y + 2, y2: y + 20, stroke: "#555", "stroke-width": 2 }, svg);
      const x0 = Math.max(L, sx(r.a)), x1 = Math.min(R, sx(r.b));
      if (x1 > x0) {
        const bar = el("rect", { x: x0, y: y + 3, width: x1 - x0, height: 16, rx: 3, fill: r.color, opacity: r.strong ? 0.95 : 0.5 }, svg);
        bar.addEventListener("mousemove", evt => TC.placeTip(container, tip, evt, r.tip));
        bar.addEventListener("mouseleave", () => { tip.style.display = "none"; });
      }
    });
    const now = spec.now;
    if (now >= spec.t0 && now <= spec.t1) {
      el("line", { x1: sx(now), x2: sx(now), y1: T - 4, y2: B, stroke: "#c0392b", "stroke-width": 2 }, svg);
      text(svg, sx(now) + 4, B + 14, "now", { "font-size": 12, fill: "#c0392b" });
    }
  }

  /* ---------- OPC chart calibration (pixel <-> lat/lon) --------------------------- */
  // Mercator: x = a + b*lon, y = c - d*merc(lat)   |  polar stereographic: rho = k*tan((90-lat)/2)
  function solveCal(kind, p1, p2) {
    const lonE = l => ((l % 360) + 360) % 360;
    if (kind === "polar") {
      // north-polar stereographic: plane w = r*(sin lon + i cos lon), r = tan((90-lat)/2);
      // screen z = A*w + B (complex scale+rotation+shift), y pointing down
      const w = p => { const r = Math.tan((90 - p.lat) * D2R / 2), l = lonE(p.lon) * D2R; return [r * Math.sin(l), r * Math.cos(l)]; };
      const w1 = w(p1), w2 = w(p2), dz = [p2.x - p1.x, p2.y - p1.y], dw = [w2[0] - w1[0], w2[1] - w1[1]];
      const den = dw[0] * dw[0] + dw[1] * dw[1];
      const A = [(dz[0] * dw[0] + dz[1] * dw[1]) / den, (dz[1] * dw[0] - dz[0] * dw[1]) / den];
      const B = [p1.x - (A[0] * w1[0] - A[1] * w1[1]), p1.y - (A[0] * w1[1] + A[1] * w1[0])];
      return { kind: "polar", A, B };
    }
    const b = (p2.x - p1.x) / (lonE(p2.lon) - lonE(p1.lon)), a = p1.x - b * lonE(p1.lon);
    const d = (p2.y - p1.y) / (merc(p1.lat) - merc(p2.lat)), c = p1.y + d * merc(p1.lat);
    return { kind: "mercator", a, b, c, d };
  }
  function calProject(cal, lat, lon) {
    lon = ((lon % 360) + 360) % 360;
    if (cal.kind === "polar") {
      const r = Math.tan((90 - lat) * D2R / 2), w = [r * Math.sin(lon * D2R), r * Math.cos(lon * D2R)];
      return [cal.A[0] * w[0] - cal.A[1] * w[1] + cal.B[0], cal.A[0] * w[1] + cal.A[1] * w[0] + cal.B[1]];
    }
    return [cal.a + cal.b * lon, cal.c - cal.d * merc(lat)];
  }
  function chartOverlay(svg, cal, us, P, opts) {
    const g = el("g", { "pointer-events": "none" }, svg);
    const toPx = pasteOverlay(P, (la, lo) => calProject(cal, la, lo));
    const draw = (lines, attrs) => drawPixelLines(g, lines, toPx, attrs, 400);
    const w = opts && opts.width || 1.6;
    if (us.context) draw(us.context, { stroke: "#000", "stroke-width": w * 0.7, opacity: 0.55 });
    draw(us.states, { stroke: "#000", "stroke-width": w, "stroke-linejoin": "round" });
    if (opts && opts.grid) {   // calibration check: draw the lat/lon grid
      for (let lat = 20; lat <= 70; lat += 10) { let d = ""; for (let lon = 120; lon <= 250; lon += 2) { const [x, y] = calProject(cal, lat, lon); d += (lon === 120 ? "M" : "L") + x + "," + y; } el("path", { d, fill: "none", stroke: "#e0007a", "stroke-width": 1.2, "stroke-dasharray": "6,4" }, g); }
      for (let lon = 130; lon <= 240; lon += 10) { let d = ""; for (let lat = 15; lat <= 72; lat += 1) { const [x, y] = calProject(cal, lat, lon); d += (lat === 15 ? "M" : "L") + x + "," + y; } el("path", { d, fill: "none", stroke: "#e0007a", "stroke-width": 1.2, "stroke-dasharray": "6,4" }, g); }
    }
    return g;
  }

  window.TeleMaps = { projection, bsrTransform, pasteOverlay, lccUS, bsrMap, trackMap, timeline, solveCal, calProject, chartOverlay, CAT };
})();
