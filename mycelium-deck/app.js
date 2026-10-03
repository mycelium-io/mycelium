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
    frame.style.transform = `scale(${zoom})`;
    const shield = document.createElement('button');
    shield.className = 'app-shield';
    shield.type = 'button';
    shield.innerHTML = '<span>Click to use the app</span>';
    const s = { el, frame, shield, url, routes, queue: [...routes] };
    panes.set(el, s);

    const open = route => {
      const target = /^https?:/.test(route) ? route : url + route;
      frame.src = target;
      const addr = el.querySelector('.addr');
      if (addr) addr.textContent = target.replace(/^https?:\/\//, '');
    };
    frame.addEventListener('load', () => el.classList.add('live'), { once: true });
    shield.addEventListener('click', e => { e.stopPropagation(); el.classList.add('using'); frame.focus(); });
    view.append(frame, shield);
    open(el.dataset.app);
    s.open = open;
  }

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
