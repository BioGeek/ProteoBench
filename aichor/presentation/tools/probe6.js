// Text against non-text geometry: markers and connector lines. A label struck through by a
// polyline, or sitting on top of a data point, is as broken as two labels on each other -- and
// invisible to a text-vs-text check. Everything is computed in the chart's own viewBox units via
// getBBox(), so a hit reports coordinates that match the drawing code.
(async () => {
  const out = [];
  const sections = [...document.querySelectorAll('.slides > section')];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const segHitsBox = (x1, y1, x2, y2, b) => {
    // clip the segment against the box (Liang-Barsky); any surviving span is a hit
    let t0 = 0, t1 = 1;
    const dx = x2 - x1, dy = y2 - y1;
    for (const [p, q] of [[-dx, x1 - b.x], [dx, b.x + b.w - x1], [-dy, y1 - b.y], [dy, b.y + b.h - y1]]) {
      if (p === 0) { if (q < 0) return false; continue; }
      const r = q / p;
      if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; }
      else { if (r < t0) return false; if (r < t1) t1 = r; }
    }
    return t1 - t0 > 0.02;
  };
  for (let i = 0; i < sections.length; i++) {
    Reveal.slide(i, 0);
    await sleep(140);
    const s = sections[i];
    const h2 = s.querySelector('h2');
    for (const [n, svg] of [...s.querySelectorAll('svg.chart')].entries()) {
      const texts = [...svg.querySelectorAll('text')].map(el => ({el, b: el.getBBox(),
        t: (el.textContent || '').trim().slice(0, 30)}));
      const hits = [];
      for (const T of texts) {
        // shrink the text box slightly: a 1px graze at the glyph edge is not a defect
        const b = {x: T.b.x + 1, y: T.b.y + 1.5, w: T.b.width - 2, h: T.b.height - 3};
        if (b.w <= 0 || b.h <= 0) continue;
        for (const c of svg.querySelectorAll('circle')) {
          const cx = +c.getAttribute('cx'), cy = +c.getAttribute('cy'), r = +c.getAttribute('r');
          const nx = Math.max(b.x, Math.min(cx, b.x + b.w)), ny = Math.max(b.y, Math.min(cy, b.y + b.h));
          if ((cx - nx) ** 2 + (cy - ny) ** 2 < r * r) hits.push({kind: 'marker', t: T.t, at: [cx, cy]});
        }
        for (const l of svg.querySelectorAll('line')) {
          if (l.getAttribute('stroke') === 'var(--grid)' || /grid/.test(l.getAttribute('stroke') || '')) continue;
          if (segHitsBox(+l.getAttribute('x1'), +l.getAttribute('y1'), +l.getAttribute('x2'), +l.getAttribute('y2'), b))
            hits.push({kind: 'line', t: T.t});
        }
        for (const pl of svg.querySelectorAll('polyline')) {
          const pts = (pl.getAttribute('points') || '').trim().split(/\s+/).map(p => p.split(',').map(Number));
          for (let j = 0; j + 1 < pts.length; j++) {
            if (segHitsBox(pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1], b)) {
              hits.push({kind: 'polyline', t: T.t}); break;
            }
          }
        }
      }
      if (hits.length) {
        const seen = new Set(), uniq = [];
        for (const x of hits) { const k = x.kind + x.t; if (!seen.has(k)) { seen.add(k); uniq.push(x); } }
        out.push({slide: i + 1, chart: n + 1, title: h2 ? h2.textContent.trim().slice(0, 42) : '', hits: uniq});
      }
    }
  }
  const pre = document.createElement('pre'); pre.id = 'PROBE_RESULT';
  pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
