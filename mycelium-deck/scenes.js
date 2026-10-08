// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── Scenes: show, don't tell ──
// A <canvas class="scene" data-scene="name"> on a slide draws a small living
// diagram in the deck's glass: beads for agents and people, hyphae for the
// links between them, pulses for messages. A scene moves through stages, and
// the stage is the number of the slide's steps shown, so the clicker drives
// it like any other step: put empty <i class="step beat"></i> markers on the
// slide, one per stage after the first. The slide carries data-stage, so CSS
// can swap a heading with it ([data-at] inside .swap).
//
// Everything is drawn in stage pixels (1920x1080) and only while its slide
// is showing.
(function () {
  const W = 1920, H = 1080;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const defs = {};

  // ── Palette, read from the deck's tokens (again when the theme changes) ──
  let C = {};
  const readColors = () => {
    const cs = getComputedStyle(document.documentElement), v = n => cs.getPropertyValue(n).trim();
    C = { accent: v('--accent'), violet: v('--accent2'), green: v('--green'), yellow: v('--yellow'), text: v('--text'), muted: v('--muted'), faint: v('--faint'), bg: v('--bg'), dark: document.documentElement.dataset.theme !== 'light' };
  };
  readColors();
  new MutationObserver(readColors).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  // ── Small tools ──
  const approach = (cur, target, rate, dt) => cur + (target - cur) * (reduce ? 1 : 1 - Math.exp(-rate * dt));
  const ease = (o, key, target, rate, dt) => { o[key] = approach(o[key], target, rate, dt); };
  const seeded = s => () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

  function draw(ctx) {
    return {
      ctx,
      // A glass bead: lit from the top left, a rim, and a soft glow on dark.
      bead(x, y, r, color, a = 1) {
        if (r < 0.5 || a < 0.01) return;
        ctx.save();
        ctx.globalAlpha = a;
        if (C.dark) { ctx.shadowColor = color; ctx.shadowBlur = r * 0.9; }
        const g = ctx.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.1, x, y, r);
        g.addColorStop(0, '#ffffff'); g.addColorStop(0.18, color); g.addColorStop(1, mix(color, C.dark ? '#000' : '#334', 0.45));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill();
        ctx.shadowBlur = 0;
        ctx.globalAlpha = a * 0.55;
        ctx.strokeStyle = '#fff'; ctx.lineWidth = Math.max(1, r * 0.06);
        ctx.beginPath(); ctx.arc(x, y, r * 0.96, 3.6, 5.2); ctx.stroke();
        ctx.restore();
      },
      // A ring: a bead seen as an outline (a person, a slot).
      ring(x, y, r, color, a = 1, w = 3) {
        if (a < 0.01) return;
        ctx.save(); ctx.globalAlpha = a; ctx.strokeStyle = color; ctx.lineWidth = w;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.stroke(); ctx.restore();
      },
      // A hypha between two points, bowed a little.
      edge(a, b, alpha, color = C.muted, bend = 0.12, w = 2) {
        if (alpha < 0.01) return;
        const [cx, cy] = ctrl(a, b, bend);
        ctx.save(); ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = w;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(cx, cy, b.x, b.y); ctx.stroke(); ctx.restore();
      },
      // A message travelling down an edge, u from 0 to 1.
      pulse(a, b, u, color = C.accent, bend = 0.12, r = 7, alpha = 1) {
        const p = along(a, b, bend, u);
        ctx.save(); ctx.globalAlpha = alpha * Math.min(1, u * 6, (1 - u) * 6);
        if (C.dark) { ctx.shadowColor = color; ctx.shadowBlur = 16; }
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.2832); ctx.fill(); ctx.restore();
      },
      label(text, x, y, a = 1, color = C.muted, size = 20, align = 'center') {
        if (a < 0.01) return;
        ctx.save(); ctx.globalAlpha = a; ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = 'middle';
        ctx.font = `500 ${size}px "Geist Mono", ui-monospace, monospace`;
        ctx.letterSpacing = '0.12em';
        ctx.fillText(text.toUpperCase(), x, y); ctx.restore();
      },
    };
  }
  function ctrl(a, b, bend) {
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y;
    return [mx - dy * bend, my + dx * bend];
  }
  function along(a, b, bend, u) {
    const [cx, cy] = ctrl(a, b, bend), v = 1 - u;
    return { x: v * v * a.x + 2 * v * u * cx + u * u * b.x, y: v * v * a.y + 2 * v * u * cy + u * u * b.y };
  }
  function mix(c1, c2, t) {
    const p = c => { const m = c.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i) || c.match(/^#?([0-9a-f])([0-9a-f])([0-9a-f])$/i); return m ? m.slice(1, 4).map(h => parseInt(h.length === 1 ? h + h : h, 16)) : [128, 128, 128]; };
    const a = p(c1), b = p(c2);
    return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',')})`;
  }

  // A node that eases toward where it should be.
  const node = (x, y, r = 0, a = 0) => ({ x, y, r, a, tx: x, ty: y, tr: r, ta: a, flash: 0 });
  function settle(n, dt, rate = 4) {
    ease(n, 'x', n.tx, rate, dt); ease(n, 'y', n.ty, rate, dt);
    ease(n, 'r', n.tr, rate * 1.4, dt); ease(n, 'a', n.ta, rate * 1.4, dt);
    n.flash = Math.max(0, n.flash - dt * 2.5);
  }

  // ════ The scenes ════

  // ── A roleplay, then a network ──
  // Stage 0: one orchestrator hands turns to agent a and agent b, one message
  // at a time, always through itself. Stage 1: the orchestrator goes; agents
  // link to the ones near them, pass work along in chains, and invoke new
  // agents that later finish and go.
  defs.roleplay = () => {
    const rnd = seeded(11);
    const hub = node(960, 610, 0, 0);
    const spots = [];
    for (let tries = 0; spots.length < 13 && tries < 900; tries++) {
      const p = { x: 330 + rnd() * 1260, y: 360 + rnd() * 560 };
      if (spots.every(q => dist(p, q) > 190)) spots.push(p);
    }
    const agents = spots.map(p => node(p.x, p.y));
    let pulses = [], clock = 0, turn = 0, spawned = [];
    return {
      stage(s) { if (s === 0) { spawned.forEach(n => { n.ta = 0; n.tr = 0; }); } pulses = []; },
      frame(d, dt, s) {
        clock += dt;
        const A = agents[0], B = agents[1];
        if (s === 0) {
          hub.tx = 960; hub.ty = 610; hub.tr = 46; hub.ta = 1;
          A.tx = 600; A.ty = 610; B.tx = 1320; B.ty = 610;
          agents.forEach((n, i) => { n.tr = i < 2 ? 30 : 0; n.ta = i < 2 ? 1 : 0; });
          // Scripted turns: through the hub, one at a time, in order.
          if (!pulses.length && clock > 0.25) {
            const seq = [[hub, A], [A, hub], [hub, B], [B, hub]][turn++ % 4];
            pulses.push({ a: seq[0], b: seq[1], u: 0, v: 1.25, color: seq[0] === hub ? C.violet : C.accent });
            clock = 0;
          }
        } else {
          hub.tr = 0; hub.ta = 0;
          agents.forEach((n, i) => { n.tx = spots[i].x; n.ty = spots[i].y; n.tr = 24; n.ta = 1; });
          // Messages between neighbours, several at once; one that arrives
          // is often passed on, so work travels in chains nobody planned.
          const live = agents.concat(spawned.filter(n => n.ta > 0.5));
          if (rnd() < dt * 3.2) {
            const a = live[Math.floor(rnd() * live.length)], near = live.filter(n => n !== a && dist(n, a) < 380);
            if (near.length) pulses.push({ a, b: near[Math.floor(rnd() * near.length)], u: 0, v: 1.1, color: C.accent, hops: 2 });
          }
          // Now and then an agent invokes a new one beside it.
          if (rnd() < dt * 0.45 && spawned.filter(n => n.ta > 0).length < 5) {
            const parent = agents[Math.floor(rnd() * agents.length)];
            const ang = rnd() * 6.28, n = node(parent.x, parent.y, 0, 0);
            n.tx = parent.x + Math.cos(ang) * 120; n.ty = parent.y + Math.sin(ang) * 100; n.tr = 15; n.ta = 1;
            n.parent = parent; n.life = 5 + rnd() * 3;
            spawned.push(n);
            pulses.push({ a: parent, b: n, u: 0, v: 1.6, color: C.green });
          }
        }
        spawned.forEach(n => { if (n.life !== undefined && (n.life -= dt) < 0) { n.ta = 0; n.tr = 0; } });
        spawned = spawned.filter(n => n.ta > 0.01 || n.a > 0.01);

        [hub, ...agents, ...spawned].forEach(n => settle(n, dt));
        // Hyphae first, then messages, then beads on top.
        d.edge(hub, A, hub.a * 0.7, C.muted, 0.05); d.edge(hub, B, hub.a * 0.7, C.muted, -0.05);
        if (s > 0) {
          for (let i = 0; i < agents.length; i++) for (let j = i + 1; j < agents.length; j++) {
            const a = agents[i], b = agents[j], k = dist(a, b);
            if (k < 380) d.edge(a, b, Math.min(a.a, b.a) * 0.45 * (1 - k / 520), C.muted, 0.1);
          }
          spawned.forEach(n => n.parent && d.edge(n.parent, n, n.a * 0.6, C.green, 0.15, 1.5));
        }
        pulses.forEach(p => {
          p.u += dt * p.v;
          if (p.u >= 1) {
            p.b.flash = 1;
            if (p.hops && rnd() < 0.6) {
              const live = agents.filter(n => n !== p.a && n !== p.b && dist(n, p.b) < 380);
              if (live.length) pulses.push({ a: p.b, b: live[Math.floor(rnd() * live.length)], u: 0, v: 1.1, color: C.accent, hops: p.hops - 1 });
            }
          }
          d.pulse(p.a, p.b, Math.min(1, p.u), p.color, 0.1);
        });
        pulses = pulses.filter(p => p.u < 1);
        d.bead(hub.x, hub.y, hub.r * (1 + hub.flash * 0.12), C.violet, hub.a);
        d.label('supervisor', hub.x, hub.y + 82, hub.a);
        agents.forEach((n, i) => {
          d.bead(n.x, n.y, n.r * (1 + n.flash * 0.18), C.accent, n.a);
          if (i < 2) d.label(i ? 'agent b' : 'agent a', n.x, n.y + 62, hub.a);
        });
        spawned.forEach(n => d.bead(n.x, n.y, n.r * (1 + n.flash * 0.2), C.green, n.a));
      },
    };
  };

  // ── An assistant, then workers, then memory ──
  // Stage 0: one assistant takes in every piece of work and keeps it, and
  // swells. Stage 1: workers arrive, work, and die, each compacting what it
  // learned into the tray below. Stage 2: the tray's three kinds are named,
  // and each new worker reads from it before it starts.
  defs.lifecycle = () => {
    const rnd = seeded(5);
    const big = node(960, 520, 0, 0);
    const KINDS = ['accent', 'violet', 'green'];
    const TRAY = { x: 520, y: 900, w: 880 };
    let tray = [], workers = [], drops = [], bits = [], inside = [], clock = 0, swell = 0;
    // The tray has a section per kind; beads fill each from the left, then stack.
    const SEC = TRAY.w / 3;
    const slot = (kind, i) => ({ x: TRAY.x + KINDS.indexOf(kind) * SEC + 34 + (i % 9) * 28, y: TRAY.y - 6 - Math.floor(i / 9) * 26 });
    const count = kind => tray.filter(k => k === kind).length;
    return {
      stage(s) { if (s === 0) { tray = []; workers = []; drops = []; inside = []; swell = 0; } },
      frame(d, dt, s) {
        clock += dt;
        if (s === 0) {
          big.tr = 70 + swell; big.ta = 1;
          // Work flies in, and stays: the assistant just gets bigger.
          if (rnd() < dt * 2.2) { const ang = rnd() * 6.28; bits.push({ x: 960 + Math.cos(ang) * 520, y: 520 + Math.sin(ang) * 330, u: 0 }); }
        } else { big.tr = 0; big.ta = 0; }
        bits.forEach(b => { b.u += dt * 0.9; if (b.u >= 1) { swell = Math.min(110, swell + 2.2); big.flash = 1; if (inside.length < 60) inside.push({ ang: rnd() * 6.28, rad: rnd(), spin: 0.2 + rnd() * 0.5, kind: KINDS[Math.floor(rnd() * 3)] }); } });
        bits = bits.filter(b => b.u < 1 && s === 0);

        if (s >= 1) {
          if (rnd() < dt * 1.3 && workers.length < 7) {
            let p; for (let k = 0; k < 20; k++) { p = { x: 380 + rnd() * 1160, y: 320 + rnd() * 420 }; if (workers.every(w => dist(w, p) > 150)) break; }
            const w = node(p.x, p.y, 0, 0);
            w.tr = 26; w.ta = 1; w.kind = KINDS[Math.floor(rnd() * 3)]; w.age = 0;
            const have = KINDS.filter(count);
            const k = have[Math.floor(rnd() * have.length)];
            w.read = s >= 2 && have.length ? { from: slot(k, Math.floor(rnd() * count(k))), u: 0, kind: k } : null;
            w.life = w.read ? 1.6 + rnd() : 2.6 + rnd() * 1.2;
            workers.push(w);
          }
        }
        workers.forEach(w => {
          w.age += dt;
          if (w.read && w.read.u < 1) { w.read.u += dt * 1.8; w.age = Math.min(w.age, 0.2); }
          if (w.age > w.life && w.ta > 0) {
            w.ta = 0; w.tr = 0;
            const queued = count(w.kind) + drops.filter(p => p.kind === w.kind).length;
            if (queued < 27) drops.push({ x: w.x, y: w.y, vy: -80, kind: w.kind, to: slot(w.kind, queued) });
          }
          settle(w, dt, 5);
        });
        workers = workers.filter(w => w.ta > 0 || w.a > 0.02);
        drops.forEach(p => { p.vy += 1400 * dt; p.y += p.vy * dt; p.x += (p.to.x - p.x) * Math.min(1, dt * 4); if (p.y >= p.to.y) { p.done = true; tray.push(p.kind); } });
        drops = drops.filter(p => !p.done);
        settle(big, dt, 3);

        // Draw.
        const showTray = s >= 1 ? 1 : 0;
        d.ctx.save(); d.ctx.globalAlpha = 0.55 * showTray;
        d.ctx.strokeStyle = C.muted; d.ctx.lineWidth = 2;
        d.ctx.beginPath(); d.ctx.moveTo(TRAY.x, TRAY.y + 18); d.ctx.lineTo(TRAY.x + TRAY.w, TRAY.y + 18); d.ctx.stroke();
        d.ctx.restore();
        bits.forEach(b => d.pulse({ x: b.x, y: b.y }, big, b.u, C.yellow, 0.1, 6));
        d.bead(big.x, big.y, big.r * (1 + big.flash * 0.04), C.violet, big.a);
        // What it was given stays inside it, turning slowly: its memory is itself.
        inside.forEach(m => { m.ang += m.spin * dt; const rr = big.r * 0.72 * Math.sqrt(m.rad); d.bead(big.x + Math.cos(m.ang) * rr, big.y + Math.sin(m.ang) * rr, 6, C[m.kind], big.a * 0.9); });
        workers.forEach(w => {
          if (w.read && w.read.u < 1.05) d.edge(w.read.from, w, Math.min(1, w.read.u * 2) * w.a * 0.8, C[w.read.kind], 0.12, 2);
          if (w.read && w.read.u < 1) d.pulse(w.read.from, w, w.read.u, C[w.read.kind], 0.12, 6);
          d.bead(w.x, w.y, w.r, C[w.kind], w.a);
          // Working: two motes circling it.
          if (w.a > 0.5 && (!w.read || w.read.u >= 1)) for (let k = 0; k < 2; k++) {
            const t = w.age * 4 + k * 3.14; d.ctx.save(); d.ctx.globalAlpha = w.a * 0.8; d.ctx.fillStyle = C[w.kind];
            d.ctx.beginPath(); d.ctx.arc(w.x + Math.cos(t) * 42, w.y + Math.sin(t) * 42, 4, 0, 6.28); d.ctx.fill(); d.ctx.restore();
          }
        });
        drops.forEach(p => d.bead(p.x, p.y, 9, C[p.kind], 1));
        KINDS.forEach(k => { for (let i = 0; i < count(k); i++) { const p = slot(k, i); d.bead(p.x, p.y, 10, C[k], showTray); } });
        const named = s >= 2 ? 1 : 0;
        ['preferences', 'behaviours', 'procedures'].forEach((t, i) => d.label(t, TRAY.x + SEC * i + SEC / 2, TRAY.y + 56, named, C[KINDS[i]], 19));
      },
    };
  };

  // ── From one prompt to a swarm ──
  // You, then: one agent; three in parallel; three repeatable chains; a swarm.
  defs.scale = () => {
    const rnd = seeded(23);
    const you = node(300, 600, 30, 1);
    const N = 34;
    const agents = Array.from({ length: N }, () => node(560, 600));
    const cloud = [];
    for (let tries = 0; cloud.length < N && tries < 4000; tries++) {
      const p = { x: 640 + rnd() * 1000, y: 320 + rnd() * 480 };
      if (cloud.every(q => dist(p, q) > 104)) cloud.push(p);
    }
    while (cloud.length < N) cloud.push({ x: 640 + rnd() * 1000, y: 320 + rnd() * 480 });
    let pulses = [], clock = 0;
    const layout = s => {
      if (s === 0) return [{ x: 760, y: 600 }];
      if (s === 1) return [{ x: 780, y: 410 }, { x: 780, y: 600 }, { x: 780, y: 790 }];
      if (s === 2) return [0, 1, 2].flatMap(r => [0, 1, 2].map(c => ({ x: 740 + c * 300, y: 410 + r * 190 })));
      return cloud;
    };
    // Who talks to whom at each stage, as index pairs (-1 is you).
    const links = s => {
      if (s === 0) return [[-1, 0]];
      if (s === 1) return [[-1, 0], [-1, 1], [-1, 2]];
      if (s === 2) return [0, 1, 2].flatMap(r => [[-1, r * 3], [r * 3, r * 3 + 1], [r * 3 + 1, r * 3 + 2]]);
      const out = [[-1, nearest()]];
      for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) if (dist(cloud[i], cloud[j]) < 175) out.push([i, j]);
      return out;
    };
    const nearest = () => cloud.reduce((b, p, i) => (dist(p, you) < dist(cloud[b], you) ? i : b), 0);
    let current = -1, edges = [];
    return {
      stage(s) { current = s; edges = links(Math.min(3, s)); pulses = []; clock = 0; },
      frame(d, dt, s) {
        s = Math.min(3, s);
        if (current !== s) this.stage(s);
        clock += dt;
        const spots = layout(s);
        agents.forEach((n, i) => { const p = spots[i]; if (p) { n.tx = p.x; n.ty = p.y; n.tr = s === 3 ? 15 : 24; n.ta = 1; } else { n.tx = 560; n.ty = 600; n.tr = 0; n.ta = 0; } settle(n, dt, 3.2); });
        settle(you, dt);
        const at = i => (i < 0 ? you : agents[i]);
        // Messages: back and forth; all at once; down each chain; everywhere.
        if (s === 0 && rnd() < dt * 1.4) pulses.push({ a: you, b: agents[0], u: 0, back: true });
        if (s === 1 && rnd() < dt * 2.4) pulses.push({ a: you, b: agents[Math.floor(rnd() * 3)], u: 0 });
        if (s === 2 && clock > 1.1) { clock = 0; [0, 1, 2].forEach(r => pulses.push({ chain: [you, agents[r * 3], agents[r * 3 + 1], agents[r * 3 + 2]], leg: 0, u: 0 })); }
        if (s === 3 && rnd() < dt * 9) { const e = edges[1 + Math.floor(rnd() * (edges.length - 1))]; if (e) pulses.push(rnd() < 0.5 ? { a: at(e[0]), b: at(e[1]), u: 0 } : { a: at(e[1]), b: at(e[0]), u: 0 }); }

        edges.forEach(([i, j]) => d.edge(at(i), at(j), Math.min(at(i).a, at(j).a) * (s === 3 ? 0.35 : 0.6), C.muted, 0.08));
        pulses.forEach(p => {
          p.u += dt * (s === 3 ? 1.5 : 1.1);
          if (p.chain) {
            if (p.u >= 1 && p.leg < p.chain.length - 2) { p.leg++; p.u = 0; p.chain[p.leg].flash = 1; }
            d.pulse(p.chain[p.leg], p.chain[p.leg + 1], Math.min(1, p.u), C.accent, 0.08);
          } else {
            if (p.u >= 1 && p.back) { p.back = false; p.u = 0; [p.a, p.b] = [p.b, p.a]; }
            d.pulse(p.a, p.b, Math.min(1, p.u), p.a === you ? C.violet : C.accent, 0.08, s === 3 ? 5 : 7);
          }
        });
        pulses = pulses.filter(p => p.chain ? !(p.u >= 1 && p.leg >= p.chain.length - 2) : p.u < 1);
        agents.forEach(n => d.bead(n.x, n.y, n.r * (1 + n.flash * 0.2), C.accent, n.a));
        agents.forEach(n => { n.flash = Math.max(0, n.flash - dt * 2); });
        d.bead(you.x, you.y, you.r, C.violet, 1);
        d.label('you', you.x, you.y + 62, 1, C.violet);
      },
    };
  };

  // ── One conversation, then lanes ──
  // Stage 0: the people and every task's work in one conversation, crowded.
  // Stage 1: the chat stands apart, and each task's thread runs in its own
  // lane, all of them at once.
  defs.lanes = () => {
    const rnd = seeded(31);
    const LANES = { chat: 400, api: 610, ui: 750, docs: 890 }, MID = 650;
    const COLOR = { chat: 'violet', api: 'accent', ui: 'green', docs: 'yellow' };
    const KINDS = ['chat', 'api', 'ui', 'docs'];
    const X0 = 560, X1 = 1700;
    const msgs = Array.from({ length: 46 }, (_, i) => {
      const kind = i % 7 === 0 ? 'chat' : KINDS[1 + (i % 3)];
      return { kind, x: X0 + rnd() * (X1 - X0), y: MID, jit: (rnd() - 0.5) * 70, v: kind === 'chat' ? 55 : 110 + rnd() * 70 };
    });
    let split = 0;
    return {
      frame(d, dt, s) {
        split = approach(split, s >= 1 ? 1 : 0, 2.6, dt);
        const ctx = d.ctx;
        // The one lane, fading as the four appear.
        ctx.save();
        ctx.globalAlpha = 0.5 * (1 - split); ctx.strokeStyle = C.muted; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(X0, MID); ctx.lineTo(X1, MID); ctx.stroke();
        KINDS.forEach(k => {
          ctx.globalAlpha = 0.5 * split; ctx.strokeStyle = C[COLOR[k]]; ctx.lineWidth = k === 'chat' ? 2.5 : 2;
          ctx.setLineDash(k === 'chat' ? [2, 14] : [8, 14]);
          ctx.beginPath(); ctx.moveTo(X0, LANES[k]); ctx.lineTo(X1, LANES[k]); ctx.stroke();
        });
        ctx.setLineDash([]);
        ctx.globalAlpha = split * 0.5; ctx.strokeStyle = C.muted; ctx.lineWidth = 1.5; ctx.setLineDash([10, 10]);
        ctx.beginPath(); ctx.moveTo(X0, 505); ctx.lineTo(X1, 505); ctx.stroke(); ctx.setLineDash([]);
        ctx.restore();
        d.label('the room · chat', X0, LANES.chat - 46, split, C.violet, 20, 'left');
        ['api', 'ui', 'docs'].forEach(k => d.label(`work/${k}`, X0, LANES[k] - 40, split, C[COLOR[k]], 20, 'left'));
        msgs.forEach(m => {
          // Crowded, everything moves at the slowest pace; apart, each at its own.
          const v = m.v * (0.35 + 0.65 * split);
          m.x += v * dt; if (m.x > X1) m.x = X0;
          const y = MID + m.jit * (1 - split) + (LANES[m.kind] - MID) * split;
          const fade = Math.min(1, (m.x - X0) / 60, (X1 - m.x) / 60);
          d.bead(m.x, y, m.kind === 'chat' ? 11 : 9, C[COLOR[m.kind]], fade);
        });
      },
    };
  };

  // ── Outcomes, and the pane behind them ──
  // A swarm works behind frosted glass (the slide's .veil); finished work
  // comes out the side as outcomes. Stage 1 clears the glass (CSS) to show
  // what was going on all along.
  defs.trust = () => {
    const rnd = seeded(47);
    const N = 22, box = { x: 180, y: 340, w: 920, h: 560 };
    const agents = [];
    for (let tries = 0; agents.length < N && tries < 3000; tries++) {
      const p = { x: box.x + 60 + rnd() * (box.w - 120), y: box.y + 60 + rnd() * (box.h - 120) };
      if (agents.every(q => dist(p, q) > 115)) agents.push(node(p.x, p.y, 16, 1));
    }
    const edges = [];
    for (let i = 0; i < agents.length; i++) for (let j = i + 1; j < agents.length; j++) if (dist(agents[i], agents[j]) < 190) edges.push([i, j]);
    const TASKS = ['rate limits on the api', 'empty state for the board', 'docs for swarm', 'retry on a failed claim', 'cache the room list', 'flaky test in ci', 'dark mode on metrics', 'shorter wake digest'];
    let pulses = [], next = 3, since = 0;
    let outcomes = TASKS.slice(0, 3).reverse().map(text => ({ text, a: 1 }));
    return {
      frame(d, dt) {
        if (rnd() < dt * 7 && edges.length) { const [i, j] = edges[Math.floor(rnd() * edges.length)]; pulses.push(rnd() < 0.5 ? { a: agents[i], b: agents[j], u: 0 } : { a: agents[j], b: agents[i], u: 0 }); }
        since += dt;
        if (since > 2.2) {
          since = 0;
          outcomes.unshift({ text: TASKS[next++ % TASKS.length], a: 0 });
          outcomes = outcomes.slice(0, 6);
          const a = agents[Math.floor(rnd() * agents.length)]; a.flash = 1;
        }
        edges.forEach(([i, j]) => d.edge(agents[i], agents[j], 0.35, C.muted, 0.1));
        pulses.forEach(p => { p.u += dt * 1.4; if (p.u >= 1) p.b.flash = 1; d.pulse(p.a, p.b, Math.min(1, p.u), C.accent, 0.1, 5); });
        pulses = pulses.filter(p => p.u < 1);
        agents.forEach(n => { n.flash = Math.max(0, n.flash - dt * 2); d.bead(n.x, n.y, n.r * (1 + n.flash * 0.25), n.flash > 0.3 ? C.green : C.accent, 1); });
        // The outcomes, newest on top.
        d.label('outcomes', 1275, 340, 1, C.muted, 19, 'left');
        outcomes.forEach((o, i) => {
          o.a = approach(o.a, 1 - i * 0.14, 5, dt);
          const y = 400 + i * 86;
          d.bead(1290, y, 13, C.green, o.a);
          d.ctx.save(); d.ctx.globalAlpha = o.a; d.ctx.fillStyle = C.text; d.ctx.textBaseline = 'middle';
          d.ctx.font = '400 30px "IBM Plex Sans", system-ui, sans-serif'; d.ctx.fillText(o.text, 1330, y); d.ctx.restore();
        });
      },
    };
  };

  // ════ Running them ════
  const live = [];
  document.querySelectorAll('canvas.scene[data-scene]').forEach(canvas => {
    const def = defs[canvas.dataset.scene];
    if (!def) return;
    live.push({ canvas, slide: canvas.closest('.slide'), scene: def(), ctx: canvas.getContext('2d'), stage: -1 });
  });
  if (!live.length) return;

  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    live.forEach(s => {
      if (!s.slide.classList.contains('active')) return;
      const stage = s.slide.querySelectorAll('.step.shown').length;
      if (stage !== s.stage) { s.slide.dataset.stage = stage; if (s.scene.stage) s.scene.stage(stage, s.stage); s.stage = stage; }
      // Back the canvas at the pixels it covers on screen, so it stays sharp.
      const r = s.canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
      const bw = Math.max(1, Math.round(r.width * dpr)), bh = Math.max(1, Math.round(r.height * dpr));
      if (s.canvas.width !== bw || s.canvas.height !== bh) { s.canvas.width = bw; s.canvas.height = bh; }
      s.ctx.setTransform(bw / W, 0, 0, bh / H, 0, 0);
      s.ctx.clearRect(0, 0, W, H);
      s.scene.frame(draw(s.ctx), dt, stage);
    });
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
