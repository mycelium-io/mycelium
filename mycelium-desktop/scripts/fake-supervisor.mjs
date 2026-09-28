#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A stand-in for `mycelium desktop serve`, for working on the app alone.
// Run the app with MYCELIUM_DESKTOP_SUPERVISOR pointing here. It speaks the
// same JSON lines, brings each component up in turn, and reports the room UI
// at $FAKE_UI_URL (default http://localhost:3100, a `pnpm dev` of the
// frontend). It exits when stdin closes or on SIGTERM, like the real one.

const args = process.argv.slice(2);
const flag = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
};
const mode = flag("--mode") === "client" ? "client" : "hub";
const hubUrl = flag("--hub-url");
const ui = mode === "hub" ? (process.env.FAKE_UI_URL ?? "http://localhost:3100") : hubUrl;
const api = mode === "hub" ? "http://127.0.0.1:8000" : hubUrl;

const names = ["slim", "hub", "ui", "runner"];
const components = Object.fromEntries(
  names.map((n) => [n, { state: mode === "client" && n !== "runner" ? "disabled" : "starting", detail: null }]),
);
const emit = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const status = () => emit({ type: "status", mode, ui_url: ui, api_url: api, components });

status();
const order = names.filter((n) => components[n].state !== "disabled");
let step = 0;
const timer = setInterval(() => {
  if (step >= order.length) return clearInterval(timer);
  const name = order[step++];
  emit({ type: "log", component: name, line: `${name} is up` });
  components[name].state = "running";
  status();
}, 500);

const stop = () => process.exit(0);
process.on("SIGTERM", stop);
process.stdin.on("end", stop);
process.stdin.resume();
