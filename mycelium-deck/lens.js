// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── The lens (background) ──
// One glass lens, not a field of droplets. Behind the slides a mycelial
// network grows for as long as the deck is open: hyphae reaching from node to
// node, with message pulses running along them. The lens sits over a part of
// it, magnifies it with per-channel dispersion and a thin-film rim, and moves
// between slides like a drop of gel, stretching along its path. A slide can
// ask for up to three lenses (a big one and a bead or two); one it stops
// asking for shrinks away.
//
// Interface: window.Lens.set(lenses, index) with lenses in viewport CSS px
// ({x, y, r}, y down), and window.Lens.theme(dark). deck.js drives both.
(function () {
  const canvas = document.getElementById('lens-bg');
  const noop = { set() {}, theme() {}, grow() {} };
  const gl = canvas && canvas.getContext('webgl', { antialias: false, alpha: false, premultipliedAlpha: false });
  if (!gl) { document.documentElement.classList.add('no-webgl'); window.Lens = noop; return; }

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MAX_LENS = 3;
  const MAX_P = 24;   // message pulses
  const OVER = 1.22;  // the network is wider than the view, so slides can pan across it

  // ── The network: a 2D canvas, uploaded as a texture while it grows ──
  // Channels: R hyphae, B nodes. Pulses are drawn by the shader from uniforms.
  const NW = Math.round(Math.min(1700, innerWidth) * OVER);
  const NH = Math.round(NW * Math.max(0.5, Math.min(0.75, innerHeight / innerWidth)));
  const SC = NW / (1700 * OVER);
  const net = document.createElement('canvas');
  net.width = NW; net.height = NH;
  const nx = net.getContext('2d');
  nx.fillStyle = '#000'; nx.fillRect(0, 0, NW, NH);
  nx.globalCompositeOperation = 'lighten';   // max, not sum: joints and crossings don't bead
  nx.lineCap = 'round';

  let seed = 7;   // fixed, so the deck grows the same network every time
  const rand = () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };

  const nodes = [];
  for (let tries = 0; nodes.length < 11 && tries < 400; tries++) {
    const x = NW * (0.06 + rand() * 0.88), y = NH * (0.08 + rand() * 0.84);
    if (nodes.every(n => Math.hypot(n.x - x, n.y - y) > NW * 0.16)) nodes.push({ x, y });
  }
  const paths = [], tips = [];
  let segments = 0;
  const CAP = 11000;

  function sprout(x, y, a, w, life, gen, home) {
    const path = { pts: [x, y] };
    paths.push(path);
    tips.push({ x, y, a, w, life, gen, home, path });
  }
  function bead(n, r) {
    const g = nx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r);
    g.addColorStop(0, 'rgba(0,0,255,1)'); g.addColorStop(0.35, 'rgba(0,0,255,.55)'); g.addColorStop(1, 'rgba(0,0,0,0)');
    nx.fillStyle = g; nx.beginPath(); nx.arc(n.x, n.y, r, 0, 6.2832); nx.fill();
  }
  nodes.forEach((n, i) => {
    bead(n, 13 * SC + 4);
    const k = 3 + Math.floor(rand() * 3);
    for (let j = 0; j < k; j++) sprout(n.x, n.y, rand() * 6.2832, 2.6 * SC + 0.6, 260 + rand() * 260, 0, i);
  });

  const STEP = 3.2 * SC + 0.8;
  function step() {
    for (let t = tips.length - 1; t >= 0; t--) {
      const tip = tips[t];
      // Reach for the nearest other node, gently: hyphae wander, then find.
      let best = null, bd = 1e9;
      for (let i = 0; i < nodes.length; i++) {
        if (i === tip.home) continue;
        const d = Math.hypot(nodes[i].x - tip.x, nodes[i].y - tip.y);
        if (d < bd) { bd = d; best = nodes[i]; }
      }
      if (best && bd < NW * 0.3) {
        let da = Math.atan2(best.y - tip.y, best.x - tip.x) - tip.a;
        da = Math.atan2(Math.sin(da), Math.cos(da));
        tip.a += da * (bd < NW * 0.08 ? 0.12 : 0.03);
      }
      tip.a += (rand() - 0.5) * 0.36;
      const x = tip.x + Math.cos(tip.a) * STEP, y = tip.y + Math.sin(tip.a) * STEP;
      nx.strokeStyle = `rgba(255,0,0,${0.32 + 0.3 * Math.min(1, tip.w / 2.5)})`;
      nx.lineWidth = tip.w;
      nx.beginPath(); nx.moveTo(tip.x, tip.y); nx.lineTo(x, y); nx.stroke();
      tip.x = x; tip.y = y; tip.path.pts.push(x, y);
      tip.life--; tip.w = Math.max(0.55, tip.w * 0.9975);
      segments++;
      if (tip.gen < 4 && rand() < 0.022) {
        sprout(x, y, tip.a + (rand() < 0.5 ? -1 : 1) * (0.45 + rand() * 0.5), tip.w * 0.72, tip.life * 0.7, tip.gen + 1, tip.home);
      }
      const out = x < -20 || y < -20 || x > NW + 20 || y > NH + 20;
      if (tip.life <= 0 || out || (best && bd < 5)) {
        if (best && bd < 5) bead(best, 7 * SC + 3);   // a hypha reached a node: it flares
        tips.splice(t, 1);
      }
    }
  }
  // Bud a new hypha off a random point of an existing one.
  function bud(n) {
    for (let k = 0; k < n && segments < CAP; k++) {
      const p = paths[Math.floor(rand() * paths.length)];
      if (!p || p.pts.length < 8) continue;
      const i = 2 * Math.floor(rand() * (p.pts.length / 2 - 1));
      sprout(p.pts[i], p.pts[i + 1], rand() * 6.2832, 1.4 * SC + 0.4, 120 + rand() * 160, 2, -1);
    }
  }
  // Start most of the way grown, so the first slide is not an empty field.
  for (let i = 0; i < 260 && tips.length; i++) step();
  bud(10);
  for (let i = 0; i < 90 && tips.length; i++) step();

  // ── GL ──
  const VERT = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FRAG = `
precision highp float;
uniform vec2 uRes, uPan, uNet;
uniform float uTime, uDark, uScale;
uniform sampler2D uTex;
uniform vec4 uL[${MAX_LENS}];   // x, y (device px, y up), radius, film seed
uniform vec3 uS[${MAX_LENS}];   // stretch direction xy, amount
uniform vec3 uP[${MAX_P}];      // pulse u, v, brightness

const vec3 CYAN = vec3(.365,.831,.878);
const vec3 VIOLET = vec3(.725,.604,.941);
const vec3 COBALT = vec3(.086,.314,.824);
const vec3 INDIGO = vec3(.416,.271,.78);
const float OVER = ${OVER.toFixed(3)};

float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}

vec3 ground(vec2 uv){
  float aspect = uRes.x/uRes.y;
  vec2 a = (uv-vec2(.86,1.05))*vec2(aspect,1.);
  vec2 b = (uv-vec2(.08,-.08))*vec2(aspect,1.);
  float glow = exp(-length(a*vec2(.8,1.3))*2.2);
  float low = exp(-length(b*vec2(.9,1.2))*2.6);
  vec3 night = vec3(.043,.051,.071) + vec3(.05,.2,.58)*glow*.55 + vec3(.25,.12,.42)*low*.22;
  vec3 sky = mix(vec3(.953,.965,.99), vec3(.86,.9,.98), smoothstep(.05,1.,uv.y));
  sky = mix(sky, vec3(.66,.78,.98), glow*.38);
  sky = mix(sky, vec3(.84,.8,.97), low*.3);
  return mix(sky, night, uDark);
}

// Hyphae, pulses and nodes at a point on the network (texture uv, y up).
vec3 netAt(vec2 t){
  vec3 n = texture2D(uTex, t).rgb;
  float pul = 0.;
  for (int i=0;i<${MAX_P};i++){
    vec2 d = (t-uP[i].xy)*uNet;
    float d2 = dot(d,d);
    pul += uP[i].z*(exp(-d2*.12) + .35*exp(-d2*.012));
  }
  return vec3(n.r, pul, n.b);
}

vec3 shade(vec2 uv, float boost){
  vec2 t = uv/OVER + uPan;
  vec3 g = ground(uv);
  vec3 n = netAt(t);
  float drift = smoothstep(.15,.95, t.x + .18*sin(t.y*5.+uTime*.05));
  float breathe = .82 + .18*sin(uTime*1.3 + t.x*9.);
  vec3 hd = mix(CYAN, VIOLET, drift);
  vec3 dark = g + hd*n.r*.36*boost + vec3(.8,.97,1.)*n.g*.9*boost + mix(CYAN, vec3(1.), .4)*n.b*breathe*.9;
  vec3 hl = mix(COBALT, INDIGO, drift);
  vec3 light = mix(g, hl, clamp(n.r*.3*boost,0.,1.));
  light = mix(light, COBALT*.9, clamp(n.g*.7*boost,0.,1.));
  light = mix(light, hl*.85, clamp(n.b*breathe*.8,0.,1.));
  return mix(light, dark, uDark);
}

void main(){
  vec2 p = gl_FragCoord.xy;
  vec2 uv = p/uRes;
  vec3 col = shade(uv, 1.);

  // What the lenses do to the ground around them: a shadow down and right of
  // each, with a caustic focused inside it where the glass gathers the light.
  for (int i=0;i<${MAX_LENS};i++){
    vec4 L = uL[i];
    if (L.z < 1.) continue;
    vec2 off = vec2(.2,-.26)*L.z;
    float ds = length((p-L.xy-off)/L.z);
    col *= 1. - smoothstep(1.5,.7,ds)*mix(.2,.32,uDark);
    vec2 cq = (p-L.xy-vec2(.34,-.42)*L.z)/L.z;
    float caus = exp(-dot(cq*vec2(1.6,2.4),cq*vec2(1.6,2.4))*2.2);
    col += mix(COBALT*.25, CYAN*.22, uDark)*caus;
  }

  for (int i=0;i<${MAX_LENS};i++){
    vec4 L = uL[i];
    if (L.z < 1.) continue;
    vec2 q = p - L.xy;
    // Gel: stretch along the direction of travel, thin across it.
    vec3 S = uS[i];
    if (S.z > .001) {
      float al = dot(q, S.xy);
      vec2 pe = q - S.xy*al;
      q = S.xy*al/(1.+S.z) + pe*(1.+S.z*.45);
    }
    float th = atan(q.y,q.x);
    float fi = float(i);
    float R = L.z*(1. + .013*sin(3.*th + uTime*.55 + fi*2.1) + .008*sin(5.*th - uTime*.8 + fi));
    float l = length(q)/R;
    if (l > 1.02) continue;

    float z = sqrt(max(0., 1.-l*l));
    vec2 dir = q/max(length(q), 1e-3);
    float f = l*.58 + (1.-z)*.95*l;
    vec3 c;
    c.r = shade((L.xy + dir*f*(1.-.04*(1.-z))*R)/uRes, 2.2).r;
    c.g = shade((L.xy + dir*f*R)/uRes, 2.2).g;
    c.b = shade((L.xy + dir*f*(1.+.04*(1.-z))*R)/uRes, 2.2).b;

    c *= mix(mix(vec3(.88,.92,1.), vec3(.86,.97,1.), uDark), vec3(1.), z);
    float far = smoothstep(-.2,.9, dot(dir, vec2(.6,-.8)));
    c *= 1. - .22*smoothstep(.55,1.,l)*far;

    float fres = pow(1.-z, 2.4);
    vec3 iri = mix(CYAN, VIOLET, .5+.5*sin(th*2. + l*6. + uTime*.12 + L.w*6.283));
    iri = mix(mix(COBALT, INDIGO, .5+.5*sin(th*2.+L.w*6.283)), iri, uDark);
    c += iri*fres*mix(.45,.6,uDark);
    c += vec3(1.)*smoothstep(.94,1.,l)*mix(.25,.3,uDark);

    vec2 u = q/R;
    vec2 s1 = u - vec2(-.36,.44);
    c += exp(-dot(s1*vec2(1.,1.7), s1*vec2(1.,1.7))*120.)*.95;
    vec2 b = u - vec2(-.2,.6);
    b = mat2(.83,.55,-.55,.83)*b;
    c += smoothstep(.09,0., max(abs(b.x)-.12, abs(b.y)-.012))*.1;
    vec2 s2 = u - vec2(.46,-.5);
    c += mix(COBALT, CYAN, uDark)*exp(-dot(s2,s2)*26.)*.2;

    float aa = smoothstep(1., 1.-1.6/R, l);
    col = mix(col, c, aa);
    if (aa > .999) break;
  }

  // Vignette, and a little grain so the gradients never band on a projector.
  vec2 vq = uv-.5;
  col *= 1. - dot(vq,vq)*mix(.12,.5,uDark);
  col += (hash(p + fract(uTime)*91.)-.5)/255.;
  gl_FragColor = vec4(col,1.);
}`;

  function compile(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  let prog;
  try {
    prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  } catch (e) {
    console.warn('lens: falling back to the still background', e);
    document.documentElement.classList.add('no-webgl'); window.Lens = noop; return;
  }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const aLoc = gl.getAttribLocation(prog, 'a');
  gl.enableVertexAttribArray(aLoc);
  gl.vertexAttribPointer(aLoc, 2, gl.FLOAT, false, 0, 0);
  const U = {};
  ['uRes', 'uPan', 'uNet', 'uTime', 'uDark', 'uScale', 'uTex', 'uL', 'uS', 'uP'].forEach(n => { U[n] = gl.getUniformLocation(prog, n); });

  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const upload = () => gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, net);
  upload();
  gl.uniform1i(U.uTex, 0);
  gl.uniform2f(U.uNet, NW, NH);

  let dpr = 1;
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(innerWidth * dpr);
    canvas.height = Math.round(innerHeight * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
    dirty = true;
  }

  // ── Motion: each lens and the pan ride a spring ──
  const lens = Array.from({ length: MAX_LENS }, (_, i) => ({ x: 0, y: 0, r: 0, vx: 0, vy: 0, vr: 0, tx: 0, ty: 0, tr: 0, seed: (i * 0.37 + 0.13) % 1 }));
  const pan = { x: 0.08, y: 0.06, vx: 0, vy: 0, tx: 0.08, ty: 0.06 };
  let dark = 1, darkT = 1, dirty = true;

  function set(list, index) {
    for (let i = 0; i < MAX_LENS; i++) {
      const L = lens[i], t = list[i];
      if (t) {
        if (L.r < 2) { L.x = t.x; L.y = t.y; L.vx = L.vy = 0; }   // a new lens appears where it is asked for
        L.tx = t.x; L.ty = t.y; L.tr = t.r;
      } else {
        L.tr = 0;
      }
      if (reduce) { L.x = L.tx; L.y = L.ty; L.r = L.tr; }
    }
    const span = 1 - 1 / OVER, k = index || 0;
    pan.tx = span * (0.5 + 0.45 * Math.sin(k * 1.9 + 0.4));
    pan.ty = span * (0.5 + 0.45 * Math.cos(k * 1.3 + 0.9));
    if (reduce) { pan.x = pan.tx; pan.y = pan.ty; }
    dirty = true;
  }
  function theme(isDark) { darkT = isDark ? 1 : 0; if (reduce) dark = darkT; dirty = true; }
  function grow(n) { bud(n || 3); }

  function spring(o, key, vkey, target, k, c, dt) {
    const a = -k * (o[key] - target) - c * o[vkey];
    o[vkey] += a * dt; o[key] += o[vkey] * dt;
  }

  // ── Pulses: a message running down a hypha ──
  const pulses = [];
  const P = new Float32Array(MAX_P * 3);
  function spawnPulse() {
    for (let k = 0; k < 6; k++) {
      const p = paths[Math.floor(rand() * paths.length)];
      if (p && p.pts.length > 40) { pulses.push({ p, i: 0, v: 0.9 + rand() * 1.4 }); return; }
    }
  }

  const Lb = new Float32Array(MAX_LENS * 4), Sb = new Float32Array(MAX_LENS * 3);
  let last = performance.now(), t0 = last, uploadEvery = 0;
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const time = (now - t0) / 1000;

    if (!reduce) {
      if (tips.length) { step(); if (++uploadEvery % 3 === 0) upload(); }
      else if (segments < CAP && rand() < 0.01) bud(1);   // keeps growing, slowly, all talk long
      if (pulses.length < MAX_P && rand() < 0.08) spawnPulse();
    }
    for (let i = pulses.length - 1; i >= 0; i--) {
      const q = pulses[i];
      q.i += q.v * 60 * dt;
      if (q.i >= q.p.pts.length / 2 - 1) pulses.splice(i, 1);
    }
    P.fill(0);
    pulses.slice(0, MAX_P).forEach((q, j) => {
      const n = q.p.pts.length / 2, k = Math.floor(q.i), f = q.i - k;
      const x = q.p.pts[2 * k] * (1 - f) + q.p.pts[2 * k + 2] * f;
      const y = q.p.pts[2 * k + 1] * (1 - f) + q.p.pts[2 * k + 3] * f;
      const life = Math.min(1, q.i / 8, (n - 1 - q.i) / 8);
      P[3 * j] = x / NW; P[3 * j + 1] = 1 - y / NH; P[3 * j + 2] = Math.max(0, life);
    });

    if (!reduce) {
      for (const L of lens) {
        spring(L, 'x', 'vx', L.tx, 34, 8.2, dt);
        spring(L, 'y', 'vy', L.ty, 34, 8.2, dt);
        spring(L, 'r', 'vr', L.tr, 40, 9.5, dt);
        if (L.r < 0) { L.r = 0; L.vr = 0; }
      }
      spring(pan, 'x', 'vx', pan.tx, 5, 4.4, dt);
      spring(pan, 'y', 'vy', pan.ty, 5, 4.4, dt);
      dark += (darkT - dark) * Math.min(1, dt * 4);
    }

    lens.forEach((L, i) => {
      Lb[4 * i] = L.x * dpr; Lb[4 * i + 1] = (innerHeight - L.y) * dpr; Lb[4 * i + 2] = L.r * dpr; Lb[4 * i + 3] = L.seed;
      const sp = Math.hypot(L.vx, L.vy);
      const s = L.r > 1 ? Math.min(0.18, sp / (L.r * 14)) : 0;
      Sb[3 * i] = sp ? L.vx / sp : 0; Sb[3 * i + 1] = sp ? -L.vy / sp : 0; Sb[3 * i + 2] = s;
    });

    gl.uniform2f(U.uRes, canvas.width, canvas.height);
    gl.uniform2f(U.uPan, pan.x, pan.y);
    gl.uniform1f(U.uTime, reduce ? 0 : time);
    gl.uniform1f(U.uDark, dark);
    gl.uniform1f(U.uScale, dpr);
    gl.uniform4fv(U.uL, Lb);
    gl.uniform3fv(U.uS, Sb);
    gl.uniform3fv(U.uP, P);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    if (reduce) { dirty = false; return; }
    requestAnimationFrame(frame);
  }

  addEventListener('resize', () => { resize(); if (reduce) requestAnimationFrame(frame); });
  resize();
  window.Lens = {
    set(list, index) { set(list, index); if (reduce) requestAnimationFrame(frame); },
    theme(isDark) { theme(isDark); if (reduce) requestAnimationFrame(frame); },
    grow,
  };
  requestAnimationFrame(frame);
})();
