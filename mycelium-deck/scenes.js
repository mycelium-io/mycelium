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
    C = { accent: v('--accent'), violet: v('--accent2'), green: v('--green'), yellow: v('--yellow'), red: v('--red'), text: v('--text'), muted: v('--muted'), faint: v('--faint'), bg: v('--bg'), dark: document.documentElement.dataset.theme !== 'light' };
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
        ctx.font = `500 ${size}px "IBM Plex Sans", system-ui, sans-serif`;
        ctx.letterSpacing = '0.08em';
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

  // ── One agent, an orchestrator, its failure, then coworkers ──
  // Stage 0: one agent making tool calls; the ring around it is its context
  // window, which fills and compacts. Stage 1: it becomes an orchestrator
  // handing work to subagents, each with a few tools; each sends a summary up
  // and goes, and the summaries pile into the orchestrator's context until
  // it is full. Stage 2: one bad instruction at the top goes wrong all the
  // way down. Stage 3: the orchestrator goes; agents that each own a piece
  // of the work stay, keep the context they build up, and talk directly.
  defs.coworkers = () => {
    const rnd = seeded(11);
    const lead = node(960, 580, 0, 0);
    const TOOLS = ['read', 'edit', 'search', 'run tests', 'shell'].map((name, i) => {
      const ang = -Math.PI / 2 + i * (2 * Math.PI / 5);
      return { name, x: 960 + Math.cos(ang) * 330, y: 590 + Math.sin(ang) * 250 };
    });
    const SLOTS = [480, 720, 960, 1200, 1440];
    const peers = [['api', 520, 500], ['ui', 960, 400], ['release', 1400, 500], ['qa', 700, 800], ['design', 1220, 800]]
      .map(([name, x, y]) => Object.assign(node(x, y), { name, context: [] }));
    const vis = { tools: 0, subs: 0, fail: 0, peers: 0 };
    let pulses = [], subs = [], piled = [], fill = 0, full = 0;
    const subagent = (x, life) => {
      const n = node(x, 780, 0, 0);
      n.tr = 24; n.ta = 1; n.age = 0; n.life = life; n.sent = false; n.bad = false;
      n.kit = 1 + Math.floor(rnd() * 2);
      return n;
    };
    // The context window: a track, and an arc as full as it is.
    const gauge = (d, n, f, a) => {
      if (a < 0.01) return;
      const r = n.r + 24, ctx = d.ctx;
      d.ring(n.x, n.y, r, C.muted, a * 0.25, 4);
      ctx.save(); ctx.globalAlpha = a; ctx.strokeStyle = f > 0.85 ? C.red : C.yellow; ctx.lineWidth = 6; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.arc(n.x, n.y, r, -Math.PI / 2, -Math.PI / 2 + f * 2 * Math.PI); ctx.stroke(); ctx.restore();
    };
    return {
      stage(s) {
        pulses = [];
        subs.forEach(n => { n.ta = 0; n.tr = 0; });
        if (s === 0) { fill = 0; piled = []; }
        if (s === 1) { fill = 0.15; piled = []; }
        if (s === 2) { subs = SLOTS.slice(1).map(x => subagent(x - 120, Infinity)); }
        if (s < 3) peers.forEach(p => { p.context = []; });
      },
      frame(d, dt, s) {
        ease(vis, 'tools', s === 0 ? 1 : 0, 5, dt);
        ease(vis, 'subs', s === 1 || s === 2 ? 1 : 0, 5, dt);
        ease(vis, 'fail', s === 2 ? 1 : 0, 5, dt);
        ease(vis, 'peers', s === 3 ? 1 : 0, 5, dt);
        if (s === 0) {
          lead.tx = 960; lead.ty = 580; lead.tr = 46; lead.ta = 1;
          // Tool calls: out to a tool and back. A full window holds, then compacts.
          if (rnd() < dt * 1.8 && pulses.length < 3) pulses.push({ a: lead, b: TOOLS[Math.floor(rnd() * TOOLS.length)], u: 0, v: 1.4, color: C.yellow, back: true });
          if (fill >= 1 && (full += dt) > 1) { fill = 0.3; full = 0; lead.flash = 1; }
        } else if (s === 1) {
          lead.tx = 960; lead.ty = 320; lead.tr = 46; lead.ta = 1;
          // Hand a piece of work to a new subagent in a free slot.
          const free = SLOTS.filter(x => subs.every(n => n.ta === 0 || Math.abs(n.tx - x) > 60));
          if (free.length && rnd() < dt * 1.3) {
            const n = subagent(free[Math.floor(rnd() * free.length)], 2.2 + rnd() * 1.6);
            subs.push(n);
            pulses.push({ a: lead, b: n, u: 0, v: 1.5, color: C.violet });
          }
          // When it's done, its summary goes up and it goes.
          subs.forEach(n => { n.age += dt; if (!n.sent && n.age > n.life) { n.sent = true; pulses.push({ a: n, b: lead, u: 0, v: 1.2, color: C.yellow, done: n, summary: true }); } });
        } else if (s === 2) {
          lead.tx = 960; lead.ty = 320; lead.tr = 46; lead.ta = 1;
          // The bad instruction goes down; what comes back up is bad too.
          if (rnd() < dt * 2.4) {
            const n = subs[Math.floor(rnd() * subs.length)];
            if (n) pulses.push(n.bad ? { a: n, b: lead, u: 0, v: 1.2, color: C.red } : { a: lead, b: n, u: 0, v: 1.3, color: C.red, poison: n });
          }
          subs.forEach(n => { n.age += dt; });
        } else {
          lead.tr = 0; lead.ta = 0;
          // Peers talk directly, and keep adding to their own context.
          if (rnd() < dt * 2.6) {
            const a = peers[Math.floor(rnd() * peers.length)], others = peers.filter(p => p !== a);
            pulses.push({ a, b: others[Math.floor(rnd() * others.length)], u: 0, v: 1.1, color: C.accent });
          }
          if (rnd() < dt * 2.2) {
            const p = peers[Math.floor(rnd() * peers.length)];
            if (p.context.length < 14) { p.context.push({ ang: rnd() * 6.28, rad: 46 + rnd() * 16, spin: 0.25 + rnd() * 0.35, a: 0 }); p.flash = 1; }
          }
        }
        peers.forEach(p => { p.tr = s === 3 ? 28 : 0; p.ta = s === 3 ? 1 : 0; });
        subs = subs.filter(n => n.ta > 0 || n.a > 0.01);
        [lead, ...subs, ...peers].forEach(n => settle(n, dt));

        // Hyphae first, then messages, then beads on top.
        TOOLS.forEach(t => d.edge(lead, t, vis.tools * 0.4, C.muted, 0.05));
        subs.forEach(n => d.edge(lead, n, Math.min(lead.a, n.a) * 0.5, n.bad ? C.red : C.muted, 0.05));
        for (let i = 0; i < peers.length; i++) for (let j = i + 1; j < peers.length; j++) d.edge(peers[i], peers[j], vis.peers * 0.3, C.muted, 0.1);
        pulses.forEach(p => {
          p.u += dt * p.v;
          if (p.u >= 1 && !p.arrived) {
            p.arrived = true;
            if (p.b.flash !== undefined) p.b.flash = 1;
            if (p.back) { pulses.push({ a: p.b, b: p.a, u: 0, v: 1.4, color: C.yellow }); fill = Math.min(1, fill + 0.07); }
            if (p.done) { p.done.ta = 0; p.done.tr = 0; }
            if (p.summary) { fill = Math.min(1, fill + 0.09); if (piled.length < 40) piled.push({ ang: rnd() * 6.28, rad: 96 + rnd() * 34, spin: 0.15 + rnd() * 0.3, a: 0 }); }
            if (p.poison) p.poison.bad = true;
          }
          d.pulse(p.a, p.b, Math.min(1, p.u), p.color, 0.08);
        });
        pulses = pulses.filter(p => p.u < 1);

        TOOLS.forEach(t => { d.ring(t.x, t.y, 12, C.yellow, vis.tools * 0.8, 2); d.label(t.name, t.x, t.y + 40, vis.tools, C.muted, 18); });
        // Summaries the orchestrator has to hold, circling it.
        piled.forEach(m => { m.ang += m.spin * dt; m.a = approach(m.a, 1, 4, dt); d.bead(lead.x + Math.cos(m.ang) * m.rad, lead.y + Math.sin(m.ang) * m.rad * 0.6, 6, C.yellow, lead.a * m.a * (1 - vis.fail * 0.6)); });
        gauge(d, lead, fill, lead.a * (1 - vis.fail));
        d.bead(lead.x, lead.y, lead.r * (1 + lead.flash * 0.12), s === 0 ? C.accent : s === 2 ? C.red : C.violet, lead.a);
        d.label('agent', lead.x, lead.y + 100, vis.tools);
        d.label('ring: context window', lead.x, lead.y + 132, vis.tools * 0.8, C.yellow, 15);
        d.label('orchestrator', lead.x - 190, lead.y, vis.subs, C.muted, 20, 'right');
        subs.forEach(n => {
          d.bead(n.x, n.y, n.r * (1 + n.flash * 0.2), n.bad ? C.red : C.green, n.a);
          // Its few tools, beside it.
          for (let k = 0; k < n.kit; k++) d.ring(n.x + 46, n.y - 14 + k * 28, 8, C.yellow, n.a * 0.7, 2);
          // Working: two motes circling it.
          if (!n.sent) for (let k = 0; k < 2; k++) {
            const t = n.age * 4 + k * 3.14; d.ctx.save(); d.ctx.globalAlpha = n.a * 0.8; d.ctx.fillStyle = n.bad ? C.red : C.green;
            d.ctx.beginPath(); d.ctx.arc(n.x + Math.cos(t) * 40, n.y + Math.sin(t) * 40, 4, 0, 6.28); d.ctx.fill(); d.ctx.restore();
          }
        });
        d.label('subagents', 960, 880, vis.subs);
        peers.forEach(p => {
          p.context.forEach(m => { m.ang += m.spin * dt; m.a = approach(m.a, 1, 4, dt); d.bead(p.x + Math.cos(m.ang) * m.rad, p.y + Math.sin(m.ang) * m.rad, 5, C.green, p.a * m.a * 0.9); });
          d.bead(p.x, p.y, p.r * (1 + p.flash * 0.18), C.accent, p.a);
          d.label(p.name, p.x, p.y + 92, vis.peers);
        });
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
