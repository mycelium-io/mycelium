// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── The deck ──
// Slides are <section class="slide"> on a 1920x1080 stage scaled to the
// window. Each slide names where its lens sits with data-lens="x y r" in stage
// pixels (comma-separate up to three; "none" for none). Keys are listed in
// the help panel (?). The speaker view (S) is a popup the deck writes itself,
// so it works from file:// with no server.
(function () {
  const deck = document.querySelector('.deck');
  const slides = [...deck.querySelectorAll('.slide')];
  const W = 1920, H = 1080;
  const talk = deck.dataset.talk || '';
  let index = 0, overview = false, scale = 1, ox = 0, oy = 0, speaker = null, started = null;

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window */ } },
  };

  function parseLens(spec) {
    if (!spec || spec === 'none') return [];
    return spec.split(',').map(s => s.trim().split(/\s+/).map(Number)).filter(a => a.length === 3 && a.every(Number.isFinite)).map(([x, y, r]) => ({ x, y, r }));
  }

  // ── Chrome, stagger order, CSS lens fallback ──
  slides.forEach((s, i) => {
    let n = 0;
    s.querySelectorAll('.rise').forEach(el => el.style.setProperty('--i', el.dataset.i ?? n++));
    const first = parseLens(s.dataset.lens)[0];
    if (first) { s.style.setProperty('--lx', first.x + 'px'); s.style.setProperty('--ly', first.y + 'px'); s.style.setProperty('--lr', first.r + 'px'); }
    else s.style.setProperty('--lr', '0px');
    const chrome = document.createElement('div');
    chrome.className = 'chrome';
    chrome.innerHTML = `<img src="../docs/logo.png" alt=""><span>mycelium</span><span class="talk"></span><span class="count"><b>${String(i + 1).padStart(2, '0')}</b> / ${String(slides.length).padStart(2, '0')}</span>`;
    chrome.querySelector('.talk').textContent = deck.dataset.footer || '';
    s.appendChild(chrome);
    s.addEventListener('click', () => { if (overview) { toggleOverview(false); go(i); } });
  });

  const progress = document.querySelector('.progress');

  // ── Fit the stage ──
  function fit() {
    scale = Math.min(innerWidth / W, innerHeight / H);
    ox = (innerWidth - W * scale) / 2; oy = (innerHeight - H * scale) / 2;
    deck.style.transform = `translate(${ox}px, ${oy}px) scale(${scale})`;
    if (overview) layoutOverview();
    pushLens();
  }

  function pushLens() {
    if (!window.Lens) return;
    // The step being shown can move the lens (data-lens on a .step).
    const s = slides[index];
    const shown = steps(s).filter(e => e.classList.contains('shown') && e.dataset.lens);
    const spec = shown.length ? shown[shown.length - 1].dataset.lens : s.dataset.lens;
    const list = overview ? [] : parseLens(spec).map(l => ({ x: ox + l.x * scale, y: oy + l.y * scale, r: l.r * scale }));
    window.Lens.set(list, index, !overview && s.hasAttribute('data-logo'));
  }

  // ── Steps ──
  const steps = s => [...s.querySelectorAll('.step')];
  function markCurrent(s) {
    const st = steps(s), shown = st.filter(e => e.classList.contains('shown'));
    st.forEach(e => e.classList.remove('current'));
    if (shown.length) shown[shown.length - 1].classList.add('current');
  }

  function go(i, { reveal = false } = {}) {
    i = Math.max(0, Math.min(slides.length - 1, i));
    const changed = i !== index;
    slides[index].classList.remove('active');
    index = i;
    const s = slides[index];
    s.classList.add('active');
    // Arriving backwards shows every step; arriving forwards shows none yet.
    steps(s).forEach(e => e.classList.toggle('shown', reveal));
    markCurrent(s);
    progress.style.width = `${(index / Math.max(1, slides.length - 1)) * 100}%`;
    if (location.hash !== '#' + (index + 1)) history.replaceState(null, '', '#' + (index + 1));
    document.title = `${s.dataset.title || 'Slide ' + (index + 1)} · ${talk || 'Mycelium'}`;
    if (started === null && index > 0) started = Date.now();
    window.DeckTerm?.activate(s);
    window.DeckApp?.activate(s);
    pushLens();
    syncSpeaker();
  }

  function next() {
    const hidden = steps(slides[index]).filter(e => !e.classList.contains('shown'));
    if (hidden.length) { hidden[0].classList.add('shown'); markCurrent(slides[index]); pushLens(); syncSpeaker(); return; }
    // A live terminal's commands, then a live app's routes, run one per press, like steps.
    if (window.DeckTerm?.typeNext(slides[index]) || window.DeckApp?.typeNext(slides[index])) { syncSpeaker(); return; }
    go(index + 1);
  }
  function prev() {
    const shown = steps(slides[index]).filter(e => e.classList.contains('shown'));
    if (shown.length) { shown[shown.length - 1].classList.remove('shown'); markCurrent(slides[index]); pushLens(); syncSpeaker(); return; }
    go(index - 1, { reveal: true });
  }

  // ── Overview ──
  function layoutOverview() {
    const cols = 4, gap = 70, tw = (W - gap * (cols + 1)) / cols, ts = tw / W, th = H * ts;
    const rows = Math.ceil(slides.length / cols);
    const total = rows * th + (rows - 1) * gap;
    // Scroll the grid so the current tile is in view.
    const row = Math.floor(index / cols);
    const shift = Math.max(0, Math.min(total - H + 2 * gap, row * (th + gap) - (H - th) / 2));
    slides.forEach((s, i) => {
      const c = i % cols, r = Math.floor(i / cols);
      s.style.transformOrigin = '0 0';
      s.style.transform = `translate(${gap + c * (tw + gap)}px, ${gap + r * (th + gap) - shift}px) scale(${ts})`;
    });
  }
  function toggleOverview(on = !overview) {
    overview = on;
    deck.classList.toggle('overview', overview);
    if (overview) layoutOverview();
    else slides.forEach(s => { s.style.transform = ''; });
    pushLens();
  }

  // ── Theme ──
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    store.set('mycelium-deck-theme', t);
    if (window.Lens) window.Lens.theme(t !== 'light');
    window.DeckTerm?.theme?.();
  }

  // ── Timers: click to start or pause, double-click to reset ──
  document.querySelectorAll('.timer').forEach(el => {
    const total = Math.round(parseFloat(el.dataset.minutes || '10') * 60);
    const r = 250, C = 2 * Math.PI * r;
    el.insertAdjacentHTML('afterbegin', `<svg viewBox="0 0 520 520"><circle class="track" cx="260" cy="260" r="${r}"/><circle class="ring" cx="260" cy="260" r="${r}" stroke-dasharray="${C}" stroke-dashoffset="0"/></svg>`);
    el.insertAdjacentHTML('beforeend', '<div class="readout"><div class="time"></div><div class="hint">click to start</div></div>');
    const ring = el.querySelector('.ring'), time = el.querySelector('.time'), hint = el.querySelector('.hint');
    let left = total, tick = null, end = 0;
    const draw = () => {
      const s = Math.max(0, Math.ceil(left));
      time.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
      ring.style.strokeDashoffset = String(C * (1 - left / total));
      el.classList.toggle('done', left <= 0);
    };
    const stop = () => { clearInterval(tick); tick = null; };
    el.addEventListener('click', e => {
      e.stopPropagation();
      if (overview) return;
      if (tick) { stop(); hint.textContent = 'paused · click to resume'; return; }
      if (left <= 0) left = total;
      end = Date.now() + left * 1000;
      hint.textContent = 'click to pause · double-click to reset';
      tick = setInterval(() => { left = (end - Date.now()) / 1000; if (left <= 0) { left = 0; stop(); hint.textContent = 'time'; } draw(); }, 250);
    });
    el.addEventListener('dblclick', e => { e.stopPropagation(); stop(); left = total; hint.textContent = 'click to start'; draw(); });
    draw();
  });

  // ── Speaker view ──
  function notesOf(s) { const n = s.querySelector('.notes'); return n ? n.innerHTML : '<p class="none">No notes for this slide.</p>'; }
  function titleOf(s) { return s ? (s.dataset.title || '') : ''; }
  function syncSpeaker() {
    if (!speaker || speaker.closed) return;
    const s = slides[index];
    const st = steps(s);
    speaker.postMessage({
      kind: 'state', index, total: slides.length, title: titleOf(s), notes: notesOf(s),
      next: titleOf(slides[index + 1]) || 'End of deck', started,
      steps: [st.length ? `${st.filter(e => e.classList.contains('shown')).length} / ${st.length} steps` : '', window.DeckTerm?.progress(s) || '', window.DeckApp?.progress(s) || ''].filter(Boolean).join(' · '),
    }, '*');
  }
  function openSpeaker() {
    speaker = window.open('', 'mycelium-speaker', 'width=1100,height=720');
    if (!speaker) return;
    speaker.document.open();
    speaker.document.write(SPEAKER_HTML);
    speaker.document.close();
    setTimeout(syncSpeaker, 50);
  }
  addEventListener('message', e => {
    if (!speaker || e.source !== speaker) return;
    const d = e.data || {};
    if (d.kind === 'next') next();
    if (d.kind === 'prev') prev();
    if (d.kind === 'ready') syncSpeaker();
    if (d.kind === 'reset') { started = Date.now(); syncSpeaker(); }
  });

  // ── Keys ──
  const help = document.querySelector('.help'), gotoBox = document.querySelector('.goto');
  let typed = '';
  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (window.DeckTerm?.focused()) return;   // keys belong to the shell until Esc
    const k = e.key;
    // + − 0 zoom a live app on the slide (0 only before a slide number is typed).
    if ((k === '+' || k === '=' || k === '-' || k === '_' || (k === '0' && !typed)) && !overview
        && window.DeckApp?.zoomKey(slides[index], k === '0' ? 0 : (k === '-' || k === '_') ? -1 : 1, e.repeat)) { e.preventDefault(); return; }
    if (/^[0-9]$/.test(k)) { typed += k; gotoBox.textContent = `Go to ${typed}`; gotoBox.classList.add('open'); return; }
    if (k === 'Enter' && typed) { go(parseInt(typed, 10) - 1); typed = ''; gotoBox.classList.remove('open'); return; }
    if (typed && k !== 'Enter') { typed = ''; gotoBox.classList.remove('open'); }
    switch (k) {
      case 'ArrowRight': case 'ArrowDown': case 'PageDown': case ' ': case 'n': e.preventDefault(); if (overview) go(index + 1); else next(); break;
      case 'ArrowLeft': case 'ArrowUp': case 'PageUp': case 'p': e.preventDefault(); if (overview) go(index - 1); else prev(); break;
      case 'Home': go(0); break;
      case 'End': go(slides.length - 1, { reveal: true }); break;
      case 'Enter': if (overview) toggleOverview(false); break;
      case 'o': case 'Escape':
        if (k === 'Escape' && window.DeckInk?.on) { window.DeckInk.off(); break; }
        if (k === 'Escape' && !overview) { help.classList.remove('open'); break; }
        toggleOverview(); break;
      case 'f': if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.(); break;
      case 't': setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'); break;
      case 'b': case '.': document.body.classList.toggle('black'); break;
      case 's': openSpeaker(); break;
      case '?': case 'h': help.classList.toggle('open'); break;
      case 'd': window.DeckInk?.toggle(); break;
      case 'u': if (window.DeckInk?.on) window.DeckInk.undo(); break;
      case 'c': if (window.DeckInk?.on) window.DeckInk.clear(); break;
      default: return;
    }
    if (overview) layoutOverview();
  });

  // Swipe on a touch screen or a tablet remote.
  let tx = null;
  addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, { passive: true });
  addEventListener('touchend', e => {
    if (tx === null) return;
    const dx = e.changedTouches[0].clientX - tx; tx = null;
    if (Math.abs(dx) > 50) (dx < 0 ? next : prev)();
  });
  addEventListener('hashchange', () => { const n = parseInt(location.hash.slice(1), 10); if (n && n - 1 !== index) go(n - 1); });
  addEventListener('resize', fit);

  const SPEAKER_HTML = `<!doctype html><html><head><meta charset="utf-8"><title>Speaker · ${talk}</title>
<style>
  :root{--bg:#0b0d12;--panel:#13171e;--text:#eaecef;--muted:#a9afb7;--accent:#5dd4e0;--border:rgba(255,255,255,.1)}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:400 17px/1.5 "IBM Plex Sans",system-ui,sans-serif;display:grid;grid-template-rows:auto 1fr auto;height:100vh}
  header{display:flex;gap:28px;align-items:baseline;padding:22px 30px;border-bottom:1px solid var(--border)}
  .clock{font:500 44px/1 ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}.elapsed{color:var(--accent)}
  .label{font:500 11px ui-monospace,monospace;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);display:block;margin-bottom:6px}
  main{display:grid;grid-template-columns:1fr 300px;min-height:0}
  .notes{padding:26px 34px;overflow:auto;font-size:26px;line-height:1.5}.notes p{margin:0 0 .7em}.notes li{margin-bottom:.4em}.none{color:var(--muted)}
  aside{border-left:1px solid var(--border);padding:26px;display:flex;flex-direction:column;gap:26px;background:var(--panel)}
  .title{font:italic 600 34px/1.1 Georgia,serif}.next{color:var(--muted);font-size:20px}
  footer{display:flex;gap:10px;padding:16px 30px;border-top:1px solid var(--border)}
  button{font:500 15px ui-monospace,monospace;background:var(--panel);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:12px 20px;cursor:pointer}button:hover{border-color:var(--accent)}
  .spacer{flex:1}
</style></head><body>
<header><div><span class="label">Elapsed</span><span class="clock elapsed" id="el">0:00</span></div><div><span class="label">Clock</span><span class="clock" id="now"></span></div><div class="spacer"></div><div><span class="label">Slide</span><span class="clock" id="pos"></span></div></header>
<main><div class="notes" id="notes"></div><aside><div><span class="label">Now</span><div class="title" id="title"></div><div class="next" id="steps"></div></div><div><span class="label">Next</span><div class="next" id="next"></div></div></aside></main>
<footer><button id="prev">← Prev</button><button id="nextb">Next →</button><div class="spacer"></div><button id="reset">Reset timer</button></footer>
<script>
  let started=null;const $=id=>document.getElementById(id);const send=kind=>opener&&opener.postMessage({kind},'*');
  addEventListener('message',e=>{const d=e.data;if(!d||d.kind!=='state')return;started=d.started;$('pos').textContent=(d.index+1)+' / '+d.total;$('title').textContent=d.title;$('notes').innerHTML=d.notes;$('next').textContent=d.next;$('steps').textContent=d.steps});
  const pad=n=>String(n).padStart(2,'0');
  setInterval(()=>{const t=new Date();$('now').textContent=t.getHours()+':'+pad(t.getMinutes());if(started){const s=Math.floor((Date.now()-started)/1000);$('el').textContent=(s>=3600?Math.floor(s/3600)+':'+pad(Math.floor(s/60)%60):Math.floor(s/60))+':'+pad(s%60)}},500);
  $('prev').onclick=()=>send('prev');$('nextb').onclick=()=>send('next');$('reset').onclick=()=>send('reset');
  addEventListener('keydown',e=>{if(['ArrowRight','ArrowDown','PageDown',' '].includes(e.key)){e.preventDefault();send('next')}if(['ArrowLeft','ArrowUp','PageUp'].includes(e.key)){e.preventDefault();send('prev')}});
  send('ready');
<\/script></body></html>`;

  // ── Start ──
  setTheme(store.get('mycelium-deck-theme') || 'dark');
  const n = parseInt(location.hash.slice(1), 10);
  index = n ? Math.max(0, Math.min(slides.length - 1, n - 1)) : 0;
  slides[index].classList.add('active');
  fit();
  go(index);
})();
