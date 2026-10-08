// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// ── The lens (background) ──
// One glass lens over a dark field of drifting motes (the docs' spores). The
// lens magnifies what is under it with per-channel dispersion and a thin-film
// rim, and moves between slides like a drop of gel, stretching along its
// path. A slide can ask for up to three lenses (a big one and a bead or two);
// one it stops asking for shrinks away. A slide marked data-logo holds the
// Mycelium mark inside its first lens.
//
// Interface: window.Lens.set(lenses, index, logo) with lenses in viewport CSS
// px ({x, y, r}, y down), and window.Lens.theme(dark). deck.js drives both.
(function () {
  const canvas = document.getElementById('lens-bg');
  const noop = { set() {}, theme() {} };
  const gl = canvas && canvas.getContext('webgl', { antialias: false, alpha: false, premultipliedAlpha: false });
  if (!gl) { document.documentElement.classList.add('no-webgl'); window.Lens = noop; return; }

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MAX_LENS = 3;

  // ── GL ──
  const VERT = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FRAG = `
precision highp float;
uniform vec2 uRes;
uniform float uTime, uDark, uScale, uLogoOn;
uniform sampler2D uLogo;      // the mark, suspended in the first lens
uniform vec4 uL[${MAX_LENS}];   // x, y (device px, y up), radius, film seed
uniform vec3 uS[${MAX_LENS}];   // stretch direction xy, amount

const vec3 CYAN = vec3(.365,.831,.878);
const vec3 VIOLET = vec3(.725,.604,.941);
const vec3 COBALT = vec3(.086,.314,.824);
const vec3 INDIGO = vec3(.416,.271,.78);

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

// Motes: two parallax layers drifting upward (the docs' spores).
float spores(vec2 q){
  float acc = 0.;
  for (int L=0;L<2;L++){
    float fl = float(L), dens = mix(5.,12.,fl);
    vec2 p = q*dens + vec2(0., uTime*mix(.05,.025,fl)*dens);
    vec2 cell = floor(p), f = fract(p)-.5, h = fract(sin(vec2(dot(cell+fl*17.3,vec2(127.1,311.7)),dot(cell+fl*17.3,vec2(269.5,183.3))))*43758.5453);
    if (h.x > .8){
      vec2 o = (fract(sin(vec2(dot(cell+3.1,vec2(127.1,311.7)),dot(cell+3.1,vec2(269.5,183.3))))*43758.5453)-.5)*.5;
      float r = mix(.05,.14,h.y)*mix(1.,.6,fl);
      float a = 1.-smoothstep(r*mix(.2,.6,fl), r, length(f-o));
      acc += a*(.6+.4*sin(uTime*1.2+h.y*40.))*mix(.5,1.,fl);
    }
  }
  return acc;
}

vec3 shade(vec2 uv, float boost){
  vec3 g = ground(uv);
  float sp = spores(vec2(uv.x*uRes.x/uRes.y, uv.y));
  vec3 dark = g + sp*vec3(.45,.9,1.)*.2*min(boost,1.5);
  vec3 light = mix(g, vec3(.2,.4,.85), clamp(sp*.26*min(boost,1.5),0.,1.));
  return mix(light, dark, uDark);
}

void main(){
  vec2 p = gl_FragCoord.xy;
  vec2 uv = p/uRes;
  // The network is faint across the slide, where the text is, and comes up
  // only near a lens: the glass is where the room is shown.
  float focus = 0.;
  for (int i=0;i<${MAX_LENS};i++){
    vec4 L = uL[i];
    if (L.z < 1.) continue;
    float d = length(p-L.xy)/(L.z*2.3);
    focus = max(focus, exp(-d*d));
  }
  vec3 col = shade(uv, mix(.22, 1., focus));

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
    float R = L.z*(1. + .008*sin(3.*th + uTime*.35 + fi*2.1) + .004*sin(5.*th - uTime*.5 + fi));
    float l = length(q)/R;
    if (l > 1.02) continue;

    float z = sqrt(max(0., 1.-l*l));
    vec2 dir = q/max(length(q), 1e-3);
    float f = l*.58 + (1.-z)*.95*l;
    vec3 c;
    c.r = shade((L.xy + dir*f*(1.-.04*(1.-z))*R)/uRes, 2.5).r;
    c.g = shade((L.xy + dir*f*R)/uRes, 2.5).g;
    c.b = shade((L.xy + dir*f*(1.+.04*(1.-z))*R)/uRes, 2.5).b;

    // The mark, set in the first lens like something in a paperweight: read
    // at the refracted point so the glass magnifies and bends it, strongest
    // face-on and fading toward the rim.
    if (i == 0 && uLogoOn > .01) {
      vec2 luv = dir*f/1.24 + .5;
      if (luv.x > 0. && luv.y > 0. && luv.x < 1. && luv.y < 1.) {
        vec4 lg = texture2D(uLogo, luv);
        c = mix(c, lg.rgb*1.08, lg.a*uLogoOn*smoothstep(.2,.65,z));
      }
    }

    c *= mix(mix(vec3(.88,.92,1.), vec3(.86,.97,1.), uDark), vec3(1.), z);
    float far = smoothstep(-.2,.9, dot(dir, vec2(.6,-.8)));
    c *= 1. - .22*smoothstep(.55,1.,l)*far;

    float fres = pow(1.-z, 2.4);
    vec3 iri = mix(CYAN, VIOLET, .5+.5*sin(th*2. + l*6. + uTime*.12 + L.w*6.283));
    iri = mix(mix(COBALT, INDIGO, .5+.5*sin(th*2.+L.w*6.283)), iri, uDark);
    c += iri*fres*mix(.35,.45,uDark);
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
  ['uRes', 'uTime', 'uDark', 'uScale', 'uLogo', 'uLogoOn', 'uL', 'uS'].forEach(n => { U[n] = gl.getUniformLocation(prog, n); });

  // The mark. Until it has loaded the shader just doesn't draw it.
  const logoTex = gl.createTexture();
  let logoReady = false;
  gl.bindTexture(gl.TEXTURE_2D, logoTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
  gl.uniform1i(U.uLogo, 0);
  const img = new Image();
  img.onload = () => {
    gl.bindTexture(gl.TEXTURE_2D, logoTex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    logoReady = true;
    dirty = true;
    if (reduce) requestAnimationFrame(frame);
  };
  img.src = window.LENS_LOGO || 'logo-512.png';

  let dpr = 1;
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(innerWidth * dpr);
    canvas.height = Math.round(innerHeight * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
    dirty = true;
  }

  // ── Motion: each lens rides a spring ──
  const lens = Array.from({ length: MAX_LENS }, (_, i) => ({ x: 0, y: 0, r: 0, vx: 0, vy: 0, vr: 0, tx: 0, ty: 0, tr: 0, seed: (i * 0.37 + 0.13) % 1 }));
  let dark = 1, darkT = 1, logo = 0, logoT = 0, dirty = true;

  function set(list, withLogo) {
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
    logoT = withLogo ? 1 : 0;
    if (reduce) logo = logoT;
    dirty = true;
  }
  function theme(isDark) { darkT = isDark ? 1 : 0; if (reduce) dark = darkT; dirty = true; }

  function spring(o, key, vkey, target, k, c, dt) {
    const a = -k * (o[key] - target) - c * o[vkey];
    o[vkey] += a * dt; o[key] += o[vkey] * dt;
  }

  const Lb = new Float32Array(MAX_LENS * 4), Sb = new Float32Array(MAX_LENS * 3);
  let last = performance.now(), t0 = last;
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const time = (now - t0) / 1000;

    if (!reduce) {
      for (const L of lens) {
        spring(L, 'x', 'vx', L.tx, 34, 8.2, dt);
        spring(L, 'y', 'vy', L.ty, 34, 8.2, dt);
        spring(L, 'r', 'vr', L.tr, 40, 9.5, dt);
        if (L.r < 0) { L.r = 0; L.vr = 0; }
      }
      dark += (darkT - dark) * Math.min(1, dt * 4);
      logo += (logoT - logo) * Math.min(1, dt * 3);
    }

    lens.forEach((L, i) => {
      Lb[4 * i] = L.x * dpr; Lb[4 * i + 1] = (innerHeight - L.y) * dpr; Lb[4 * i + 2] = L.r * dpr; Lb[4 * i + 3] = L.seed;
      const sp = Math.hypot(L.vx, L.vy);
      const s = L.r > 1 ? Math.min(0.18, sp / (L.r * 14)) : 0;
      Sb[3 * i] = sp ? L.vx / sp : 0; Sb[3 * i + 1] = sp ? -L.vy / sp : 0; Sb[3 * i + 2] = s;
    });

    gl.bindTexture(gl.TEXTURE_2D, logoTex);
    gl.uniform2f(U.uRes, canvas.width, canvas.height);
    gl.uniform1f(U.uTime, reduce ? 0 : time);
    gl.uniform1f(U.uDark, dark);
    gl.uniform1f(U.uScale, dpr);
    gl.uniform1f(U.uLogoOn, logoReady ? logo : 0);
    gl.uniform4fv(U.uL, Lb);
    gl.uniform3fv(U.uS, Sb);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    if (reduce) { dirty = false; return; }
    requestAnimationFrame(frame);
  }

  addEventListener('resize', () => { resize(); if (reduce) requestAnimationFrame(frame); });
  resize();
  window.Lens = {
    set(list, index, withLogo) { set(list, withLogo); if (reduce) requestAnimationFrame(frame); },
    theme(isDark) { theme(isDark); if (reduce) requestAnimationFrame(frame); },
  };
  requestAnimationFrame(frame);
})();
