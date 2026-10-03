// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── Ink: drawing over the deck ──
// D turns drawing on and off. While it is on, the pointer draws over
// everything on the slide, the live app and terminals included, and the deck
// keys still move between slides. Three tools: a pen, a highlighter, and
// laser ink that fades a moment after you lift. Ink belongs to its slide:
// it is kept in stage pixels, so it scales with the deck and is still there
// when you come back. U (or ⌘/Ctrl-Z) takes back the last stroke, C clears
// the slide, Esc puts the pen down.
(function () {
  const deck = document.querySelector('.deck');
  const canvas = document.getElementById('ink');
  const bar = document.querySelector('.ink-bar');
  if (!deck || !canvas || !bar) return;
  const ctx = canvas.getContext('2d');
  const W = 1920;
  const FADE = 1100;   // ms laser ink takes to go, after the stroke ends

  const COLORS = { accent: '--accent', violet: '--accent2', yellow: '--yellow', red: '--red', ink: '--text' };
  const TOOLS = {
    pen: { width: 6, alpha: 1 },
    marker: { width: 30, alpha: 0.32 },
    laser: { width: 7, alpha: 1, glow: 18 },
  };
  let on = false, tool = 'pen', color = 'accent';
  const ink = new WeakMap();   // slide → strokes
  let stroke = null;

  const slide = () => document.querySelector('.slide.active');
  const strokes = () => {
    const s = slide();
    if (!s) return [];   // before the deck has shown a slide
    if (!ink.has(s)) ink.set(s, []);
    return ink.get(s);
  };
  const cssColor = name => getComputedStyle(document.documentElement).getPropertyValue(COLORS[name]).trim();
  function stagePoint(e) {
    const r = deck.getBoundingClientRect(), k = W / r.width;
    return { x: (e.clientX - r.left) * k, y: (e.clientY - r.top) * k, p: e.pressure || 0.5 };
  }

  function size() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(innerWidth * dpr); canvas.height = Math.round(innerHeight * dpr);
    render();
  }

  // Smooth lines: a quadratic curve through the midpoints of the samples.
  function trace(pts) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    if (pts.length < 3) { const q = pts[pts.length - 1]; ctx.lineTo(q.x + 0.01, q.y); return; }
    for (let i = 1; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      ctx.quadraticCurveTo(a.x, a.y, (a.x + b.x) / 2, (a.y + b.y) / 2);
    }
    const z = pts[pts.length - 1];
    ctx.lineTo(z.x, z.y);
  }

  let raf = 0;
  function render() {
    raf = 0;
    const r = deck.getBoundingClientRect(), dpr = canvas.width / innerWidth, k = (r.width / W) * dpr;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(k, 0, 0, k, r.left * dpr, r.top * dpr);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    const now = performance.now();
    let fading = false;
    const list = strokes();
    for (let i = list.length - 1; i >= 0; i--) {
      const s = list[i];
      let alpha = TOOLS[s.tool].alpha;
      if (s.tool === 'laser' && s.done) {
        const t = (now - s.done) / FADE;
        if (t >= 1) { list.splice(i, 1); continue; }
        alpha *= 1 - t * t;
        fading = true;
      }
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = s.color;
      ctx.lineWidth = TOOLS[s.tool].width * (s.tool === 'pen' ? 0.6 + s.pts[0].p * 0.8 : 1);
      ctx.shadowColor = s.color;
      ctx.shadowBlur = TOOLS[s.tool].glow ? TOOLS[s.tool].glow * k : 0;
      trace(s.pts);
      ctx.stroke();
    }
    ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    if (fading) schedule();
  }
  const schedule = () => { if (!raf) raf = requestAnimationFrame(render); };

  canvas.addEventListener('pointerdown', e => {
    if (!on || e.button !== 0) return;
    canvas.setPointerCapture(e.pointerId);
    stroke = { tool, color: cssColor(color), pts: [stagePoint(e)] };
    strokes().push(stroke);
    schedule();
  });
  canvas.addEventListener('pointermove', e => {
    if (!stroke) return;
    const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    evs.forEach(ev => stroke.pts.push(stagePoint(ev)));
    schedule();
  });
  const end = () => { if (stroke) { stroke.done = performance.now(); stroke = null; schedule(); } };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);

  function set(next) {
    on = next;
    document.body.classList.toggle('inking', on);
    bar.classList.toggle('open', on);
    if (!on) end();
  }
  function pick(kind, value) {
    if (kind === 'tool') tool = value; else color = value;
    bar.querySelectorAll(`[data-${kind}]`).forEach(b => b.classList.toggle('on', b.dataset[kind] === value));
  }
  function undo() {
    const list = strokes();
    const i = list.map(s => s.tool !== 'laser').lastIndexOf(true);
    if (i >= 0) list.splice(i, 1);
    schedule();
  }
  function clear() { strokes().length = 0; schedule(); }

  bar.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.tool) pick('tool', b.dataset.tool);
    else if (b.dataset.color) pick('color', b.dataset.color);
    else if (b.dataset.act === 'undo') undo();
    else if (b.dataset.act === 'clear') clear();
    else if (b.dataset.act === 'close') set(false);
  });
  bar.querySelectorAll('[data-color]').forEach(b => { b.style.setProperty('--swatch', `var(${COLORS[b.dataset.color]})`); });
  addEventListener('keydown', e => {
    if (on && (e.metaKey || e.ctrlKey) && e.key === 'z') { e.preventDefault(); undo(); }
  });

  addEventListener('resize', size);
  // Follow the deck: a new slide shows its own ink, a resize redraws it.
  new MutationObserver(schedule).observe(deck, { subtree: true, attributes: true, attributeFilter: ['class', 'style'] });
  size();

  window.DeckInk = {
    get on() { return on; },
    toggle: () => set(!on),
    off: () => set(false),
    undo, clear,
    tool: t => { if (TOOLS[t]) { pick('tool', t); if (!on) set(true); } },
  };
})();
