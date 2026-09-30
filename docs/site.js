  // Icons come from a third-party CDN. If it fails to load, the page must still
  // work, a bare lucide.createIcons() here would throw and abort this whole
  // file, taking the nav, theme toggle and background canvas down with it.
  function icons() {
    if (window.lucide && window.lucide.createIcons) window.lucide.createIcons();
  }

  icons();

  // ── Theme (light / dark / system) ──
  // Mirrors the app's ThemeToggle. The pre-paint resolver lives inline in the
  // page head; this owns the menu, persistence, and telling the canvas to
  // repaint on a theme change.
  const THEME_KEY = 'mycelium-theme';
  const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');

  function storedTheme() {
    try { return localStorage.getItem(THEME_KEY) || 'dark'; } catch (e) { return 'dark'; }
  }

  function applyTheme(pref) {
    const dark = pref === 'dark' || (pref === 'system' && themeMedia.matches);
    document.documentElement.classList.toggle('dark', dark);
    const btn = document.getElementById('theme-btn');
    if (btn) {
      btn.innerHTML = '<i data-lucide="' + (dark ? 'moon' : 'sun') + '"></i>';
      icons();
    }
    document.querySelectorAll('[data-theme-set]').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-theme-set') === pref);
    });
    window.dispatchEvent(new CustomEvent('mycelium:theme'));
  }

  function setTheme(pref) {
    try { localStorage.setItem(THEME_KEY, pref); } catch (e) {}
    applyTheme(pref);
  }

  function toggleThemeMenu(e) {
    e.stopPropagation();
    const menu = document.getElementById('theme-menu');
    if (menu) menu.classList.toggle('open');
  }

  document.addEventListener('click', () => {
    const menu = document.getElementById('theme-menu');
    if (menu) menu.classList.remove('open');
  });
  document.querySelectorAll('[data-theme-set]').forEach(b => {
    b.addEventListener('click', () => setTheme(b.getAttribute('data-theme-set')));
  });
  themeMedia.addEventListener('change', () => {
    if (storedTheme() === 'system') applyTheme('system');
  });
  applyTheme(storedTheme());

  // ── Mobile nav drawer (hamburger) ──
  function toggleDrawer(e) {
    if (e) e.stopPropagation();
    const sb = document.getElementById('sidebar');
    const bd = document.getElementById('nav-backdrop');
    const open = sb && sb.classList.toggle('open');
    if (bd) bd.classList.toggle('open', !!open);
    if (open) closeSearchField();
  }
  function closeDrawer() {
    const sb = document.getElementById('sidebar');
    const bd = document.getElementById('nav-backdrop');
    if (sb) sb.classList.remove('open');
    if (bd) bd.classList.remove('open');
  }
  // Close on link tap inside the drawer, on Escape, or when it grows to desktop.
  document.addEventListener('click', (e) => {
    const sb = document.getElementById('sidebar');
    if (sb && sb.classList.contains('open') && sb.contains(e.target) && e.target.closest('a')) {
      closeDrawer();
    }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
  window.addEventListener('resize', () => { if (window.innerWidth > 860) closeDrawer(); });

  // ── Persistent nav tree ──
  // Every page's groups render on every page. The page being read starts open;
  // the reader's own expand/collapse choices win from there and follow them
  // across pages.
  const NAV_KEY = 'mycelium-nav-open';

  function navState() {
    try { return JSON.parse(localStorage.getItem(NAV_KEY) || '{}'); } catch (e) { return {}; }
  }

  function setNavState(key, open) {
    const state = navState();
    state[key] = open;
    try { localStorage.setItem(NAV_KEY, JSON.stringify(state)); } catch (e) {}
  }

  (function initNav() {
    const state = navState();
    document.querySelectorAll('.nav-group').forEach(group => {
      const key = group.getAttribute('data-nav-group');
      const toggle = group.querySelector('.nav-group-toggle');
      if (key in state) {
        group.classList.toggle('collapsed', !state[key]);
      }
      if (toggle) {
        toggle.setAttribute('aria-expanded', String(!group.classList.contains('collapsed')));
        toggle.addEventListener('click', () => {
          const open = group.classList.toggle('collapsed') === false;
          toggle.setAttribute('aria-expanded', String(open));
          setNavState(key, open);
        });
      }
    });
  })();

  // ── Client-side search ──
  // Index is generated with the pages (docs/search-index.js) and pulled in on
  // first use, so it costs nothing until someone actually searches.
  const searchBox = document.getElementById('docsearch');
  const searchToggle = document.getElementById('docsearch-toggle');
  const searchInput = document.getElementById('docsearch-input');
  const searchPanel = document.getElementById('docsearch-panel');
  const searchResults = document.getElementById('docsearch-results');
  let searchIndex = null;
  let searchLoading = null;
  let searchHits = [];
  let searchSelected = -1;

  function loadSearchIndex() {
    if (searchIndex) return Promise.resolve(searchIndex);
    if (searchLoading) return searchLoading;
    searchLoading = new Promise(resolve => {
      const s = document.createElement('script');
      s.src = 'search-index.js';
      s.onload = () => { searchIndex = window.MYCELIUM_SEARCH_INDEX || []; resolve(searchIndex); };
      s.onerror = () => { searchIndex = []; resolve(searchIndex); };
      document.head.appendChild(s);
    });
    return searchLoading;
  }

  // Every token must land somewhere (AND), and where it lands sets its weight:
  // a title beats a breadcrumb beats body prose.
  function scoreRecord(rec, tokens, query) {
    const title = rec.t.toLowerCase();
    const crumb = (rec.s || '').toLowerCase();
    const body = (rec.x || '').toLowerCase();
    let total = 0;
    for (let i = 0; i < tokens.length; i++) {
      const tok = tokens[i];
      const ti = title.indexOf(tok);
      let s;
      if (ti === 0) s = 120;
      else if (ti > 0) s = title[ti - 1] === ' ' ? 90 : 60;
      else if (crumb.indexOf(tok) >= 0) s = 40;
      else {
        const bi = body.indexOf(tok);
        if (bi < 0) return 0;
        s = 22 - Math.min(12, bi / 40);
      }
      total += s;
    }
    if (title.indexOf(query) >= 0) total += 60;
    if (rec.k === 'cmd') total += 15;
    return total;
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  // Match on the raw text, then escape each piece, so a query like "amp" can't
  // find itself inside an entity this function just wrote.
  function highlight(text, tokens) {
    const pattern = tokens
      .filter(Boolean)
      .map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|');
    if (!pattern) return escapeHtml(text);
    const re = new RegExp('(' + pattern + ')', 'gi');
    return text
      .split(re)
      .map((part, i) => (i % 2 ? '<mark>' + escapeHtml(part) + '</mark>' : escapeHtml(part)))
      .join('');
  }

  // A hit's snippet starts at the first matched token, not at the top of the
  // section, so the reader sees the sentence that matched.
  function snippet(rec, tokens) {
    const body = rec.x || '';
    if (!body) return '';
    let at = -1;
    for (let i = 0; i < tokens.length; i++) {
      const j = body.toLowerCase().indexOf(tokens[i]);
      if (j >= 0 && (at < 0 || j < at)) at = j;
    }
    let start = at > 60 ? body.lastIndexOf(' ', at - 50) + 1 : 0;
    const text = (start > 0 ? '…' : '') + body.slice(start, start + 180);
    return highlight(text, tokens);
  }

  function renderHits(tokens) {
    if (!searchHits.length) {
      searchResults.innerHTML = '<div class="docsearch-empty">No matches.</div>';
      return;
    }
    searchResults.innerHTML = searchHits.map((rec, i) => {
      const cls = 'docsearch-hit' + (rec.k === 'cmd' ? ' cmd' : '') + (i === searchSelected ? ' selected' : '');
      const crumb = escapeHtml(rec.p + (rec.s ? ' › ' + rec.s : ''));
      return '<a class="' + cls + '" href="' + rec.u + '" role="option" data-hit="' + i + '">'
        + '<div class="docsearch-crumb">' + crumb + '</div>'
        + '<div class="docsearch-title">' + highlight(rec.t, tokens) + '</div>'
        + '<div class="docsearch-snippet">' + snippet(rec, tokens) + '</div>'
        + '</a>';
    }).join('');
  }

  function closeSearch() {
    if (searchPanel) searchPanel.classList.remove('open');
    if (searchInput) searchInput.setAttribute('aria-expanded', 'false');
    searchSelected = -1;
  }

  // Field is hidden below the layout breakpoint; these calls focus/clear it
  // above that width and are no-ops below it.
  function openSearchField() {
    closeDrawer();
    if (searchBox) searchBox.classList.add('open');
    if (searchToggle) searchToggle.setAttribute('aria-expanded', 'true');
    if (searchInput) searchInput.focus();
  }

  function closeSearchField() {
    closeSearch();
    if (searchBox) searchBox.classList.remove('open');
    if (searchToggle) searchToggle.setAttribute('aria-expanded', 'false');
    if (searchInput) { searchInput.value = ''; searchInput.blur(); }
  }

  if (searchToggle) {
    searchToggle.addEventListener('click', e => {
      e.stopPropagation();
      if (searchBox.classList.contains('open')) closeSearchField();
      else openSearchField();
    });
  }
  // The row is a small-screen affordance; growing past it must not strand it open.
  window.addEventListener('resize', () => {
    if (window.innerWidth > 640 && searchBox) searchBox.classList.remove('open');
  });

  function runSearch() {
    const query = searchInput.value.trim().toLowerCase();
    if (!query) { closeSearch(); return; }
    const tokens = query.split(/\s+/).filter(Boolean);
    loadSearchIndex().then(index => {
      if (searchInput.value.trim().toLowerCase() !== query) return;
      searchHits = index
        .map(rec => ({ rec: rec, score: scoreRecord(rec, tokens, query) }))
        .filter(h => h.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 12)
        .map(h => h.rec);
      searchSelected = searchHits.length ? 0 : -1;
      renderHits(tokens);
      searchPanel.classList.add('open');
      searchInput.setAttribute('aria-expanded', 'true');
    });
  }

  function moveSelection(delta) {
    if (!searchHits.length) return;
    searchSelected = (searchSelected + delta + searchHits.length) % searchHits.length;
    searchResults.querySelectorAll('.docsearch-hit').forEach((el, i) => {
      el.classList.toggle('selected', i === searchSelected);
      if (i === searchSelected) el.scrollIntoView({ block: 'nearest' });
    });
  }

  if (searchInput) {
    searchInput.addEventListener('focus', loadSearchIndex);
    searchInput.addEventListener('input', runSearch);
    searchInput.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); moveSelection(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveSelection(-1); }
      else if (e.key === 'Enter') {
        const hit = searchResults.querySelector('.docsearch-hit.selected');
        if (hit) { e.preventDefault(); window.location.href = hit.getAttribute('href'); closeSearch(); }
      } else if (e.key === 'Escape') { closeSearchField(); }
    });
    document.addEventListener('click', e => {
      if (e.target.closest('#docsearch')) return;
      closeSearch();
      if (searchBox && searchBox.classList.contains('open')) closeSearchField();
    });
    // Same-page hits only move the hash, so close the panel by hand.
    searchResults.addEventListener('click', () => closeSearch());
    // "/" and ⌘K / Ctrl+K jump to the field from anywhere on the page.
    document.addEventListener('keydown', e => {
      const el = document.activeElement;
      const typing = !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault(); openSearchField(); searchInput.select();
      } else if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault(); openSearchField();
      }
    });
  }

  function copyPage() {
    const text = document.querySelector('.main').innerText;
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.querySelector('.copy-page-btn');
      const tokens = Math.round(text.length / 4).toLocaleString();
      btn.innerHTML = '<i data-lucide="check"></i>Copied (~' + tokens + ' tokens)';
      btn.classList.add('copied');
      icons();
      setTimeout(() => {
        btn.innerHTML = '<i data-lucide="copy"></i>Copy page';
        btn.classList.remove('copied');
        icons();
      }, 2000);
    });
  }

  const INSTALL_CMDS = {
    curl: 'curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash',
    brew: 'brew install mycelium-io/tap/mycelium',
    clawhub: 'Tell your agent: "install https://clawhub.ai/juliarvalenti/mycelium-io"',
  };
  function setInstallTab(tab, el) {
    document.getElementById('install-cmd').textContent = INSTALL_CMDS[tab];
    document.querySelectorAll('.install-tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    const btn = document.querySelector('.install-copy-btn');
    btn.innerHTML = '<i data-lucide="copy"></i>';
    btn.classList.remove('copied');
    icons();
  }

  function copyInstallCmd(btn) {
    const cmd = document.getElementById('install-cmd').textContent;
    navigator.clipboard.writeText(cmd).then(() => {
      btn.innerHTML = '<i data-lucide="check"></i>';
      btn.classList.add('copied');
      icons();
      setTimeout(() => {
        btn.innerHTML = '<i data-lucide="copy"></i>';
        btn.classList.remove('copied');
        icons();
      }, 2000);
    });
  }

  // ── Heading tools: copy link, copy section ──
  // Every heading in the doc body carries a chainlink (copies its deep link)
  // and a copy button (copies the section it opens, as markdown). h1s hold no
  // id of their own — the enclosing <section class="doc-section"> holds it —
  // so a heading resolves its anchor from the section it opens.
  const LINK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
  const COPY_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const CHECK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
  const BLOCK_SEL = 'p,h1,h2,h3,h4,h5,h6,pre,ul,ol,table,hr,div,section,blockquote,figure,details';

  function writeClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Fall back to a scratch textarea when opened from disk (file://) or over
    // plain http, where the async clipboard API is unavailable.
    return new Promise((resolve, reject) => {
      const scratch = document.createElement('textarea');
      scratch.value = text;
      scratch.setAttribute('readonly', '');
      scratch.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.appendChild(scratch);
      scratch.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(scratch);
      ok ? resolve() : reject(new Error('copy failed'));
    });
  }

  function flashCopied(el, restore) {
    el.classList.add('copied');
    el.innerHTML = CHECK_SVG;
    setTimeout(() => {
      el.classList.remove('copied');
      el.innerHTML = restore;
    }, 1500);
  }

  function headingAnchorId(heading) {
    if (heading.id) return heading.id;
    const section = heading.closest('section[id]');
    // The heading that opens a section shares the section's id — the one the
    // nav and the search index already point at. Only that heading may claim
    // it, or two headings would answer to the same anchor.
    if (section && section.querySelector('h1, h2, h3, h4') === heading) return section.id;
    // Any other heading the page left without an id (hand-written HTML) gets
    // one derived from its text, in the shape the generator uses.
    const slug = heading.textContent.trim().toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    if (!slug) return null;
    const base = (section ? section.id + '-' : '') + slug;
    let id = base;
    for (let n = 2; document.getElementById(id); n++) id = base + '-' + n;
    heading.id = id;
    return id;
  }

  // A heading owns the siblings that follow it up to the next heading at the
  // same or a higher level, so an h1 takes its whole section, subheads included.
  function headingBlocks(heading) {
    const level = Number(heading.tagName[1]);
    const blocks = [];
    for (let node = heading.nextElementSibling; node; node = node.nextElementSibling) {
      if (/^H[1-6]$/.test(node.tagName) && Number(node.tagName[1]) <= level) break;
      blocks.push(node);
    }
    return blocks;
  }

  function inlineMarkdown(node) {
    if (node.nodeType === 3) return node.nodeValue.replace(/\s+/g, ' ');
    if (node.nodeType !== 1) return '';
    if (node.classList.contains('heading-tools')) return '';
    const tag = node.tagName.toLowerCase();
    if (tag === 'br') return '\n';
    const inner = Array.from(node.childNodes).map(inlineMarkdown).join('');
    if (!inner.trim()) return '';
    switch (tag) {
      case 'code':
      case 'kbd':
        return '`' + inner + '`';
      case 'strong':
      case 'b':
        return '**' + inner + '**';
      case 'em':
      case 'i':
        return '*' + inner + '*';
      case 'a': {
        const href = node.getAttribute('href');
        if (!href) return inner;
        try {
          return '[' + inner + '](' + new URL(href, location.href).href + ')';
        } catch (err) {
          return inner;
        }
      }
      default:
        return inner;
    }
  }

  function listMarkdown(list, depth) {
    const ordered = list.tagName === 'OL';
    const pad = '  '.repeat(depth);
    const lines = [];
    Array.from(list.children).forEach((li, i) => {
      const own = [];
      const nested = [];
      Array.from(li.childNodes).forEach(child => {
        if (child.nodeType === 1 && /^(UL|OL)$/.test(child.tagName)) nested.push(child);
        else own.push(inlineMarkdown(child));
      });
      lines.push(pad + (ordered ? (i + 1) + '. ' : '- ') + own.join('').trim());
      nested.forEach(sub => lines.push(listMarkdown(sub, depth + 1)));
    });
    return lines.join('\n');
  }

  function tableMarkdown(table) {
    const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
      Array.from(tr.children).map(cell =>
        inlineMarkdown(cell).trim().replace(/\|/g, '\\|').replace(/\n/g, ' ')));
    if (!rows.length) return '';
    const width = rows.reduce((w, r) => Math.max(w, r.length), 0);
    const row = cells =>
      '| ' + cells.concat(new Array(width - cells.length).fill('')).join(' | ') + ' |';
    return [row(rows[0]), row(new Array(width).fill('---'))]
      .concat(rows.slice(1).map(row))
      .join('\n');
  }

  function blockMarkdown(node) {
    if (node.nodeType === 3) return node.nodeValue.trim();
    if (node.nodeType !== 1) return '';
    if (node.classList.contains('heading-tools') || node.classList.contains('edit-page')) return '';
    const tag = node.tagName.toLowerCase();
    if (/^h[1-6]$/.test(tag)) return '#'.repeat(Number(tag[1])) + ' ' + inlineMarkdown(node).trim();
    if (tag === 'pre') return '```\n' + node.textContent.replace(/\s+$/, '') + '\n```';
    if (tag === 'ul' || tag === 'ol') return listMarkdown(node, 0);
    if (tag === 'table') return tableMarkdown(node);
    if (tag === 'hr') return '---';
    if (tag === 'script' || tag === 'style') return '';
    if (!node.querySelector(BLOCK_SEL)) return inlineMarkdown(node).trim();
    return Array.from(node.childNodes).map(blockMarkdown).filter(Boolean).join('\n\n');
  }

  function sectionMarkdown(heading) {
    return [blockMarkdown(heading)]
      .concat(headingBlocks(heading).map(blockMarkdown))
      .filter(Boolean)
      .join('\n\n')
      .replace(/\n{3,}/g, '\n\n') + '\n';
  }

  document.querySelectorAll('.main h1, .main h2, .main h3, .main h4').forEach(heading => {
    if (heading.classList.contains('hero-title')) return;
    const id = headingAnchorId(heading);
    if (!id) return;

    const anchor = document.createElement('a');
    anchor.className = 'header-anchor';
    anchor.href = '#' + id;
    anchor.title = 'Copy link to this section';
    anchor.setAttribute('aria-label', 'Copy link to this section');
    anchor.innerHTML = LINK_SVG;
    anchor.addEventListener('click', e => {
      e.preventDefault();
      writeClipboard(location.href.split('#')[0] + '#' + id).then(() => {
        history.pushState(null, '', '#' + id);
        flashCopied(anchor, LINK_SVG);
      });
    });

    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'header-copy';
    copy.title = 'Copy this section as Markdown';
    copy.setAttribute('aria-label', 'Copy this section as Markdown');
    copy.innerHTML = COPY_SVG;
    copy.addEventListener('click', () => {
      writeClipboard(sectionMarkdown(heading)).then(() => flashCopied(copy, COPY_SVG));
    });

    const tools = document.createElement('span');
    tools.className = 'heading-tools';
    tools.appendChild(anchor);
    tools.appendChild(copy);
    heading.appendChild(tools);
  });


  // agents.md is the setup runbook, meant to be handed to an agent whole. The
  // token estimate matches copyPage's: characters over four, close enough to
  // tell a reader whether it fits their context.
  function copyAgentsMd() {
    const btn = document.querySelector('.copy-agents-btn');
    const reset = () => {
      btn.innerHTML = '<i data-lucide="file-text"></i>Copy agents.md';
      btn.classList.remove('copied', 'failed');
      icons();
    };
    fetch('agents.md')
      .then(r => {
        if (!r.ok) throw new Error(r.status);
        return r.text();
      })
      .then(text => navigator.clipboard.writeText(text).then(() => {
        const tokens = Math.round(text.length / 4).toLocaleString();
        btn.innerHTML = '<i data-lucide="check"></i>Copied (~' + tokens + ' tokens)';
        btn.classList.add('copied');
        icons();
        setTimeout(reset, 2000);
      }))
      .catch(() => {
        btn.innerHTML = '<i data-lucide="x"></i>Copy failed';
        btn.classList.add('failed');
        icons();
        setTimeout(reset, 2000);
      });
  }

  // Active nav link tracking
  const sections = document.querySelectorAll('.doc-section[id], section[id]');
  const navLinks = document.querySelectorAll('.nav-link[href^="#"]');

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.id;
        navLinks.forEach(l => l.classList.remove('active'));
        const active = document.querySelector(`.nav-link[href="#${id}"]`);
        if (active) active.classList.add('active');
      }
    });
  }, { rootMargin: '-20% 0px -70% 0px' });

  sections.forEach(s => observer.observe(s));
