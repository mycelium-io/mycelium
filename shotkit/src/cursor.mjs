// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What a recording adds to a page: a cursor you can see, a click you can see,
 * and a camera that can push in.
 *
 * Headless Chromium draws no pointer, and a screen recording without one is
 * unreadable — things happen and nothing says why. So the cursor is drawn by
 * the page itself, as an overlay that follows the *real* mouse. That direction
 * matters: the recorder moves Playwright's actual mouse, hover states light up
 * under it for real, and the drawn arrow is downstream of the same events the
 * app sees rather than a second animation that has to be kept in step with it.
 *
 * The camera is a transform on the document, not a crop in the encoder. A page
 * the browser zooms re-rasterizes its text at the new size, so a push-in lands
 * on type sharper than the frame it started from; cropping the video afterwards
 * could only make the same pixels bigger.
 *
 * `installOverlay` is serialized into the page by `addInitScript`, so it closes
 * over nothing and reads nothing from this module — every constant it needs
 * arrives in its one argument.
 */

/** Where the arrow's tip sits inside its own 26x30 box. */
export const HOTSPOT = { x: 5, y: 3 };

/**
 * @typedef {object} OverlayOptions
 * @property {boolean} [cursor] draw the pointer at all
 * @property {number} [startX] @property {number} [startY] where it starts
 * @property {number} [follow] 0-1, how hard the drawn cursor chases the real one
 * @property {string} [accent] ripple color
 * @property {number} [size] arrow height in CSS px
 */

/** @type {Required<OverlayOptions> & {hotspotX:number, hotspotY:number}} */
export const OVERLAY_DEFAULTS = {
  cursor: true,
  startX: 40,
  startY: 40,
  follow: 0.42,
  accent: "#5cc7d2",
  size: 30,
  hotspotX: HOTSPOT.x,
  hotspotY: HOTSPOT.y,
};

/**
 * Runs in the page, on every document. Installs `window.__shotkit`:
 *
 *   at(x, y)                aim the drawn cursor (real mouse events do this too;
 *                           the recorder calls it to seed and to land exactly)
 *   snap(x, y)              teleport, no easing
 *   camera(z, x, y, ms)     push in to `z` around viewport point (x, y)
 *   press(down) / show(on)  force the pressed look; hide the pointer
 *   state()                 what the recorder asserts against
 *
 * @param {Required<OverlayOptions> & {hotspotX:number, hotspotY:number}} opts
 */
