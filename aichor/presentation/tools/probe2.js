// Measure every slide against the VISIBLE viewport, not against its own section box.
// Reveal grows a section to fit its content and only ever scales for the authored 1280x800,
// so an over-tall slide silently spills past the top and bottom edges of the window. That
// spill is what a reader sees as text touching or crossing the border, and it is invisible
// to a section-relative measurement.
(async () => {
  const out = [];
  const sections = [...document.querySelectorAll('.slides > section')];
  const revealEl = document.querySelector('.reveal');
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < sections.length; i++) {
    Reveal.slide(i, 0);
    await sleep(140);
    const s = sections[i];
    const vw = window.innerWidth, vh = window.innerHeight;
    const sr = s.getBoundingClientRect();
    const h2 = s.querySelector('h2, h1');
    // which descendants actually cross the window edge
    const bad = [];
    for (const el of s.querySelectorAll('h1,h2,h3,p,table,tr,td,th,svg,div,li,code,span')) {
      if (!el.getClientRects().length) continue;
      const r = el.getBoundingClientRect();
      const d = {
        top: -r.top, bottom: r.bottom - vh, left: -r.left, right: r.right - vw,
      };
      const worst = Math.max(d.top, d.bottom, d.left, d.right);
      if (worst > 1) {
        bad.push({
          tag: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim()
               ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
          ...Object.fromEntries(Object.entries(d).map(([k, v]) => [k, +v.toFixed(0)])),
          text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 55),
        });
      }
    }
    // outermost offenders only: drop an element if an ancestor is also in the list
    const keep = bad.filter(b => true);
    out.push({
      i: i + 1,
      title: h2 ? h2.textContent.trim().slice(0, 56) : '(none)',
      vw, vh,
      sectionH: +sr.height.toFixed(0),
      sectionTop: +sr.top.toFixed(0),
      sectionBottom: +(sr.bottom - vh).toFixed(0),
      sectionLeft: +sr.left.toFixed(0),
      sectionRight: +(sr.right - vw).toFixed(0),
      scale: +(new DOMMatrixReadOnly(getComputedStyle(document.querySelector('.slides')).transform).a || 1).toFixed(3),
      nBad: keep.length,
      worst: keep.slice(0, 6),
    });
  }
  const pre = document.createElement('pre');
  pre.id = 'PROBE_RESULT';
  pre.textContent = JSON.stringify(out);
  document.body.appendChild(pre);
})();
