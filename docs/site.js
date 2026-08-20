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

  // ── Header anchor links ──
  // Add chainlink icon to all h2[id] and h3[id] elements
  document.querySelectorAll('h2[id], h3[id]').forEach(heading => {
    const anchor = document.createElement('a');
    anchor.className = 'header-anchor';
    anchor.href = '#' + heading.id;
    anchor.setAttribute('aria-label', 'Copy link to section');
    anchor.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
    anchor.addEventListener('click', function(e) {
      e.preventDefault();
      const url = window.location.origin + window.location.pathname + '#' + heading.id;
      navigator.clipboard.writeText(url).then(() => {
        history.pushState(null, '', '#' + heading.id);
        anchor.style.opacity = '1';
        anchor.style.color = 'var(--green)';
        setTimeout(() => {
          anchor.style.color = '';
          anchor.style.opacity = '';
        }, 1500);
      });
    });
    heading.appendChild(anchor);
  });

  // ── Section ID to docs command mapping ──
  const SECTION_DOCS_MAP = {
    'overview': 'mycelium docs overview',
    'quickstart': 'mycelium docs quickstart',
    'rooms': 'mycelium docs rooms',
    'memory': 'mycelium docs memory',
    'cognitive-engine': 'mycelium docs cognitive-engine',
    'knowledge-graph': 'mycelium docs knowledge-graph',
    'cli-reference': 'mycelium docs cli-reference',
    'architecture': 'mycelium docs architecture',
    'adapters': 'mycelium docs adapters',
    'adapter-claude-code': 'mycelium docs adapters claude-code',
    'adapter-cursor': 'mycelium docs adapters cursor',
    'adapter-api': 'mycelium docs adapters api',
  };

  // Track current visible section for the docs cmd button
  var currentDocsSection = 'overview';

  function copyDocsCmd() {
    const cmd = SECTION_DOCS_MAP[currentDocsSection] || 'mycelium docs --full';
    navigator.clipboard.writeText(cmd).then(() => {
      const btn = document.querySelector('.copy-docs-btn');
      btn.innerHTML = '<i data-lucide="check"></i>' + cmd;
      btn.classList.add('copied');
      icons();
      setTimeout(() => {
        btn.innerHTML = '<i data-lucide="terminal"></i>Copy docs cmd';
        btn.classList.remove('copied');
        icons();
      }, 2000);
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
        // Track for copy docs cmd button
        if (SECTION_DOCS_MAP[id]) currentDocsSection = id;
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
