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
(function() {
  const canvas = document.getElementById('mycelium-bg');
  const ctx = canvas.getContext('2d');

  // ── Pixelated grid ──
  const CELL = 8;
  const cols = 480, rows = 270;
  // Two layers: structure (permanent network) and flow (nutrient transport)
  var structure = new Float32Array(cols * rows);  // permanent hypha map
  var trail = new Float32Array(cols * rows);       // animated nutrient flow
  var colorIdx = new Uint8Array(cols * rows);

  // ── Palette ──
  // Read from the stylesheet so the network tracks the active theme.
  // Three depths of one accent provide variation without a second hue.
  var BG = { r: 12, g: 14, b: 17 };
  var COLORS = [{ r: 92, g: 199, b: 210 }, { r: 92, g: 199, b: 210 }, { r: 92, g: 199, b: 210 }];
  var INK_ALPHA = 1;

  function hexToRgb(hex) {
    var h = hex.trim().replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
    };
  }

  function mix(a, b, t) {
    return {
      r: Math.round(a.r + (b.r - a.r) * t),
      g: Math.round(a.g + (b.g - a.g) * t),
      b: Math.round(a.b + (b.b - a.b) * t),
    };
  }

  function readPalette() {
    var cs = getComputedStyle(document.documentElement);
    var bg = cs.getPropertyValue('--canvas-bg');
    var ink = cs.getPropertyValue('--canvas-ink').split(',');
    var alpha = parseFloat(cs.getPropertyValue('--canvas-alpha'));
    if (bg) BG = hexToRgb(bg);
    if (ink.length === 3) {
      var base = { r: +ink[0], g: +ink[1], b: +ink[2] };
      // Three depths of one accent: enough variation to read as separate
      // colonies, without spending a second hue.
      COLORS = [base, mix(base, BG, 0.28), mix(base, BG, 0.5)];
    }
    if (!isNaN(alpha)) INK_ALPHA = alpha;
  }

  readPalette();
  window.addEventListener('mycelium:theme', readPalette);

  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.imageRendering = 'pixelated';

  var viewCols, viewRows;
  function resize() {
    viewCols = Math.min(Math.ceil(window.innerWidth / CELL), cols);
    viewRows = Math.min(Math.ceil(window.innerHeight / CELL), rows);
    canvas.width = viewCols;
    canvas.height = viewRows;
  }
  window.addEventListener('resize', resize);
  resize();

  // ══════════════════════════════════════════════════════════════════
  // LAYER 1: Tip-growth (Meškauskas et al.), builds the network
  // ══════════════════════════════════════════════════════════════════

  const TIP_SPEED = 0.25;
  const BRANCH_PROB = 0.015;
  const BRANCH_ANGLE_MIN = 0.4;
  const BRANCH_ANGLE_MAX = 1.1;
  const WANDER = 0.1;
  const MAX_TIPS = 1200;

  var tips = [];

  function depositStructure(x, y, ci, gen) {
    var gx = Math.floor(x), gy = Math.floor(y);
    var strength = 0.5 / (1 + gen * 0.25);
    var radius = gen < 2 ? 1 : 0;
    for (var dy = -radius; dy <= radius; dy++) {
      for (var dx = -radius; dx <= radius; dx++) {
        var px = gx + dx, py = gy + dy;
        if (px >= 0 && px < cols && py >= 0 && py < rows) {
          var idx = py * cols + px;
          var str = (dx === 0 && dy === 0) ? strength : strength * 0.4;
          structure[idx] = Math.min(1.0, structure[idx] + str);
          colorIdx[idx] = ci;
        }
      }
    }
  }

  function isOccupied(x, y) {
    var gx = Math.floor(x), gy = Math.floor(y);
    if (gx < 0 || gx >= cols || gy < 0 || gy >= rows) return true;
    return structure[gy * cols + gx] > 0.2;
  }

  function seedColony(cx, cy, ci, n) {
    for (var i = 0; i < n; i++) {
      var angle = (Math.PI * 2 * i) / n + (Math.random() - 0.5) * 0.5;
      tips.push({
        x: cx + Math.cos(angle) * 2,
        y: cy + Math.sin(angle) * 2,
        angle: angle, ci: ci, age: 0, gen: 0,
        maxAge: 1500 + Math.floor(Math.random() * 3000),
        speed: TIP_SPEED * (0.7 + Math.random() * 0.6),
      });
    }
    depositStructure(cx, cy, ci, 0);
  }

  function growStep() {
    var newTips = [];
    for (var i = tips.length - 1; i >= 0; i--) {
      var t = tips[i];
      t.age++;

      t.angle += (Math.random() - 0.5) * WANDER * 2;

      var nx = t.x + Math.cos(t.angle) * t.speed;
      var ny = t.y + Math.sin(t.angle) * t.speed;

      if (nx < 0 || nx >= cols || ny < 0 || ny >= rows || t.age > t.maxAge) {
        tips.splice(i, 1);
        continue;
      }

      if (t.age > 50 && isOccupied(nx, ny)) {
        depositStructure(nx, ny, t.ci, t.gen);
        tips.splice(i, 1);
        continue;
      }

      depositStructure(t.x, t.y, t.ci, t.gen);
      t.x = nx; t.y = ny;

      // Sporulation
      if (t.age > 300 && t.age % 150 === 0 && Math.random() < 0.12) {
        seedColony(t.x, t.y, t.ci, 2);
      }

      // Branching
      if (tips.length + newTips.length < MAX_TIPS && Math.random() < BRANCH_PROB && t.age > 10) {
        var bAngle = BRANCH_ANGLE_MIN + Math.random() * (BRANCH_ANGLE_MAX - BRANCH_ANGLE_MIN);
        var sign = Math.random() < 0.5 ? -1 : 1;
        newTips.push({
          x: t.x, y: t.y,
          angle: t.angle + sign * bAngle,
          ci: t.ci, age: 0, gen: t.gen + 1,
          maxAge: 600 + Math.floor(Math.random() * 1500),
          speed: t.speed * (0.75 + Math.random() * 0.25),
        });
      }
    }
    for (var j = 0; j < newTips.length; j++) {
      if (tips.length < MAX_TIPS) tips.push(newTips[j]);
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // LAYER 2: Nutrient agents (Physarum-style), flow through network
  // ══════════════════════════════════════════════════════════════════
  // These agents are constrained to the established network.
  // They follow trails and re-deposit, creating organic pulsing.

  var agents = [];
  const MAX_AGENTS = 600;
  const SENSOR_DIST = 6;
  const SENSOR_ANGLE = 0.6;

  function spawnAgentOnNetwork() {
    // Find a random occupied cell to spawn on
    for (var attempt = 0; attempt < 20; attempt++) {
      var x = Math.random() * viewCols;
      var y = Math.random() * viewRows;
      var gx = Math.floor(x), gy = Math.floor(y);
      if (gx >= 0 && gx < cols && gy >= 0 && gy < rows && structure[gy * cols + gx] > 0.1) {
        agents.push({
          x: x, y: y,
          angle: Math.random() * Math.PI * 2,
          ci: colorIdx[gy * cols + gx],
          speed: 0.08 + Math.random() * 0.1,
        });
        return;
      }
    }
  }

  function senseTrail(ax, ay, angle, offset) {
    var sx = Math.floor(ax + Math.cos(angle + offset) * SENSOR_DIST);
    var sy = Math.floor(ay + Math.sin(angle + offset) * SENSOR_DIST);
    if (sx < 0 || sx >= cols || sy < 0 || sy >= rows) return 0;
    // Sense both structure and flow trail, prefer flowing along the network
    return structure[sy * cols + sx] * 0.5 + trail[sy * cols + sx];
  }

  // ══════════════════════════════════════════════════════════════════
  // PRE-WARM: Build the network before first render
  // ══════════════════════════════════════════════════════════════════

  var numColonies = 15 + Math.floor(Math.random() * 8);
  for (var c = 0; c < numColonies; c++) {
    seedColony(
      15 + Math.random() * (viewCols - 30),
      15 + Math.random() * (viewRows - 30),
      Math.floor(Math.random() * COLORS.length),
      2 + Math.floor(Math.random() * 3)
    );
  }

  for (var warm = 0; warm < 4000; warm++) {
    growStep();
  }

  for (var a = 0; a < MAX_AGENTS; a++) {
    spawnAgentOnNetwork();
  }

  for (var warm = 0; warm < 200; warm++) {
    for (var i = 0; i < trail.length; i++) {
      trail[i] *= 0.995;
    }
    for (var i = 0; i < agents.length; i++) {
      var a = agents[i];
      var sL = senseTrail(a.x, a.y, a.angle, -SENSOR_ANGLE);
      var sC = senseTrail(a.x, a.y, a.angle, 0);
      var sR = senseTrail(a.x, a.y, a.angle, SENSOR_ANGLE);
      var turn = 0.08 + Math.random() * 0.06;
      if (sC >= sL && sC >= sR) a.angle += (Math.random() - 0.5) * 0.3;
      else if (sL > sR) a.angle -= turn;
      else a.angle += turn;
      a.x += Math.cos(a.angle) * a.speed;
      a.y += Math.sin(a.angle) * a.speed;
      if (a.x < 0) a.x += cols; if (a.x >= cols) a.x -= cols;
      if (a.y < 0) a.y += rows; if (a.y >= rows) a.y -= rows;
      var gx = Math.floor(a.x), gy = Math.floor(a.y);
      if (gx >= 0 && gx < cols && gy >= 0 && gy < rows) {
        trail[gy * cols + gx] = Math.min(1.0, trail[gy * cols + gx] + 0.04);
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // ANIMATION LOOP
  // ══════════════════════════════════════════════════════════════════

  var lastFrame = 0;
  var frameInterval = 1000 / 20;

  function animate(timestamp) {
    requestAnimationFrame(animate);
    if (timestamp - lastFrame < frameInterval) return;
    lastFrame = timestamp;

    growStep();

    // Respawn colonies if tips exhausted
    if (tips.length < 5) {
      var cx = 10 + Math.random() * (viewCols - 20);
      var cy = 10 + Math.random() * (viewRows - 20);
      seedColony(cx, cy, Math.floor(Math.random() * COLORS.length), 2 + Math.floor(Math.random() * 2));
    }

    // Decay flow trail, faster than structure, creates the pulsing effect
    for (var i = 0; i < trail.length; i++) {
      trail[i] *= 0.99;
      if (trail[i] < 0.005) trail[i] = 0;
    }

    // Update nutrient agents, Physarum sensing on the combined field
    for (var i = 0; i < agents.length; i++) {
      var a = agents[i];

      var sL = senseTrail(a.x, a.y, a.angle, -SENSOR_ANGLE);
      var sC = senseTrail(a.x, a.y, a.angle, 0);
      var sR = senseTrail(a.x, a.y, a.angle, SENSOR_ANGLE);

      var turn = 0.08 + Math.random() * 0.06;
      if (sC >= sL && sC >= sR) {
        a.angle += (Math.random() - 0.5) * 0.3;
      } else if (sL > sR) {
        a.angle -= turn;
      } else {
        a.angle += turn;
      }

      a.x += Math.cos(a.angle) * a.speed;
      a.y += Math.sin(a.angle) * a.speed;

      // Wrap edges
      if (a.x < 0) a.x += cols; if (a.x >= cols) a.x -= cols;
      if (a.y < 0) a.y += rows; if (a.y >= rows) a.y -= rows;

      // If agent drifted off the network, teleport back onto it
      var gx = Math.floor(a.x), gy = Math.floor(a.y);
      if (gx >= 0 && gx < cols && gy >= 0 && gy < rows && structure[gy * cols + gx] < 0.05) {
        // Off-network, find a random network cell to respawn on
        for (var att = 0; att < 30; att++) {
          var rx = Math.floor(Math.random() * viewCols);
          var ry = Math.floor(Math.random() * viewRows);
          if (structure[ry * cols + rx] > 0.1) {
            a.x = rx; a.y = ry;
            a.angle = Math.random() * Math.PI * 2;
            a.ci = colorIdx[ry * cols + rx];
            gx = rx; gy = ry;
            break;
          }
        }
      }

      // Deposit flow trail
      if (gx >= 0 && gx < cols && gy >= 0 && gy < rows) {
        var idx = gy * cols + gx;
        trail[idx] = Math.min(1.0, trail[idx] + 0.04);
        colorIdx[idx] = a.ci;
      }
    }

    // ── Render ──
    ctx.fillStyle = 'rgb(' + BG.r + ',' + BG.g + ',' + BG.b + ')';
    ctx.fillRect(0, 0, viewCols, viewRows);

    var rw = Math.min(viewCols, cols);
    var rh = Math.min(viewRows, rows);
    for (var y = 0; y < rh; y++) {
      for (var x = 0; x < rw; x++) {
        var idx = y * cols + x;
        var sVal = structure[idx];
        var tVal = trail[idx];
        if (sVal < 0.01 && tVal < 0.01) continue;
        var c = COLORS[colorIdx[idx]];
        // Structure is dim/permanent, flow is brighter/animated
        var alpha = (sVal * 0.02 + tVal * 0.2) * INK_ALPHA;
        ctx.fillStyle = 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + alpha + ')';
        ctx.fillRect(x, y, 1, 1);
      }
    }
  }

  requestAnimationFrame(animate);
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