// ── Glass droplets (background) ──
// The docs' take on the site's glass scene: droplets of iridescent glass (the
// agents) drifting up the page, reaching for each other with thin hyphae that
// carry message pulses. Now and then two drift together and pool into one
// (the outcome), with a ripple where they meet; later a large drop buds a
// small one off again, so the room never empties. Under the cursor, in the
// gutters only, a bead condenses and threads itself to the nearest drop.
//
// Readability comes first: the reading pane and rails are near-opaque and sit
// above this canvas, the scene renders at 1x and ~30fps, it pauses when the
// tab is hidden, and prefers-reduced-motion gets one still frame.
//
// Rendering: a 2D metaball field (compact kernels, so hyphae fuse into the
// drops with a fillet rather than bloating them), lit as a dome. Refraction
// with per-channel dispersion, a thin-film term toward the rim, two softbox
// highlights and a backlit caustic, over a field that is cobalt at the top of
// the page and night (or pale sky, in light) below.
(function () {
  const canvas = document.getElementById('mycelium-bg');
  if (!canvas) return;
  const gl = canvas.getContext('webgl', { antialias: false, alpha: false, premultipliedAlpha: false });
  if (!gl) { document.documentElement.classList.add('no-webgl'); return; }

  const MAX_B = 12;   // droplet slots (the bead takes the last one when present)
  const MAX_L = 24;   // hypha segments: two per link, grown from both ends
  const MAX_P = 8;    // message pulses

  const VERT = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FRAG = [
    'precision highp float;',
    'uniform vec2 uRes;',
    'uniform float uTime,uDark,uDusk,uScroll,uNB,uNL;',
    'uniform vec4 uB[' + MAX_B + '];',   // x, y (device px, y up), radius, film seed
    'uniform vec4 uL[' + MAX_L + '];',   // segment a.xy, b.xy
    'uniform vec3 uP[' + MAX_P + '];',   // pulse x, y, brightness
    'uniform vec4 uRing;',              // x, y, radius, alpha

    'const float T=.4219;',             // (1-.25)^3: a drop's edge sits at its radius
    'float kern(float d2,float R2){float x=1.-d2/R2;return x>0.?x*x*x:0.;}',
    'float seg2(vec2 p,vec2 a,vec2 b){vec2 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/max(dot(ba,ba),1e-4),0.,1.);vec2 q=pa-ba*h;return dot(q,q);}',
    'float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}',
    'vec2 hash2(vec2 p){return fract(sin(vec2(dot(p,vec2(127.1,311.7)),dot(p,vec2(269.5,183.3))))*43758.5453);}',

    'float field(vec2 p,out float seed){',
    '  float f=0.,best=0.;seed=0.;',
    '  for(int i=0;i<' + MAX_B + ';i++){',
    '    if(float(i)>=uNB)break;',
    '    vec2 d=p-uB[i].xy;float R=uB[i].z*2.;',
    '    float k=kern(dot(d,d),R*R);f+=k;',
    '    if(k>best){best=k;seed=uB[i].w;}',
    '  }',
    '  float lr=6.5;',
    '  for(int i=0;i<' + MAX_L + ';i++){',
    '    if(float(i)>=uNL)break;',
    '    f+=.56*kern(seg2(p,uL[i].xy,uL[i].zw),lr*lr);',
    '  }',
    '  return f;',
    '}',
    'float fieldOnly(vec2 p){float s;return field(p,s);}',

    // The page's ground. Dark: night, with the plates' cobalt pooled at the
    // top that fades as you read down. Light: a pale sky with the same cobalt
    // hint, so the drops read as the same glass on a lit field.
    'vec3 ground(vec2 uv){',
    '  float glow=exp(-length((uv-vec2(.8,1.08))*vec2(1.,1.5))*2.4)*(1.-uDusk);',
    '  vec3 night=vec3(.043,.051,.071)+vec3(.05,.2,.58)*glow*.6;',
    '  vec3 sky=mix(vec3(.953,.965,.99),vec3(.84,.89,.98),smoothstep(.1,1.,uv.y));',
    '  sky=mix(sky,vec3(.62,.75,.97),glow*.4);',
    '  return mix(sky,night,uDark);',
    '}',

    // Spores: two parallax layers of motes drifting upward.
    'float spores(vec2 q){',
    '  float acc=0.;',
    '  for(int L=0;L<2;L++){',
    '    float fl=float(L),dens=mix(5.,12.,fl);',
    '    vec2 p=q*dens+vec2(0.,uTime*mix(.05,.025,fl)*dens-uScroll*mix(.00035,.00015,fl)*dens);',
    '    vec2 cell=floor(p),f=fract(p)-.5,h=hash2(cell+fl*17.3);',
    '    if(h.x>.8){',
    '      vec2 o=(hash2(cell+3.1)-.5)*.5;',
    '      float r=mix(.05,.14,h.y)*mix(1.,.6,fl);',
    '      float a=1.-smoothstep(r*mix(.2,.6,fl),r,length(f-o));',
    '      acc+=a*(.6+.4*sin(uTime*1.2+h.y*40.))*mix(.5,1.,fl);',
    '    }',
    '  }',
    '  return acc;',
    '}',

    'vec3 film(float t){return .5+.5*cos(6.28318*(t+vec3(0.,.33,.67)));}',
    'float lift(float f){return f>T?sqrt(1.-exp(-3.2*(f-T)/T)):0.;}',

    'void main(){',
    '  vec2 p=gl_FragCoord.xy,uv=p/uRes;',
    '  float asp=uRes.x/uRes.y;',
    '  vec3 bg=ground(uv);',
    '  float sp=spores(vec2(uv.x*asp,uv.y));',
    '  bg=mix(bg+sp*vec3(.45,.9,1.)*.16,mix(bg,vec3(.2,.4,.85),sp*.22),1.-uDark);',

    '  float seed;float f=field(p,seed);',
    '  float fx=fieldOnly(p+vec2(1.5,0.)),fy=fieldOnly(p+vec2(0.,1.5));',
    '  vec2 gF=vec2(fx-f,fy-f)/1.5;',
    '  float dist=(f-T)/max(length(gF),1e-4);',          // signed px to the surface
    '  float cov=clamp(dist*.8+.5,0.,1.);',

    // Outside: a faint cyan breath around each drop on the night side.
    '  vec3 col=bg;',
    '  if(dist<0.){col+=vec3(.2,.6,.95)*.07*exp(dist/7.)*uDark;}',

    '  if(cov>0.){',
    '    float h=lift(f),hx=lift(fx),hy=lift(fy);',
    '    vec3 n=normalize(vec3(-(hx-h)/1.5*30.,-(hy-h)/1.5*30.,1.));',
    '    vec2 off=n.xy*26./uRes;',
    '    vec3 refr=vec3(ground(uv+off).r,ground(uv+off*1.15).g,ground(uv+off*1.3).b);',
    '    vec3 body=mix(mix(refr,vec3(.42,.64,.97),.34),mix(refr,vec3(.16,.5,1.),.66)*(.85+.55*h),uDark);',
    '    float fres=pow(1.-n.z,1.4);',
    // Film thickness pools across the surface, so colour sweeps through the
    // body in bands (the plates' look) and is strongest toward the rim.
    '    float swirl=sin(dot(n.xy,vec2(3.1,-2.3))+seed*9.+uTime*.35)*.22+sin(n.x*5.3-n.y*4.1+uTime*.2)*.12;',
    '    float thick=h*.55+seed+swirl+fres*.6+uTime*.015;',
    '    vec3 fc=film(thick);',
    '    fc=mix(fc*.8+.08,fc*1.05,uDark);',
    '    vec3 g=mix(body,fc,clamp(.3+fres*.66,0.,1.));',
    // Light: a darker lip so a drop keeps its edge on a pale field.
    '    g*=1.-(1.-uDark)*.28*smoothstep(.55,1.,fres);',
    '    vec3 L=normalize(vec3(-.45,.55,.7));',
    '    float sh=max(dot(n,normalize(L+vec3(0.,0.,1.))),0.);',
    '    float spec=pow(sh,220.)*1.6+pow(sh,28.)*.28;',
    '    spec+=pow(max(dot(n,normalize(vec3(.5,-.45,.75)+vec3(0.,0.,1.))),0.),36.)*.22;',
    '    float caus=smoothstep(.25,.9,fres)*max(dot(normalize(n.xy+1e-5),-normalize(L.xy)),0.);',
    '    g+=spec+caus*vec3(.55,.95,1.)*.45;',
    '    col=mix(col,g,cov*.96);',
    '  }',

    // Message pulses, riding the hyphae.
    '  for(int i=0;i<' + MAX_P + ';i++){',
    '    vec2 d=p-uP[i].xy;',
    '    col+=vec3(.75,1.,1.)*exp(-dot(d,d)/28.)*uP[i].z;',
    '    col+=vec3(.3,.8,1.)*exp(-dot(d,d)/400.)*uP[i].z*.18*uDark;',
    '  }',

    // The ripple where two drops became one.
    '  if(uRing.w>0.){',
    '    float rd=abs(length(p-uRing.xy)-uRing.z);',
    '    float ra=exp(-rd*rd/18.)*uRing.w;',
    '    vec3 rc=film(uRing.z*.006+uTime*.1);',
    '    col=mix(col,rc,ra*.55);',
    '  }',
    '  col+=(hash(p+fract(uTime))-.5)/255.;',   // dither: no banding in the ground
    '  gl_FragColor=vec4(col,1.);',
    '}',
  ].join('\n');

  function compile(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.warn('glass shader:', gl.getShaderInfoLog(s));
      return null;
    }
    return s;
  }
  const vs = compile(gl.VERTEX_SHADER, VERT);
  const fs = compile(gl.FRAGMENT_SHADER, FRAG);
  const prog = gl.createProgram();
  if (vs && fs) { gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog); }
  if (!vs || !fs || !gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    document.documentElement.classList.add('no-webgl');
    return;
  }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const aLoc = gl.getAttribLocation(prog, 'a');
  gl.enableVertexAttribArray(aLoc);
  gl.vertexAttribPointer(aLoc, 2, gl.FLOAT, false, 0, 0);

  const U = {};
  ['uRes', 'uTime', 'uDark', 'uDusk', 'uScroll', 'uNB', 'uNL', 'uB', 'uL', 'uP', 'uRing']
    .forEach(n => { U[n] = gl.getUniformLocation(prog, n); });
  const bArr = new Float32Array(MAX_B * 4);
  const lArr = new Float32Array(MAX_L * 4);
  const pArr = new Float32Array(MAX_P * 3);

  const still = window.matchMedia('(prefers-reduced-motion: reduce)');

  // ── Theme ──
  let dark = 1, darkTarget = 1;
  function readTheme() { darkTarget = document.documentElement.classList.contains('dark') ? 1 : 0; }
  readTheme();
  dark = darkTarget;
  window.addEventListener('mycelium:theme', () => { readTheme(); wake(); });

  // ── Size ──
  // CSS px for the simulation; the drawing buffer is 1x, since this is a
  // background and the reading surfaces above it carry the crisp edges.
  let W = 0, H = 0;
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W; canvas.height = H;
    canvas.style.width = '100%'; canvas.style.height = '100%';
    gl.viewport(0, 0, W, H);
  }
  resize();

  // ── Scene ──
  let nextId = 1;
  const rand = (a, b) => a + Math.random() * (b - a);
  // Phones have no gutters to speak of: fewer, smaller drops at the edges.
  const small = () => W < 760;
  const target = () => small() ? 4 : Math.max(6, Math.min(MAX_B - 1, Math.round(W * H / 120000)));
  const drops = [];

  // Where a drop can be seen: the gutters beside the reading pane and rail.
  // Most drops start there; a few drift behind the pane as a soft glow.
  let spanW = Infinity;   // width of the gutter the last freeX() picked
  function freeX() {
    spanW = Infinity;
    const spans = [];
    const pane = document.querySelector('.main-inner');
    const rail = document.querySelector('.sidebar');
    const left = rail && rail.offsetParent !== null ? rail.getBoundingClientRect().right : 0;
    if (pane) {
      const r = pane.getBoundingClientRect();
      if (r.left - left > 40) spans.push([left, r.left]);
      if (W - r.right > 40) spans.push([r.right, W]);
    }
    const total = spans.reduce((n, s) => n + s[1] - s[0], 0);
    if (!total || Math.random() < 0.2) return rand(0, W);
    let k = Math.random() * total;
    for (const s of spans) {
      if (k <= s[1] - s[0]) { spanW = s[1] - s[0]; return s[0] + k; }
      k -= s[1] - s[0];
    }
    return rand(0, W);
  }

  function makeDrop(x, y, r) {
    r = r || Math.min((12 + Math.pow(Math.random(), 1.8) * 50) * (small() ? 0.55 : 1), Math.max(10, spanW * 0.3));
    return {
      id: nextId++, x: x, y: y, r: r, tr: r,
      z: 0.35 + Math.min(1, r / 62) * 0.65,
      ph: rand(0, 6.28), seed: Math.random(),
      pair: null, dying: false, bud: null,
    };
  }
  for (let i = 0; i < target(); i++) drops.push(makeDrop(freeX(), rand(0, H)));

  const links = new Map();      // "a-b" → { a, b, g }
  const pulses = [];
  let ring = null;
  const bead = { x: 0, y: 0, tx: 0, ty: 0, r: 0, on: false, id: 0 };

  let t = 0;
  let nextMerge = rand(5, 8);
  let nextBud = Infinity;
  let nextPulse = 1;

  // Scroll: drops ride with the page at their depth, so the scene has parallax.
  let lastScroll = window.scrollY;
  function onScroll() {
    const ds = window.scrollY - lastScroll;
    lastScroll = window.scrollY;
    // A jump (an anchor link, search) would carry every drop off at once and
    // leave the gutters empty; condense a fresh scene in place instead.
    if (Math.abs(ds) > H * 0.6) {
      links.clear();
      pulses.length = 0;
      for (const d of drops) {
        d.pair = null; d.bud = null;
        d.x = freeX(); d.y = rand(0, H); d.r = 0.5;
      }
      wake();
      return;
    }
    for (const d of drops) d.y -= ds * (0.1 + 0.3 * d.z);
    wake();
  }
  window.addEventListener('scroll', onScroll, { passive: true });

  // The bead lives in the gutters only: over prose or chrome, it lets go.
  window.addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse') return;
    const over = e.target && e.target.closest &&
      e.target.closest('.main-inner, .sidebar, .topnav, .docs-footer, .lightbox-overlay');
    bead.on = !over;
    bead.tx = e.clientX; bead.ty = e.clientY;
    if (bead.r < 0.5) { bead.x = bead.tx; bead.y = bead.ty; }
  }, { passive: true });
  document.addEventListener('pointerleave', () => { bead.on = false; });

  function startMerge() {
    let best = null, bd = Infinity;
    for (let i = 0; i < drops.length; i++) {
      const a = drops[i];
      if (a.pair || a.dying || a.bud || a.y < 0 || a.y > H) continue;
      for (let j = i + 1; j < drops.length; j++) {
        const b = drops[j];
        if (b.pair || b.dying || b.bud || b.y < 0 || b.y > H) continue;
        if (a.r + b.r > 110) continue;
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < 380 && d < bd) { bd = d; best = [a, b]; }
      }
    }
    if (best) { best[0].pair = best[1]; best[1].pair = best[0]; }
  }

  function startBud() {
    let p = null;
    for (const d of drops) {
      if (d.dying || d.pair || d.bud || d.y < 40 || d.y > H - 40) continue;
      if (d.r > 34 && (!p || d.r > p.r)) p = d;
    }
    if (!p) {
      // Nothing big enough on screen: condense a fresh one below the fold.
      drops.push(makeDrop(freeX(), H + 80));
      return;
    }
    const r0 = p.r * rand(0.4, 0.5);
    p.tr = Math.sqrt(Math.max(p.r * p.r - r0 * r0, 100));
    const c = makeDrop(p.x, p.y, r0);
    c.r = 0.5;
    const ang = rand(0, Math.PI * 2);
    c.bud = { from: p, ang: ang, t: 0, dist: (p.tr + r0) * 1.35 };
    drops.push(c);
  }

  function step(dt) {
    t += dt;
    dark += (darkTarget - dark) * Math.min(1, dt * 5);

    // Motion: an upward drift, faster for the near (bigger) drops.
    for (const d of drops) {
      d.r += (d.tr - d.r) * Math.min(1, dt * (d.dying ? 5 : 1.4));
      if (d.bud) {
        const b = d.bud;
        b.t += dt / 2.6;
        const e = 1 - Math.pow(1 - Math.min(b.t, 1), 3);
        d.x = b.from.x + Math.cos(b.ang) * b.dist * e;
        d.y = b.from.y + Math.sin(b.ang) * b.dist * e;
        if (b.t >= 1 || b.from.dying) d.bud = null;
        continue;
      }
      if (d.dying && d.pair) {
        d.x += (d.pair.x - d.x) * Math.min(1, dt * 6);
        d.y += (d.pair.y - d.y) * Math.min(1, dt * 6);
        continue;
      }
      d.x += Math.sin(t * 0.12 + d.ph) * 5 * d.z * dt;
      d.y -= (5 + 11 * d.z) * dt;
      if (d.pair && !d.dying) {
        const o = d.pair, dx = o.x - d.x, dy = o.y - d.y, dist = Math.hypot(dx, dy) || 1;
        const pull = Math.min(46, dist * 0.9) * (o.r * o.r) / (o.r * o.r + d.r * d.r) * 2;
        d.x += dx / dist * pull * dt;
        d.y += dy / dist * pull * dt;
      }
    }

    // Separation between drops that aren't meant to meet.
    for (let i = 0; i < drops.length; i++) {
      const a = drops[i];
      if (a.dying || a.bud) continue;
      for (let j = i + 1; j < drops.length; j++) {
        const b = drops[j];
        if (b.dying || b.bud || a.pair === b) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
        // Far enough apart that their fields don't bridge: only a merge pools.
        const min = (a.r + b.r) * 1.5;
        if (d < min) {
          const push = (min - d) * Math.min(1, dt * 2) * 0.5;
          a.x -= dx / d * push; a.y -= dy / d * push;
          b.x += dx / d * push; b.y += dy / d * push;
        }
      }
    }

    // Merges complete once the necks have pooled.
    for (const a of drops) {
      const b = a.pair;
      if (!b || a.dying || b.dying) continue;
      if (Math.hypot(a.x - b.x, a.y - b.y) < (a.r + b.r) * 0.5) {
        const [big, small] = a.r >= b.r ? [a, b] : [b, a];
        const A = big.r * big.r, B = small.r * small.r;
        big.tr = Math.min(80, Math.sqrt(A + B));
        big.x = (big.x * A + small.x * B) / (A + B);
        big.y = (big.y * A + small.y * B) / (A + B);
        big.pair = null;
        small.dying = true; small.tr = 0; small.pair = big;
        big.seed = (big.seed + small.seed) * 0.5;
        ring = { x: big.x, y: big.y, t: 0, r0: big.tr };
        nextBud = t + rand(4, 7);
      }
    }
    for (let i = drops.length - 1; i >= 0; i--) {
      if (drops[i].dying && drops[i].r < 0.6) drops.splice(i, 1);
    }

    // Wrap: off the top comes back from below, and the other way on scroll up.
    for (const d of drops) {
      if (d.bud || d.dying) continue;
      const m = d.r * 2.2 + 20;
      if (d.y < -m) { d.y = H + m + rand(0, 80); d.x = freeX(); breakPair(d); }
      else if (d.y > H + m + 120) { d.y = -m; d.x = freeX(); breakPair(d); }
      if (d.x < -m) d.x += W + 2 * m;
      else if (d.x > W + m) d.x -= W + 2 * m;
    }

    if (t > nextMerge) { startMerge(); nextMerge = t + rand(9, 14); }
    const alive = drops.filter(d => !d.dying).length;
    if (t > nextBud || (alive < target() && nextBud === Infinity)) {
      if (alive < target()) startBud();
      nextBud = Infinity;
    }

    // Bead: condenses under the cursor, in the gutters.
    bead.x += (bead.tx - bead.x) * Math.min(1, dt * 9);
    bead.y += (bead.ty - bead.y) * Math.min(1, dt * 9);
    bead.r += ((bead.on ? 7 : 0) - bead.r) * Math.min(1, dt * 4);

    updateLinks(dt);
    updatePulses(dt);
    if (ring) { ring.t += dt; if (ring.t > 1.8) ring = null; }
  }

  // A drop that wraps around lets go of everything it held: its partner and
  // its hyphae, which would otherwise stretch across the screen as they fade.
  function breakPair(d) {
    if (d.pair) { d.pair.pair = null; d.pair = null; }
    for (const [key, l] of links) if (l.a === d || l.b === d) links.delete(key);
  }

  // Would a hypha from a to b pass through c? Then it doesn't grow.
  function threads(c, a, b) {
    const bx = b.x - a.x, by = b.y - a.y;
    const h = Math.max(0, Math.min(1, ((c.x - a.x) * bx + (c.y - a.y) * by) / (bx * bx + by * by || 1)));
    return Math.hypot(c.x - a.x - bx * h, c.y - a.y - by * h) < c.r * 1.6 + 8;
  }

  function updateLinks(dt) {
    // Candidates: near neighbours, at most three hyphae per drop.
    const want = new Set();
    const pairs = [];
    const live = drops.filter(d => !d.dying && d.r > 4);
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const a = live[i], b = live[j];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const reach = Math.min(300, (a.r + b.r) * 2.8 + 90);
        if (d < reach && !live.some(c => c !== a && c !== b && threads(c, a, b))) pairs.push([d, a, b]);
      }
    }
    pairs.sort((p, q) => p[0] - q[0]);
    const deg = new Map();
    for (const [, a, b] of pairs) {
      if ((deg.get(a) || 0) >= 3 || (deg.get(b) || 0) >= 3) continue;
      if (want.size >= (MAX_L - 2) / 2) break;
      deg.set(a, (deg.get(a) || 0) + 1);
      deg.set(b, (deg.get(b) || 0) + 1);
      const key = a.id < b.id ? a.id + '-' + b.id : b.id + '-' + a.id;
      want.add(key);
      if (!links.has(key)) links.set(key, { a: a, b: b, g: 0 });
    }
    for (const [key, l] of links) {
      if (want.has(key)) l.g = Math.min(1, l.g + dt * 0.7);
      else if (Math.hypot(l.a.x - l.b.x, l.a.y - l.b.y) > 420) links.delete(key);
      else {
        l.g -= dt * 1.4;
        if (l.g <= 0 || l.a.dying || l.b.dying || !drops.includes(l.a) || !drops.includes(l.b)) links.delete(key);
      }
    }
  }

  function updatePulses(dt) {
    if (t > nextPulse) {
      nextPulse = t + rand(0.5, 1.3);
      const grown = [...links.values()].filter(l => l.g >= 1);
      if (grown.length && pulses.length < MAX_P) {
        const l = grown[Math.floor(Math.random() * grown.length)];
        const fwd = Math.random() < 0.5;
        const len = Math.hypot(l.a.x - l.b.x, l.a.y - l.b.y);
        pulses.push({ l: l, fwd: fwd, t: 0, dur: 1 + len / 240 });
      }
    }
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i];
      p.t += dt / p.dur;
      if (p.t >= 1 || p.l.g < 1) pulses.splice(i, 1);
    }
  }

  // ── Upload + draw ──
  function draw() {
    const scroll = window.scrollY;
    const slots = [];
    for (const d of drops) if (d.r > 0.4) slots.push(d);
    slots.sort((a, b) => b.r - a.r);
    slots.length = Math.min(slots.length, MAX_B - 1);
    let nb = 0;
    const put = (x, y, r, s) => {
      bArr[nb * 4] = x; bArr[nb * 4 + 1] = H - y; bArr[nb * 4 + 2] = r; bArr[nb * 4 + 3] = s; nb++;
    };
    for (const d of slots) put(d.x, d.y, d.r * (1 + 0.025 * Math.sin(t * 0.8 + d.ph)), d.seed);

    let nl = 0;
    const seg = (ax, ay, bx, by) => {
      if (nl >= MAX_L) return;
      lArr[nl * 4] = ax; lArr[nl * 4 + 1] = H - ay; lArr[nl * 4 + 2] = bx; lArr[nl * 4 + 3] = H - by; nl++;
    };
    const ease = g => g * g * (3 - 2 * g);
    for (const l of links.values()) {
      if (!slots.includes(l.a) || !slots.includes(l.b)) continue;
      // Rooted at each drop's surface and grown toward the middle, so a
      // hypha reaches out of the glass rather than ridging through it.
      const len = Math.hypot(l.b.x - l.a.x, l.b.y - l.a.y) || 1;
      const ux = (l.b.x - l.a.x) / len, uy = (l.b.y - l.a.y) / len;
      const ax = l.a.x + ux * l.a.r * 0.8, ay = l.a.y + uy * l.a.r * 0.8;
      const bx = l.b.x - ux * l.b.r * 0.8, by = l.b.y - uy * l.b.r * 0.8;
      const g = ease(Math.max(0, l.g)) * 0.5;
      seg(ax, ay, ax + (bx - ax) * g, ay + (by - ay) * g);
      seg(bx, by, bx - (bx - ax) * g, by - (by - ay) * g);
    }
    if (bead.r > 0.4 && nb < MAX_B) {
      put(bead.x, bead.y, bead.r, 0.62);
      let near = null, nd = 240;
      for (const d of slots) {
        const dd = Math.hypot(d.x - bead.x, d.y - bead.y) - d.r;
        if (dd < nd) { nd = dd; near = d; }
      }
      if (near) {
        const g = Math.min(1, bead.r / 7);
        seg(bead.x, bead.y, bead.x + (near.x - bead.x) * g, bead.y + (near.y - bead.y) * g);
      }
    }

    pArr.fill(0);
    pulses.forEach((p, i) => {
      const k = p.fwd ? p.t : 1 - p.t;
      const e = k * k * (3 - 2 * k);
      pArr[i * 3] = p.l.a.x + (p.l.b.x - p.l.a.x) * e;
      pArr[i * 3 + 1] = H - (p.l.a.y + (p.l.b.y - p.l.a.y) * e);
      pArr[i * 3 + 2] = Math.sin(Math.PI * p.t) * 0.9;
    });

    gl.uniform2f(U.uRes, W, H);
    gl.uniform1f(U.uTime, t);
    gl.uniform1f(U.uDark, dark);
    gl.uniform1f(U.uDusk, Math.min(1, scroll / 900));
    gl.uniform1f(U.uScroll, scroll);
    gl.uniform1f(U.uNB, nb);
    gl.uniform1f(U.uNL, nl);
    gl.uniform4fv(U.uB, bArr);
    gl.uniform4fv(U.uL, lArr);
    gl.uniform3fv(U.uP, pArr);
    if (ring) {
      const k = ring.t / 1.8;
      gl.uniform4f(U.uRing, ring.x, H - ring.y, ring.r0 + (1 - Math.pow(1 - k, 3)) * 160, (1 - k) * 0.8);
    } else {
      gl.uniform4f(U.uRing, 0, 0, 0, 0);
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  // ── Loop ──
  // ~30fps is plenty for drift this slow, and halves the cost of a background.
  let raf = 0, last = 0;
  function frame(now) {
    raf = 0;
    if (document.hidden) return;
    if (still.matches) { draw(); return; }
    raf = requestAnimationFrame(frame);
    if (now - last < 32) return;
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / 30;
    last = now;
    step(dt);
    draw();
  }
  function wake() { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } }

  // Settle the scene before first paint, so hyphae are already grown.
  for (let i = 0; i < 90; i++) step(1 / 30);
  for (const l of links.values()) l.g = 1;

  window.addEventListener('resize', () => { resize(); wake(); });
  document.addEventListener('visibilitychange', wake);
  still.addEventListener('change', wake);
  wake();
})();

// ── Diagram lightbox ──
// A doc-img (an architecture diagram embedded via markdown) opens full-size
// on click. Self-contained: builds its own overlay, no markup needed in the
// generated HTML beyond the <img class="doc-img">.
(function () {
  var overlay = null;

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    document.removeEventListener('keydown', onKey);
  }

  function onKey(e) {
    if (e.key === 'Escape') close();
  }

  function open(img) {
    close();
    overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    var full = document.createElement('img');
    full.src = img.src;
    full.alt = img.alt;
    overlay.appendChild(full);
    overlay.addEventListener('click', close);
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKey);
  }

  document.addEventListener('click', function (e) {
    var img = e.target.closest('.doc-img');
    if (img) open(img);
  });
})();
