// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** How `links.py`'s four `_resolve` failures read to a person. Shared so the
 *  detail view and the graph name the same failure the same way. */
export const LINK_ERRORS: Record<string, string> = {
  not_found: "no such memory",
  no_anchor: "no such section",
  not_expandable: "target is not expandable",
  cross_room: "cross-room links are not supported",
};

export function linkErrorLabel(error?: string | null): string {
  if (!error) return "broken";
  return LINK_ERRORS[error] ?? error;
}

/**
 * Whether an unresolved link is a *defect* rather than a limitation.
 *
 * `myc://rooms/other/key` is documented, legitimate syntax that simply doesn't
 * resolve room-locally — counting it alongside a typo would report a room as
 * broken for doing something correct. The other three failures each mean the
 * author wrote something that doesn't exist.
 */
export function isBrokenLinkError(error?: string | null): boolean {
  return error !== "cross_room";
}
