// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** One formatter per set of options, made once. `toLocaleString` and its
 *  siblings build a new formatter on every call, and Safari is slow at that: a
 *  long channel formatting each message's time again on every draw spent most
 *  of a seam drag on it. The output is the same, in the browser's locale. */
const formatters = new Map<string, Intl.DateTimeFormat>();

export function formatDate(date: Date, options: Intl.DateTimeFormatOptions): string {
  const key = JSON.stringify(options);
  let format = formatters.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(undefined, options);
    formatters.set(key, format);
  }
  return format.format(date);
}
