// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A flag parser with one unusual requirement: `shot term` has to hand the rest
 * of the line to somebody else.
 *
 * `shot term mycelium memory ls --room atlas` contains two flag namespaces, and
 * `--room` belongs to the child. So a command can declare `stopAtPositional`,
 * after which everything is collected verbatim — the same convention `env` and
 * `timeout` use. An explicit `--` does the same thing at any point.
 */

/**
 * @typedef {"boolean"|"string"|"number"|"list"|"map"} FlagType
 * @typedef {{type: FlagType, alias?: string, dest?: string, help?: string, value?: string}} FlagSpec
 */

const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

/**
 * @param {string[]} argv
 * @param {Record<string, FlagSpec>} spec
 * @param {{stopAtPositional?: boolean}} [opts]
 */
export function parse(argv, spec, opts = {}) {
  /** @type {Record<string, any>} */
  const flags = {};
  /** @type {string[]} */
  const rest = [];
  const byAlias = new Map();
  for (const [name, s] of Object.entries(spec)) if (s.alias) byAlias.set(s.alias, name);

  const set = (name, s, raw) => {
    const dest = s.dest ?? camel(name);
    if (s.type === "boolean") flags[dest] = raw;
    else if (s.type === "number") flags[dest] = Number(raw);
    else if (s.type === "list") (flags[dest] ??= []).push(raw);
    else if (s.type === "map") {
      const eq = String(raw).indexOf("=");
      if (eq === -1) throw new Error(`--${name} expects key=value, got ${raw}`);
      (flags[dest] ??= {})[String(raw).slice(0, eq)] = String(raw).slice(eq + 1);
    } else flags[dest] = raw;
  };

  let i = 0;
  let passthrough = false;
  for (; i < argv.length; i++) {
    const arg = argv[i];
    if (passthrough) {
      rest.push(arg);
      continue;
    }
    if (arg === "--") {
      passthrough = true;
      continue;
    }
    if (arg.startsWith("--")) {
      let [name, inline] = splitOnce(arg.slice(2), "=");
      let negated = false;
      if (!spec[name] && name.startsWith("no-") && spec[name.slice(3)]?.type === "boolean") {
        name = name.slice(3);
        negated = true;
      }
      const s = spec[name];
      if (!s) throw new Error(`unknown option --${name}`);
      if (s.type === "boolean") set(name, s, !negated);
      else set(name, s, inline ?? argv[++i]);
      continue;
    }
    if (arg.startsWith("-") && arg.length > 1 && !/^-\d/.test(arg)) {
      const name = byAlias.get(arg.slice(1));
      const s = name && spec[name];
      if (!s) throw new Error(`unknown option ${arg}`);
      if (s.type === "boolean") set(name, s, true);
      else set(name, s, argv[++i]);
      continue;
    }
    rest.push(arg);
    if (opts.stopAtPositional) passthrough = true;
  }
  return { flags, rest };
}

function splitOnce(s, sep) {
  const i = s.indexOf(sep);
  return i === -1 ? [s, undefined] : [s.slice(0, i), s.slice(i + 1)];
}

/** Render a flag spec as aligned `--flag  help` lines. */
export function helpFor(spec) {
  const rows = Object.entries(spec).map(([name, s]) => {
    const left = [s.alias ? `-${s.alias},` : "   ", `--${name}`, s.value ?? (s.type === "boolean" ? "" : `<${s.type}>`)]
      .filter(Boolean)
      .join(" ");
    return [left, s.help ?? ""];
  });
  const width = Math.max(...rows.map(([l]) => l.length));
  return rows.map(([l, r]) => `  ${l.padEnd(width)}  ${r}`).join("\n");
}
