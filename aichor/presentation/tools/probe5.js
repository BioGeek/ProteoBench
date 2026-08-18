// Text-vs-text collision detection inside every chart. The height probe proves a slide fits its
// frame; it says nothing about two labels landing on top of each other, which is the other way
// text "touches" something it should not. Pairwise bbox intersection over <text> nodes, reported
// in the chart's own viewBox units so the numbers point straight at the drawing code.
(async () => {
  const out = [];
  const sections = [...document.querySelectorAll('.slides > section')];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < sections.length; i++) {
    Reveal.slide(i, 0);
    await sleep(140);
    const s = sections[i];
    const h2 = s.querySelector('h2');
    for (const [n, svg] of [...s.querySelectorAll('svg.chart')].entries()) {
      const vb = svg.viewBox.baseVal;
      const sr = svg.getBoundingClientRect();
      const k = sr.width / vb.width || 1;                 // px per viewBox unit
      const texts = [...svg.querySelectorAll('text')].map(el => {
        const r = el.getBoundingClientRect();
        return {
          x: +((r.left - sr.left) / k).toFixed(1), y: +((r.top - sr.top) / k).toFixed(1),
          w: +(r.width / k).toFixed(1), h: +(r.height / k).toFixed(1),
          cls: el.getAttribute('class') || '',
          t: (el.textContent || '').trim().slice(0, 26),
        };
      });
      const hits = [];
      for (let a = 0; a < texts.length; a++) {
        for (let b = a + 1; b < texts.length; b++) {
          const A = texts[a], B = texts[b];
          const ox = Math.min(A.x + A.w, B.x + B.w) - Math.max(A.x, B.x);
          const oy = Math.min(A.y + A.h, B.y + B.h) - Math.max(A.y, B.y);
          if (ox > 1 && oy > 1) hits.push({a: A.t, acls: A.cls, b: B.t, bcls: B.cls,
                                          ox: +ox.toFixed(1), oy: +oy.toFixed(1)});
        }
      }
      // text escaping the chart's own viewBox
      const esc = texts.filter(T => T.x < -1 || T.y < -1 || T.x + T.w > vb.width + 1 || T.y + T.h > vb.height + 1)
                       .map(T => ({t: T.t, cls: T.cls, x: T.x, y: T.y, w: T.w, h: T.h}));
      if (hits.length || esc.length) {
        out.push({slide: i + 1, chart: n + 1, title: h2 ? h2.textContent.trim().slice(0, 44) : '',
                  vb: [vb.width, vb.height], hits: hits.slice(0, 12), esc: esc.slice(0, 8)});
      }
    }
  }
  const pre = document.createElement('pre'); pre.id = 'PROBE_RESULT';
  pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
