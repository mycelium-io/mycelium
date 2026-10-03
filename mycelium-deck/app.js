// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── The live app ──
// A .app[data-app="/route"] pane shows its screenshot until the Mycelium app
// answers, then the real app in a frame. The app is looked for at ?app=… on
// the deck's URL, else the Docker stack's port (8080), else the Mac app's
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
    const s = { el, view, frame, shield, url, routes, queue: [...routes], zoom, mag: 1, mx: 0, my: 0 };
    panes.set(el, s);
    place(s);
    const bar = el.querySelector('.bar');
    if (bar) {
      bar.insertAdjacentHTML('beforeend', '<span class="app-zoom"><button type="button" class="out" aria-label="Zoom out">−</button><button type="button" class="pct" title="Back to fit">100%</button><button type="button" class="in" aria-label="Zoom in">+</button></span>');
      const centre = () => ({ x: view.offsetWidth / 2, y: view.offsetHeight / 2 });
      bar.querySelector('.app-zoom .in').addEventListener('click', () => magnify(s, s.mag * 1.25, centre()));
      bar.querySelector('.app-zoom .out').addEventListener('click', () => magnify(s, s.mag / 1.25, centre()));
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
      if (s.mag <= 1.001 || e.button !== 0) return;
      const k = view.offsetWidth / view.getBoundingClientRect().width;
      const start = { x: e.clientX, y: e.clientY, mx: s.mx, my: s.my };
      const move = m => {
        if (Math.abs(m.clientX - start.x) + Math.abs(m.clientY - start.y) > 4) s.dragged = true;
        s.mx = start.mx + (m.clientX - start.x) * k; s.my = start.my + (m.clientY - start.y) * k;
        place(s, false);
      };
      const up = () => { removeEventListener('mousemove', move); removeEventListener('mouseup', up); };
      addEventListener('mousemove', move); addEventListener('mouseup', up);
      e.preventDefault();
    });
    shield.addEventListener('wheel', e => {
      e.preventDefault();
      const p = local(s, e);
      if (e.ctrlKey || e.metaKey) magnify(s, s.mag * Math.exp(-e.deltaY * 0.01), p, false);
      else if (s.mag > 1.001) { s.mx -= e.deltaX; s.my -= e.deltaY; place(s, false); }
    }, { passive: false });
    view.append(frame, shield);
    open(el.dataset.app);
    s.open = open;
  }

  // ── Zoom ──
  // The frame is laid out at the pane's size over its data-zoom, then drawn at
  // translate(mx, my) scale(zoom * mag), so magnifying never reflows the app.
  // The magnified app always covers the pane.
  function place(s, animate = true) {
    const w = s.view.offsetWidth, h = s.view.offsetHeight;
    s.mx = Math.min(0, Math.max(w - w * s.mag, s.mx));
    s.my = Math.min(0, Math.max(h - h * s.mag, s.my));
    s.frame.classList.toggle('zooming', animate);
    s.frame.style.transform = `translate(${s.mx}px, ${s.my}px) scale(${s.zoom * s.mag})`;
    s.el.classList.toggle('magnified', s.mag > 1.001);
    const pct = s.el.querySelector('.app-zoom .pct');
    if (pct) pct.textContent = `${Math.round(s.mag * 100)}%`;
  }
  // Zoom to `mag`, keeping the point `at` (pane pixels) where it is.
  function magnify(s, mag, at, animate = true) {
    mag = Math.max(1, Math.min(4, mag));
    const p = at || { x: s.view.offsetWidth / 2, y: s.view.offsetHeight / 2 };
    const cx = (p.x - s.mx) / s.mag, cy = (p.y - s.my) / s.mag;
    s.mx = p.x - cx * mag; s.my = p.y - cy * mag; s.mag = mag;
    if (mag === 1) { s.mx = 0; s.my = 0; }
    place(s, animate);
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
    zoomKey: (slide, dir) => {
      const el = slide.querySelector('.app.live');
      const s = el && panes.get(el);
      if (!s) return false;
      if (dir === 0) { magnify(s, 1); return true; }
      const r = s.view.getBoundingClientRect();
      const over = pointer && pointer.clientX >= r.left && pointer.clientX <= r.right && pointer.clientY >= r.top && pointer.clientY <= r.bottom;
      magnify(s, s.mag * (dir > 0 ? 1.25 : 1 / 1.25), over ? local(s, pointer) : null);
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
