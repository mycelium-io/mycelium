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

  // ── Moved sections ──
  // Sections move between pages as the docs are reorganized, and old links
  // still carry the old page. When the hash names nothing here, find the page
  // that holds it in the search index (which lists every anchor) and go there.
  // Renamed anchors are mapped first.
  const RENAMED_ANCHORS = {
    'walk-server': 'on-a-server',
    'adapter-a2a': 'a2a-bridge',
    'adapters': 'engines',
  };
  (function relocate() {
    const raw = decodeURIComponent(location.hash.slice(1));
    if (!raw || document.getElementById(raw) && !RENAMED_ANCHORS[raw]) return;
    const id = RENAMED_ANCHORS[raw] || raw;
    if (document.getElementById(id)) { location.replace('#' + id); return; }
    const page = location.pathname.split('/').pop() || 'index.html';
    loadSearchIndex().then(index => {
      const hit = index.find(rec => rec.u.endsWith('#' + id) && !rec.u.startsWith(page + '#'));
      if (hit) location.replace(hit.u);
    });
  })();

  // ── One section at a time ──
  // Each page is a run of doc-sections; showing them all at once makes an
  // endless scroll. Only the section the URL points at is shown, ending in its
  // Previous / Next bar (generate_docs.py writes those, in reading order across
  // pages). A link to a heading shows the section that holds it, then scrolls
  // to it. Without JS nothing is hidden: every section shows, stacked.
  //
  // Only pages the generator built have pagers. Hand-written pages that load
  // this file (l9-integration.html, omnigent-integration.html) have sections
  // but no way between them, so they keep scrolling as one page.
  const pagedSections = Array.prototype.slice.call(document.querySelectorAll('.main .doc-section[id]'));
  const pagers = document.querySelectorAll('.doc-pager[data-pager-for]');
  const paged = pagedSections.length > 1 && pagers.length > 0;
  if (paged) {
    document.body.classList.add('paged');
    let current = null;

    const route = (jump) => {
      const id = decodeURIComponent(location.hash.slice(1));
      const target = id ? document.getElementById(id) : null;
      const section = (target && target.closest('.doc-section')) || pagedSections[0];
      if (section !== current) {
        pagedSections.forEach(s => s.classList.toggle('is-current', s === section));
        pagers.forEach(p => p.classList.toggle('is-current', p.getAttribute('data-pager-for') === section.id));
        current = section;
      }
      // Highlight the sidebar entry for this exact anchor, else its section.
      const links = document.querySelectorAll('.sidebar .nav-link[href^="#"]');
      const exact = target && document.querySelector('.sidebar .nav-link[href="#' + CSS.escape(id) + '"]');
      const want = '#' + (exact ? id : section.id);
      links.forEach(l => l.classList.toggle('active', l.getAttribute('href') === want));
      // Instant, not the page's smooth scroll: a new section is a new page,
      // and gliding through the old one's length to reach it reads as lag.
      if (target && target !== section) target.scrollIntoView({ behavior: 'instant' });
      else if (jump) window.scrollTo({ top: 0, behavior: 'instant' });
    };
    window.addEventListener('hashchange', () => route(true));
    route(false);
  }

  // Active nav link tracking (the scrolling layout; paged mode sets it above)
  const sections = document.querySelectorAll('.doc-section[id], section[id]');
  const navLinks = document.querySelectorAll('.nav-link[href^="#"]');

  const observer = new IntersectionObserver((entries) => {
    if (paged) return;
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
