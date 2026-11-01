// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The take's time skip: the app fades to dark with a line saying how much
// later it is, the room grows underneath (`POST /api/demo/busy`), and
// `eval:window.__fade.out()` fades back in on it.
//
// `record.mjs` inlines this file for an `eval:file:fade.js` action.
(() => {
  const style = `
    #demo-fade { position: fixed; inset: 0; z-index: 2147483000; display: grid; place-items: center;
      background: #07090c; opacity: 0; transition: opacity 700ms ease; pointer-events: none; }
    #demo-fade.on { opacity: 1; }
    #demo-fade span { font: 400 44px/1.2 "Cormorant Garamond", Georgia, serif; color: #e8edf2;
      letter-spacing: 0.01em; opacity: 0; transition: opacity 500ms ease 450ms; }
    #demo-fade.on span { opacity: 1; }
  `;
  const root = document.createElement("div");
  root.id = "demo-fade";
  root.innerHTML = `<style>${style}</style><span>A week later</span>`;
  document.body.appendChild(root);
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add("on")));
  window.__fade = {
    out() {
      root.style.transition = "opacity 900ms ease";
      root.classList.remove("on");
      setTimeout(() => root.remove(), 1000);
    },
  };
  // The room grows while the screen is dark.
  void fetch("/api/demo/busy", { method: "POST" });
})();