export function installOverlay(opts) {
  if (window.__shotkit) return;

  const st = {
    x: opts.startX,
    y: opts.startY,
    tx: opts.startX,
    ty: opts.startY,
    anim: null,
    down: false,
    ticking: false,
    lastPress: -Infinity,
    visible: opts.cursor,
    cam: { z: 1, tx: 0, ty: 0 },
    mounted: false,
  };
  let root = null;
  let arrow = null;

  const CSS = `
    #__shotkit-overlay, #__shotkit-overlay * { pointer-events: none !important; }
    #__shotkit-overlay {
      position: fixed; inset: 0; margin: 0; padding: 0; border: 0;
      width: 100%; height: 100%; max-width: none; max-height: none;
      background: transparent; overflow: visible; z-index: 2147483647;
    }
    #__shotkit-overlay::backdrop { background: transparent; }
    #__shotkit-cursor {
      position: absolute; left: 0; top: 0;
      width: ${(opts.size * 26) / 30}px; height: ${opts.size}px;
      transform-origin: ${(opts.hotspotX / 26) * 100}% ${(opts.hotspotY / 30) * 100}%;
      filter: drop-shadow(0 2px 5px rgba(0,0,0,.42));
      transition: opacity 160ms linear;
      will-change: transform;
    }
    #__shotkit-cursor svg { display: block; width: 100%; height: 100%; }
    .__shotkit-ripple {
      position: absolute; border-radius: 50%;
      border: 2.5px solid ${opts.accent};
      background: ${opts.accent}33;
      box-shadow: 0 0 12px ${opts.accent}66;
    }
  `;

  const ARROW = `<svg viewBox="0 0 26 30" xmlns="http://www.w3.org/2000/svg">
      <path d="M5 2.6 L5 24.4 L10.7 18.8 L14.2 26.8 L17.9 25.1 L14.4 17.3 L21.8 17.1 Z"
            fill="#ffffff" stroke="rgba(12,14,17,.62)" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;

  function mount() {
    if (!document.documentElement) return;
    // A page that replaces its body (setContent, a client-side route change)
    // takes the overlay with it, so "mounted" means *still attached*.
    if (st.mounted && root && root.isConnected) return;
    if (!document.getElementById("__shotkit-style")) {
      const style = document.createElement("style");
      style.id = "__shotkit-style";
      style.textContent = CSS;
      (document.head ?? document.documentElement).appendChild(style);
    }

    root = document.createElement("div");
    root.id = "__shotkit-overlay";
    root.setAttribute("aria-hidden", "true");
    arrow = document.createElement("div");
    arrow.id = "__shotkit-cursor";
    arrow.innerHTML = ARROW;
    root.appendChild(arrow);
    (document.body ?? document.documentElement).appendChild(root);

    // The top layer is the one place a fixed element ignores an ancestor
    // transform, which is exactly what the camera does to the document: the
    // cursor has to stay the size of a cursor while the page is pushed in.
    try {
      root.setAttribute("popover", "manual");
      root.showPopover();
    } catch {
      /* no popover here: the cursor rides the zoom, which is survivable */
    }
    st.mounted = true;
    draw();
    // One loop for the life of the document, however often the overlay has to
    // be put back: remounting is not a reason to start a second one.
    if (!st.ticking) {
      st.ticking = true;
      requestAnimationFrame(tick);
    }
  }

  function draw() {
    if (!arrow) return;
    const x = st.x - opts.hotspotX;
    const y = st.y - opts.hotspotY;
    arrow.style.transform = `translate(${x}px, ${y}px) scale(${st.down ? 0.86 : 1})`;
    arrow.style.opacity = st.visible ? "1" : "0";
  }

  /** Ease in and out, the same curve the recorder walks the real mouse along. */
  function ease(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  }

  /**
   * Two ways the pointer moves, and the reason for both.
   *
   * A travel the recorder asked for is animated here, in the page, off rAF: it
   * is smooth at the display's rate whatever the round-trip cost of driving the
   * browser from outside, and it does not depend on input events reaching this
   * script at all — headless Chromium coalesces mouse moves and flushes them
   * with its frames, which is a thin thread to hang a recording on.
   *
   * Anything else that moves the mouse — a stray `locator.click()`, a real
   * pointer — is chased with a light lerp, which irons out sparse events and
   * gives the cursor a little weight.
   */
  function tick() {
    requestAnimationFrame(tick);
    if (st.anim) {
      const p = Math.min(1, (performance.now() - st.anim.t0) / st.anim.ms);
      const e = ease(p);
      st.x = st.anim.fx + (st.anim.x - st.anim.fx) * e;
      st.y = st.anim.fy + (st.anim.y - st.anim.fy) * e;
      if (p >= 1) st.anim = null;
      draw();
      return;
    }
    const dx = st.tx - st.x;
    const dy = st.ty - st.y;
    if (Math.abs(dx) < 0.05 && Math.abs(dy) < 0.05) {
      if (st.x === st.tx && st.y === st.ty) return;
      st.x = st.tx;
      st.y = st.ty;
    } else {
      st.x += dx * opts.follow;
      st.y += dy * opts.follow;
    }
    draw();
  }

  function ripple() {
    if (!root) return;
    const el = document.createElement("div");
    const size = 18;
    el.className = "__shotkit-ripple";
    el.style.left = `${st.tx - size / 2}px`;
    el.style.top = `${st.ty - size / 2}px`;
    el.style.width = `${size}px`;
    el.style.height = `${size}px`;
    root.appendChild(el);
    const done = () => el.remove();
    try {
      // Held bright for the first third: a ring that fades on the way out is
      // gone by the second frame at 30fps, which reads as no click at all.
      const anim = el.animate(
        [
          { transform: "scale(.4)", opacity: 1, offset: 0 },
          { transform: "scale(1.5)", opacity: 0.9, offset: 0.35 },
          { transform: "scale(3.4)", opacity: 0, offset: 1 },
        ],
        { duration: 540, easing: "cubic-bezier(.22,.7,.3,1)" },
      );
      anim.addEventListener("finish", done);
    } catch {
      done();
    }
  }

  /**
   * Push in to `z` around viewport point (x, y).
   *
   * The transform is `translate(t) scale(z)` off a `0 0` origin, so aiming it is
   * arithmetic rather than origin bookkeeping: a point `u` in the unzoomed
   * viewport renders at `t + z*u`. `t` is then clamped so the frame only ever
   * crops into what is already on screen — a push-in near an edge slides back
   * inside instead of panning off the page.
   *
   * The clamp is not politeness: a page paints what its layout viewport covers
   * and nothing else, so a camera that wandered outside the frame would be
   * pointed at document nobody has drawn.
   */
  function camera(z, x, y, ms) {
    const de = document.documentElement;
    const W = window.innerWidth;
    const H = window.innerHeight;
    const zoom = Math.max(1, Number(z) || 1);
    const ux = (x - st.cam.tx) / st.cam.z;
    const uy = (y - st.cam.ty) / st.cam.z;
    const tx = Math.min(0, Math.max(W * (1 - zoom), W / 2 - zoom * ux));
    const ty = Math.min(0, Math.max(H * (1 - zoom), H / 2 - zoom * uy));
    st.cam = { z: zoom, tx, ty };
    de.style.transformOrigin = "0 0";
    de.style.willChange = zoom === 1 ? "" : "transform";
    de.style.transition = ms > 0 ? `transform ${ms}ms cubic-bezier(.33,.1,.24,1)` : "none";
    // The scroll offset is applied after the transform, so it has to come back
    // out of the translate for the arithmetic above to hold on a scrolled page.
    const sx = window.scrollX * (zoom - 1);
    const sy = window.scrollY * (zoom - 1);
    de.style.transform = zoom === 1 ? "" : `translate(${tx - sx}px, ${ty - sy}px) scale(${zoom})`;
    return { z: zoom, tx, ty };
  }

  addEventListener("mousemove", (e) => {
    st.tx = e.clientX;
    st.ty = e.clientY;
  }, { capture: true, passive: true });
  addEventListener("mousedown", () => {
    st.down = true;
    // A press the recorder announced has already drawn its ring; the real event
    // arrives a moment later and must not stack a second one on top of it.
    if (performance.now() - st.lastPress > 400) ripple();
    draw();
  }, { capture: true, passive: true });
  addEventListener("mouseup", () => {
    st.down = false;
    draw();
  }, { capture: true, passive: true });

  window.__shotkit = {
    mount,
    at(x, y) {
      st.tx = x;
      st.ty = y;
    },
    /** Travel there over `ms`, on the page's own clock. */
    glide(x, y, ms) {
      if (!(ms > 0)) return this.snap(x, y);
      st.anim = { fx: st.x, fy: st.y, x, y, t0: performance.now(), ms };
      st.tx = x;
      st.ty = y;
      return undefined;
    },
    snap(x, y) {
      st.anim = null;
      st.x = x;
      st.tx = x;
      st.y = y;
      st.ty = y;
      draw();
    },
    press(down) {
      st.down = Boolean(down);
      if (down) {
        st.lastPress = performance.now();
        ripple();
      }
      draw();
    },
    show(on) {
      st.visible = Boolean(on);
      draw();
    },
    camera,
    state: () => ({ ...st, cam: { ...st.cam } }),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
  // A client-side route change that replaces the tree we appended to would
  // otherwise lose the cursor mid-take; remounting is cheap and idempotent.
  setInterval(mount, 500);
}
