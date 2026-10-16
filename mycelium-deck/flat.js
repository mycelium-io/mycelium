// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── Flat diagrams: wires between boxes ──
// A slide lays its boxes out with ordinary HTML and CSS, and names the ones a
// wire joins with data-node. Each <path data-from="a" data-to="b"> in the
// slide's <svg class="wires"> is then drawn from box a to box b, leaving the
// side that faces the other box. data-route="elbow" bends it at a right angle
// instead of going straight. A path can be a .step like anything else.
//
// Positions are read from layout (offsetLeft/Top up to the slide), so they are
// stage pixels and don't move while a .rise box animates in.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const GAP = 10;

  // The arrowheads every wire shares, defined once for the whole page.
  const defs = document.createElementNS(NS, 'svg');
  defs.id = 'wire-defs';
  defs.setAttribute('width', '0'); defs.setAttribute('height', '0');
  defs.style.position = 'absolute';
  defs.innerHTML = ['wire-head', 'wire-head-hi'].map((id, i) =>
    `<marker id="${id}" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">` +
    `<path class="${i ? 'head-hi' : 'head'}" d="M0 0 L12 6 L0 12 z"/></marker>`).join('');
  document.body.appendChild(defs);

  // A box's rectangle in its slide's stage pixels.
  function rect(el, slide) {
    let x = 0, y = 0, n = el;
    while (n && n !== slide) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
    return { x, y, w: el.offsetWidth, h: el.offsetHeight, cx: x + el.offsetWidth / 2, cy: y + el.offsetHeight / 2 };
  }

  // Where a wire leaves a box, on the side facing the other one.
  function port(r, other, vertical) {
    if (vertical) return { x: r.cx, y: other.cy > r.cy ? r.y + r.h + GAP : r.y - GAP };
    return { x: other.cx > r.cx ? r.x + r.w + GAP : r.x - GAP, y: r.cy };
  }

  function layout(slide) {
    slide.querySelectorAll('svg.wires path[data-from]').forEach(path => {
      const a = slide.querySelector(`[data-node="${path.dataset.from}"]`);
      const b = slide.querySelector(`[data-node="${path.dataset.to}"]`);
      if (!a || !b) return;
      const ra = rect(a, slide), rb = rect(b, slide);
      const vertical = path.dataset.axis ? path.dataset.axis === 'v' : Math.abs(rb.cy - ra.cy) > Math.abs(rb.cx - ra.cx) * 0.6;
      const p = port(ra, rb, vertical), q = port(rb, ra, vertical);
      let d = `M${p.x} ${p.y} L${q.x} ${q.y}`;
      if (path.dataset.route === 'elbow') {
        d = vertical
          ? `M${p.x} ${p.y} V${(p.y + q.y) / 2} H${q.x} V${q.y}`
          : `M${p.x} ${p.y} H${(p.x + q.x) / 2} V${q.y} H${q.x}`;
      }
      path.setAttribute('d', d);
    });
  }

  // Callouts beside a section of a terminal pane (.callout[data-part]): each
  // sits at the right of its section's first line, or of the blank line just
  // above it (data-place="above"), wherever its section ends up in the text.
  function callouts(slide) {
    slide.querySelectorAll('.callout[data-part]').forEach(c => {
      const pane = c.parentElement;
      const part = pane.querySelector(`.part[data-part="${c.dataset.part}"]`);
      if (!part) return;
      const line = parseFloat(getComputedStyle(part.closest('pre')).lineHeight) || 32;
      let y = 0, n = part.closest('pre');
      while (n && n !== pane) { y += n.offsetTop; n = n.offsetParent; }
      y += part.offsetTop - part.closest('pre').offsetTop;
      if (c.dataset.place === 'above') y -= line;
      c.style.top = `${y + (line - c.offsetHeight) / 2}px`;
    });
  }

  const slides = [...document.querySelectorAll('.slide')].filter(s => s.querySelector('svg.wires, .callout'));
  const all = () => slides.forEach(s => { layout(s); callouts(s); });
  all();
  document.fonts?.ready.then(all);
  addEventListener('load', all);
})();
