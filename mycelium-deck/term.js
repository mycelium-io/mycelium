// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── Live terminals ──
// Served by serve.py (the URL carries ?token=…), a .term[data-term] pane
// becomes a real shell drawn by xterm.js. Opened as a file, it stays the
// static <pre> it was written with.
//
// A pane's <template class="script"> holds commands, one per line. While the
// shell isn't focused, each press of → types the next one and runs it, so a
// demo goes as rehearsed; click into the shell to type yourself, Esc to give
// the keys back to the deck.
(function () {
  const token = new URLSearchParams(location.search).get('token');
  const live = Boolean(token) && location.protocol.startsWith('http');
  const panes = new Map();   // element → state
  window.DeckTerm = {
    live,
    focused: () => Boolean(document.activeElement && document.activeElement.closest('.term.live')),
    pending: slide => [...slide.querySelectorAll('.term.live')].some(el => panes.get(el)?.queue.length),
    progress: slide => {
      const st = [...slide.querySelectorAll('.term.live')].map(el => panes.get(el)).filter(Boolean);
      const total = st.reduce((n, s) => n + s.script.length, 0);
      return total ? `${total - st.reduce((n, s) => n + s.queue.length, 0)} / ${total} commands` : '';
    },
    typeNext: slide => {
      const el = [...slide.querySelectorAll('.term.live')].find(e => panes.get(e)?.queue.length);
      if (!el) return false;
      const s = panes.get(el);
      type(s, s.queue.shift());
      return true;
    },
    activate, theme,
  };
  if (!live) return;

  const XTERM = 'https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0';
  const FIT = 'https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0';
  let ready = null;
  function load() {
    if (ready) return ready;
    const css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = `${XTERM}/css/xterm.css`;
    document.head.appendChild(css);
    const script = src => new Promise((ok, fail) => { const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
    ready = script(`${XTERM}/lib/xterm.js`).then(() => script(`${FIT}/lib/addon-fit.js`)).then(() => document.fonts.load('24px "Geist Mono"').catch(() => {}));
    return ready;
  }

  const api = (path, id, body) => fetch(`/term/${path}?id=${id}&token=${encodeURIComponent(token)}`, { method: 'POST', body });

  function palette() {
    const css = getComputedStyle(document.documentElement), v = n => css.getPropertyValue(n).trim();
    return {
      background: 'rgba(0,0,0,0)', foreground: v('--text'), cursor: v('--accent'), cursorAccent: v('--bg'),
      selectionBackground: v('--border-hi'),
      black: v('--faint'), brightBlack: v('--code-comment'),
      red: v('--red'), brightRed: v('--red'), green: v('--green'), brightGreen: v('--green'),
      yellow: v('--yellow'), brightYellow: v('--yellow'), blue: v('--code-flag'), brightBlue: v('--code-flag'),
      magenta: v('--accent2'), brightMagenta: v('--accent2'), cyan: v('--accent'), brightCyan: v('--accent'),
      white: v('--muted'), brightWhite: v('--text'),
    };
  }
  function theme() { panes.forEach(s => { s.term.options.theme = palette(); }); }

  // Start the shells on a slide the first time it is shown.
  async function activate(slide) {
    if (!live) return;
    const els = [...slide.querySelectorAll('.term[data-term]')].filter(el => !panes.has(el));
    if (!els.length) return;
    try { await load(); } catch { return; }   // no CDN: the static terminal stays
    els.forEach(start);
  }

  function start(el) {
    const id = el.dataset.term;
    const pre = el.querySelector('pre');
    const height = Math.max(pre ? pre.offsetHeight : 0, 440);
    const wrap = document.createElement('div');
    wrap.className = 'xterm-wrap';
    const host = document.createElement('div');
    host.className = 'xterm-host';
    host.style.height = (height - 70) + 'px';
    wrap.appendChild(host);
    const tpl = el.querySelector('template.script');
    const script = tpl ? tpl.content.textContent.split('\n').map(l => l.trim()).filter(Boolean) : [];
    const term = new window.Terminal({
      fontFamily: '"Geist Mono", ui-monospace, Menlo, monospace', fontSize: 24, lineHeight: 1.25,
      allowTransparency: true, cursorBlink: true, theme: palette(), scrollback: 2000,
    });
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    const s = { el, id, term, fit, script, queue: [...script], sending: Promise.resolve() };
    panes.set(el, s);

    if (pre) pre.hidden = true;
    el.appendChild(wrap);
    el.classList.add('live');
    const bar = el.querySelector('.bar');
    if (bar) bar.insertAdjacentHTML('beforeend', '<em class="live-dot">live</em>');
    term.open(host);
    fit.fit();

    // Keystrokes in order: each waits for the one before it.
    const send = data => { s.sending = s.sending.then(() => api('input', id, data)).catch(() => {}); return s.sending; };
    s.send = send;
    term.onData(send);
    // Esc hands the keys back to the deck, and never reaches the shell.
    term.attachCustomKeyEventHandler(e => { if (e.key !== 'Escape') return true; if (e.type === 'keydown') term.blur(); return false; });

    api('open', id, JSON.stringify({ cols: term.cols, rows: term.rows })).then(r => {
      if (!r.ok) throw new Error(r.status);
      let last = `${term.cols}x${term.rows}`;
      new ResizeObserver(() => {
        fit.fit();
        const size = `${term.cols}x${term.rows}`;
        if (size !== last) { last = size; api('resize', id, JSON.stringify({ cols: term.cols, rows: term.rows })).catch(() => {}); }
      }).observe(host);
      const es = new EventSource(`/term/stream?id=${id}&token=${encodeURIComponent(token)}`);
      es.onmessage = e => { const b = atob(e.data); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); term.write(u); };
      es.addEventListener('exit', () => { es.close(); term.write('\r\n\x1b[2m[shell exited — reload to start a new one]\x1b[0m\r\n'); });
    }).catch(() => {
      // The server isn't there: put the static terminal back.
      wrap.remove(); if (pre) pre.hidden = false; el.classList.remove('live'); panes.delete(el);
      el.querySelector('.live-dot')?.remove();
    });

  }

  // Type a command the way a person would, then run it.
  function type(s, line) {
    const chars = [...line];
    let i = 0;
    const tick = () => {
      if (i < chars.length) { s.send(chars[i++]); setTimeout(tick, 18 + Math.random() * 38); }
      else setTimeout(() => s.send('\r'), 160);
    };
    tick();
  }
})();
