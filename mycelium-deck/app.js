// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── The live app ──
// A .app[data-app="/route"] pane shows its screenshot until the Mycelium app
// answers, then the real app in a frame. The app is looked for at ?app=… on
// the deck's URL, else the Docker stack's port (8080), else the desktop app's
// (3717).
//
// A frame that has focus keeps every key, a clicker's included, so the frame
// sits under a shield until it is clicked; a click anywhere else on the slide
// gives the keys back to the deck. A pane's <template class="script"> lists
// routes, one per line: each press of → opens the next one.
//
// Zoom magnifies the app where you point, and the app stays usable while
// zoomed: the bar's − and + (the percentage goes back to fit), the + − 0 keys
// toward the pointer, or a pinch over the app; drag or scroll to look around.
(function () {
  const param = new URLSearchParams(location.search).get('app');
  const candidates = param ? [param] : ['http://127.0.0.1:8080', 'http://127.0.0.1:3717'];
  const panes = new Map();
  let base = null;

  // The first candidate that answers. A no-cors fetch can't read the reply,
  // but it fails outright when nothing is listening, which is all we need.
  function find() {
    if (base) return base;
    const probe = url => Promise.race([
      fetch(url.replace(/\/$/, '') + '/', { mode: 'no-cors', cache: 'no-store' }).then(() => url.replace(/\/$/, '')),
      new Promise((_, no) => setTimeout(no, 1500)),
    ]);
    base = candidates.reduce((p, url) => p.catch(() => probe(url)), Promise.reject(new Error('none')));
    base.catch(() => { base = null; });   // try again on the next slide that wants it
    return base;
  }

  async function activate(slide) {
    const els = [...slide.querySelectorAll('.app[data-app]')].filter(el => !panes.has(el));
    if (!els.length) return;
    let url;
    try { url = await find(); } catch { return; }   // no app: the screenshots stay
    els.forEach(el => start(el, url));
  }

  function start(el, url) {
    const view = el.querySelector('.app-view');
    const zoom = parseFloat(el.dataset.zoom || '1');
    const tpl = el.querySelector('template.script');
    const routes = tpl ? tpl.content.textContent.split('\n').map(l => l.trim()).filter(Boolean) : [];
    const frame = document.createElement('iframe');
    frame.title = el.dataset.title || 'Mycelium';
    frame.style.width = `${100 / zoom}%`;
    frame.style.height = `${100 / zoom}%`;
    const shield = document.createElement('button');
    shield.className = 'app-shield';
    shield.type = 'button';
    shield.innerHTML = '<span>Click to use the app</span>';
    const s = { el, view, frame, shield, url, routes, queue: [...routes], zoom, mag: 1, mx: 0, my: 0, tm: 1, tx: 0, ty: 0, anchor: null };
    panes.set(el, s);
    draw(s);
    const bar = el.querySelector('.bar');
    if (bar) {
      bar.insertAdjacentHTML('beforeend', '<span class="app-zoom"><button type="button" class="out" aria-label="Zoom out">−</button><button type="button" class="pct" title="Back to fit">100%</button><button type="button" class="in" aria-label="Zoom in">+</button></span>');
      const centre = () => ({ x: view.offsetWidth / 2, y: view.offsetHeight / 2 });
      bar.querySelector('.app-zoom .in').addEventListener('click', () => magnify(s, s.tm * 1.25, centre()));
      bar.querySelector('.app-zoom .out').addEventListener('click', () => magnify(s, s.tm / 1.25, centre()));
      bar.querySelector('.app-zoom .pct').addEventListener('click', () => magnify(s, 1));
    }

    const open = route => {
      const target = /^https?:/.test(route) ? route : url + route;
      frame.src = target;
      const addr = el.querySelector('.addr');
      if (addr) addr.textContent = target.replace(/^https?:\/\//, '');
    };
    frame.addEventListener('load', () => el.classList.add('live'), { once: true });
    shield.addEventListener('click', e => {
      e.stopPropagation();
      if (s.dragged) { s.dragged = false; return; }   // that was a pan, not a click in
      el.classList.add('using'); frame.focus();
    });
    // While zoomed, drag the shield to look around; a pinch over it zooms.
    shield.addEventListener('mousedown', e => {
      if (s.tm <= 1.001 || e.button !== 0) return;
      const k = view.offsetWidth / view.getBoundingClientRect().width;
      const start = { x: e.clientX, y: e.clientY, mx: s.tx, my: s.ty };
      const move = m => {
        if (Math.abs(m.clientX - start.x) + Math.abs(m.clientY - start.y) > 4) s.dragged = true;
        pan(s, start.mx + (m.clientX - start.x) * k, start.my + (m.clientY - start.y) * k, true);
      };
      const up = () => { removeEventListener('mousemove', move); removeEventListener('mouseup', up); };
      addEventListener('mousemove', move); addEventListener('mouseup', up);
      e.preventDefault();
    });
    shield.addEventListener('wheel', e => {
      e.preventDefault();
      const p = local(s, e);
      if (e.ctrlKey || e.metaKey) magnify(s, s.tm * Math.exp(-e.deltaY * 0.01), p);
      else if (s.tm > 1.001) pan(s, s.tx - e.deltaX, s.ty - e.deltaY);
    }, { passive: false });
    view.append(frame, shield);
    open(el.dataset.app);
    s.open = open;
  }

  // ── Zoom ──
  // The frame is laid out at the pane's size over its data-zoom, then drawn at
  // translate(mx, my) scale(zoom * mag), so magnifying never reflows the app.
  // Every input sets a target and the view eases to it, frame by frame. A zoom
  // holds one point of the app under one point of the pane (the anchor) the
  // whole way, so what you point at stays put as it grows. The magnified app
  // always covers the pane.
  function clampTo(s, mag, mx, my) {
    const w = s.view.offsetWidth, h = s.view.offsetHeight;
    return [Math.min(0, Math.max(w - w * mag, mx)), Math.min(0, Math.max(h - h * mag, my))];
  }
  function draw(s) {
    s.frame.style.transform = `translate(${s.mx}px, ${s.my}px) scale(${s.zoom * s.mag})`;
    s.el.classList.toggle('magnified', s.tm > 1.001);
    const pct = s.el.querySelector('.app-zoom .pct');
    if (pct) pct.textContent = `${Math.round(s.tm * 100)}%`;
  }
  let ticking = false, last = 0;
  function tick(now) {
    const dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;
    const k = reduce ? 1 : 1 - Math.exp(-dt * 13);
    let moving = false;
    panes.forEach(s => {
      const lm = Math.log(s.mag), lt = Math.log(s.tm);
      s.mag = Math.exp(lm + (lt - lm) * k);
      if (s.anchor) { s.mx = s.anchor.px - s.anchor.cx * s.mag; s.my = s.anchor.py - s.anchor.cy * s.mag; }
      else { s.mx += (s.tx - s.mx) * k; s.my += (s.ty - s.my) * k; }
      [s.mx, s.my] = clampTo(s, s.mag, s.mx, s.my);
      if (Math.abs(lt - Math.log(s.mag)) > 1e-4 || Math.abs(s.tx - s.mx) > 0.1 || Math.abs(s.ty - s.my) > 0.1) moving = true;
      else { s.mag = s.tm; s.mx = s.tx; s.my = s.ty; s.anchor = null; }
      draw(s);
    });
    ticking = moving;
    if (moving) requestAnimationFrame(tick);
  }
  function run() { if (!ticking) { ticking = true; last = performance.now(); requestAnimationFrame(tick); } }
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Zoom to `mag`, keeping the point `at` (pane pixels) where it is, or as
  // near as the pane's edges allow.
  function magnify(s, mag, at) {
    mag = Math.max(1, Math.min(4, mag));
    const p = at || { x: s.view.offsetWidth / 2, y: s.view.offsetHeight / 2 };
    const cx = (p.x - s.mx) / s.mag, cy = (p.y - s.my) / s.mag;
    s.tm = mag;
    [s.tx, s.ty] = clampTo(s, mag, p.x - cx * mag, p.y - cy * mag);
    // The one point that is in the same place now and at the target: zoom
    // around it, and the glide lands exactly on the target, edges and all.
    const d = s.mag - mag;
    if (Math.abs(d) < 1e-6) s.anchor = null;
    else {
      const ax = (s.tx - s.mx) / d, ay = (s.ty - s.my) / d;
      s.anchor = { px: s.mx + ax * s.mag, py: s.my + ay * s.mag, cx: ax, cy: ay };
    }
    run();
  }
  // Look around: `instant` for a drag, which follows the hand exactly.
  function pan(s, mx, my, instant) {
    s.anchor = null;
    [s.tx, s.ty] = clampTo(s, s.tm, mx, my);
    if (instant) { s.mx = s.tx; s.my = s.ty; draw(s); } else run();
  }
  // A screen point in pane pixels (the deck scales the stage).
  function local(s, e) {
    const r = s.view.getBoundingClientRect(), k = s.view.offsetWidth / r.width;
    return { x: (e.clientX - r.left) * k, y: (e.clientY - r.top) * k };
  }
  let pointer = null;
  addEventListener('mousemove', e => { pointer = e; }, { passive: true });

  // A page that focuses its own input as it loads would take the keys from
  // the deck. Unless the frame was clicked into, take them straight back.
  addEventListener('blur', () => setTimeout(() => {
    const f = document.activeElement;
    if (f && f.tagName === 'IFRAME') {
      const s = [...panes.values()].find(p => p.frame === f);
      if (s && !s.el.classList.contains('using')) { f.blur(); window.focus(); }
    }
  }, 0));

  // Taking the keys back: a click outside a frame in use.
  document.addEventListener('mousedown', e => {
    panes.forEach(s => {
      if (s.el.classList.contains('using') && !s.el.contains(e.target)) { s.el.classList.remove('using'); window.focus(); }
    });
  }, true);

  window.DeckApp = {
    activate,
    // The + − 0 keys: zoom the app on the slide toward the pointer when it is
    // over the app, else around the middle. False when the slide has none.
    zoomKey: (slide, dir, repeat) => {
      const el = slide.querySelector('.app.live');
      const s = el && panes.get(el);
      if (!s) return false;
      if (dir === 0) { magnify(s, 1); return true; }
      const r = s.view.getBoundingClientRect();
      const over = pointer && pointer.clientX >= r.left && pointer.clientX <= r.right && pointer.clientY >= r.top && pointer.clientY <= r.bottom;
      // Held down, the key repeats: smaller steps, so it glides rather than jumps.
      const step = repeat ? 1.08 : 1.25;
      magnify(s, s.tm * (dir > 0 ? step : 1 / step), over ? local(s, pointer) : null);
      return true;
    },
    typeNext: slide => {
      const el = [...slide.querySelectorAll('.app.live')].find(e => panes.get(e)?.queue.length);
      if (!el) return false;
      const s = panes.get(el);
      s.open(s.queue.shift());
      return true;
    },
    progress: slide => {
      const st = [...slide.querySelectorAll('.app.live')].map(el => panes.get(el)).filter(Boolean);
      const total = st.reduce((n, s) => n + s.routes.length, 0);
      return total ? `${total - st.reduce((n, s) => n + s.queue.length, 0)} / ${total} pages` : '';
    },
  };
})();
