// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** True when `text` is a single JSON object/array (for Raw → format toggle). */
export function isJsonRawText(text: string): boolean {
  return parseJsonRawText(text) !== null;
}

export function parseJsonRawText(text: string): unknown | null {
  const trimmed = text.trim();
  if (!trimmed || !(trimmed.startsWith("{") || trimmed.startsWith("["))) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

export function prettyPrintJsonRawText(text: string): string | null {
  const parsed = parseJsonRawText(text);
  return parsed === null ? null : JSON.stringify(parsed, null, 2);
}
