// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What @reviewer is told when @builder's mention wakes it: the wake message
// the runner types into its terminal, in the design the wake message is moving
// to (each message's text in a `│` gutter, the ask in full, then the numbered
// commands). The web app has no view of an agent's terminal, so the take shows
// it as a card over the app, the one thing on screen that isn't the app's own UI.
//
// `record.mjs` inlines this file for an `eval:file:wake-card.js` action; it
// shows the card, and `eval:window.__wakeCard.hide()` takes it down.
(() => {
  const TASK = "work/customers-are-charged-twice-when-they-double-cli";
  const TITLE = "Customers are charged twice when they double-click Pay";
  // [kind, text]: head, label (a "Why:" line), frame (the gutter), next, blank.
  // The layout and wording are the wake message's own (PR #1353); the long
  // `(lands in …)` note goes on its own line so the card stays readable.
  const lines = [
    ["head", "mycelium wake for @reviewer in checkout"],
    ["blank"],
    ["label", "Why:     ", `@builder mentioned you in "${TITLE}" (${TASK})`],
    ["label", "Since:   ", "your last turn, 14m ago: 2 in this thread (@sam-rivera 1, @builder 1), 3 elsewhere"],
    ["blank"],
    ["top", `@builder · now · in "${TITLE}" · 7f3a9c21`],
    ["frame", "Taking this. I can reproduce it: two quick taps on Pay send two payment requests,"],
    ["frame", "and Stripe charges both. @reviewer, want to review the fix when it's up?"],
    ["bottom"],
    ["blank"],
    ["label", "Next:    ", "1. mycelium await --room checkout --handle reviewer --json --timeout 5"],
    ["note", "            (every ask in this wake, in full; it marks them read and tells the room you're on it)"],
    ["label", "         ", `2. mycelium respond --room checkout --handle reviewer --task ${TASK} --body "..."`],
    ["note", `            (lands in "${TITLE}")`],
    ["blank"],
    ["label", "Tasks:   ", 'yours "Add Apple Pay to checkout" (12m ago)'],
    ["label", "Board:   ", `@sam-rivera filed "${TITLE}"`],
    ["label", "         ", `@builder claimed "${TITLE}"`],
    ["label", "         ", "open now: 2 held, 3 new"],
  ];

  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const me = (s) => esc(s).replace("@reviewer,", '<span class="wc-me">@reviewer</span>,');
  const html = lines
    .map(([kind, a = "", b = ""]) => {
      if (kind === "head") return `<div class="wc-head">${esc(a)}</div>`;
      if (kind === "label") return `<div><span class="wc-label">${esc(a)}</span>${esc(b)}</div>`;
      if (kind === "top") return `<div><span class="wc-gutter">┌ </span><span class="wc-from">${esc(a)}</span></div>`;
      if (kind === "frame") return `<div><span class="wc-gutter">│ </span><span class="wc-body">${me(a)}</span></div>`;
      if (kind === "bottom") return `<div class="wc-gutter">└</div>`;
      if (kind === "note") return `<div class="wc-label">${esc(a)}</div>`;
      return "<div>&nbsp;</div>";
    })
    .join("");

  const style = `
    #wake-card { position: fixed; inset: 0; z-index: 2147483000; display: grid; place-items: center;
      background: rgb(0 0 0 / 0.5); opacity: 0; transition: opacity 260ms ease; pointer-events: none; }
    #wake-card.on { opacity: 1; }
    #wake-card .wc-win { width: 1240px; border-radius: 12px; overflow: hidden;
      background: #0b0f14; border: 1px solid rgb(255 255 255 / 0.12);
      box-shadow: 0 30px 80px rgb(0 0 0 / 0.6); transform: translateY(10px) scale(0.98);
      transition: transform 260ms ease; }
    #wake-card.on .wc-win { transform: none; }
    #wake-card .wc-bar { display: flex; align-items: center; gap: 8px; padding: 10px 14px;
      background: #141a22; border-bottom: 1px solid rgb(255 255 255 / 0.08);
      font: 500 13px/1 "IBM Plex Sans", system-ui, sans-serif; color: #9aa4b2; }
    #wake-card .wc-dot { width: 11px; height: 11px; border-radius: 50%; background: #3a4350; }
    #wake-card .wc-title { margin-left: 8px; }
    #wake-card .wc-text { margin: 0; padding: 18px 22px 22px;
      font: 13px/1.55 "IBM Plex Mono", ui-monospace, Menlo, monospace; color: #d6dde6; white-space: pre; }
    #wake-card .wc-head { color: #7ee0d0; font-weight: 600; }
    #wake-card .wc-label { color: #8b95a3; }
    #wake-card .wc-gutter { color: #5d6875; }
    #wake-card .wc-from { color: #8b95a3; }
    #wake-card .wc-body { color: #eef2f7; }
    #wake-card .wc-me { color: #7ee0d0; }
  `;

  const show = () => {
    if (document.getElementById("wake-card")) return;
    const root = document.createElement("div");
    root.id = "wake-card";
    root.innerHTML =
      `<style>${style}</style><div class="wc-win"><div class="wc-bar">` +
      `<span class="wc-dot"></span><span class="wc-dot"></span><span class="wc-dot"></span>` +
      `<span class="wc-title">reviewer · Claude Code in herdr, on Sam's machine</span></div>` +
      `<div class="wc-text">${html}</div></div>`;
    document.body.appendChild(root);
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add("on")));
  };
  const hide = () => {
    const root = document.getElementById("wake-card");
    if (!root) return;
    root.classList.remove("on");
    setTimeout(() => root.remove(), 300);
  };
  window.__wakeCard = { show, hide };
  show();
})();
