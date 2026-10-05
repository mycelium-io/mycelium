// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * This browser's device key, and what it signs for a machine it is paired with.
 *
 * A runner normally needs approval on its machine before starting a job.
 * A paired device's signed jobs start without approval instead
 * (`mycelium/runner/pairing.py`).
 * The key is ECDSA P-256, made here by WebCrypto as non-extractable and kept
 * in IndexedDB: the page can sign with it but nothing, the page included, can
 * read the private half out. Inside the Mac app the same holds in its web
 * view's storage.
 *
 * Pairing proves the code: an HMAC over this device's name and key, keyed by
 * PBKDF2 of the whole code, which only the machine that printed it can check.
 * A signature covers the exact JSON sent beside the job, which the machine
 * checks against the job it receives.
 */

import { useEffect, useState } from "react";
import type { DeviceSignature, Runner } from "@/lib/api";

const DB = "mycelium-device";
const STORE = "keys";
const SLOT = "device";
/** Must match `pairing.KDF_ROUNDS` on the runner. */
const KDF_ROUNDS = 200_000;
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const CODE_LEN = 12;
const OFFER_ID_LEN = 4;
/** Said when this browser makes its key, so every view of it reads it again. */
const KEY_CHANGED = "mycelium:device-key";

export interface DeviceKey {
  /** 16 hex characters: SHA-256 of the public point, as the runner computes it. */
  id: string;
  x: string;
  y: string;
  privateKey: CryptoKey;
}

function b64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (const b of arr) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64url(text: string): Uint8Array {
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

/** A key id as a person compares it with what the machine prints: `3f9a 12c4 b0de 7781`. */
export function fingerprint(id: string): string {
  return id.match(/.{1,4}/g)?.join(" ") ?? id;
}

export async function keyIdOf(x: string, y: string): Promise<string> {
  const point = new Uint8Array([4, ...unb64url(x), ...unb64url(y)]);
  return hex(await crypto.subtle.digest("SHA-256", point)).slice(0, 16);
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function slot<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = run(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

/** This browser's key, or null when it has none yet (or can't keep one). */
export async function loadDeviceKey(): Promise<DeviceKey | null> {
  if (typeof indexedDB === "undefined" || !globalThis.crypto?.subtle) return null;
  try {
    const found = await slot<DeviceKey | undefined>("readonly", (s) => s.get(SLOT));
    return found ?? null;
  } catch {
    return null;
  }
}

/** This browser's key, made the first time it pairs. Throws when the browser can't keep one. */
export async function ensureDeviceKey(): Promise<DeviceKey> {
  const existing = await loadDeviceKey();
  if (existing) return existing;
  if (typeof indexedDB === "undefined" || !globalThis.crypto?.subtle) {
    throw new Error("This browser can't keep a device key (it needs a secure page and site storage).");
  }
  const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const key: DeviceKey = { id: await keyIdOf(jwk.x!, jwk.y!), x: jwk.x!, y: jwk.y!, privateKey: pair.privateKey };
  await slot("readwrite", (s) => s.put(key, SLOT));
  return key;
}

/** This browser's key id once read, or null while reading or when it has none. */
export function useDeviceKeyId(): string | null {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void loadDeviceKey().then((k) => {
      if (live) setId(k?.id ?? null);
    });
    const onChange = () =>
      void loadDeviceKey().then((k) => {
        if (live) setId(k?.id ?? null);
      });
    window.addEventListener(KEY_CHANGED, onChange);
    return () => {
      live = false;
      window.removeEventListener(KEY_CHANGED, onChange);
    };
  }, []);
  return id;
}

// ── pairing ──────────────────────────────────────────────────────────────────

/** A code as typed, in its one spelling (Crockford: O reads as 0, I and L as 1); null if it isn't one. */
export function normalizeCode(code: string): string | null {
  const clean = code.replace(/[\s-]/g, "").toUpperCase().replace(/O/g, "0").replace(/[IL]/g, "1");
  if (clean.length !== CODE_LEN || [...clean].some((c) => !ALPHABET.includes(c))) return null;
  return clean;
}

/** What `POST /api/runners/pair` takes: the code's public part, this device, and the proof. */
export async function pairRequest(code: string, name: string) {
  const clean = normalizeCode(code);
  if (!clean) throw new Error("That isn't a pairing code: it's 12 letters and digits, like ABCD-EFGH-JKMN.");
  const key = await ensureDeviceKey();
  window.dispatchEvent(new Event(KEY_CHANGED));
  const proof = await pairProof(clean, name, key.x, key.y);
  return {
    body: { code_id: clean.slice(0, OFFER_ID_LEN), name, key: { x: key.x, y: key.y }, proof },
    keyId: key.id,
  };
}

/** The HMAC a machine checks a pairing by (`pairing.proof` on the runner). `code` is normalized. */
export async function pairProof(code: string, name: string, x: string, y: string): Promise<string> {
  const enc = new TextEncoder();
  const offer = code.slice(0, OFFER_ID_LEN);
  const base = await crypto.subtle.importKey("raw", enc.encode(code), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: enc.encode(`mycelium-pair:${offer}`), iterations: KDF_ROUNDS },
    base,
    256,
  );
  const mac = await crypto.subtle.importKey("raw", bits, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const message = enc.encode(`mycelium-pair-v1\n${offer}\n${name}\n${x}\n${y}`);
  return b64url(await crypto.subtle.sign("HMAC", mac, message));
}

// ── signing ──────────────────────────────────────────────────────────────────

/** A runner's pairing with this browser's key, when it has a live one. */
export function pairingWith(runner: Pick<Runner, "pairings">, keyId: string | null) {
  if (!keyId) return null;
  const now = Date.now();
  return (
    runner.pairings?.find((p) => p.key === keyId && (!p.expires_at || Date.parse(p.expires_at) > now)) ?? null
  );
}

/** The fields a job is signed over, by kind: what the runner checks against the job it gets. */
export type SignedJob =
  | { kind: "launch"; job: { room: string; handle: string; framework: string; cwd: string | null } }
  | {
      kind: "swarm";
      job: { room: string; task: string; framework: string; cwd: string | null; size: number; worktree: boolean };
    }
  | { kind: "restart"; job: { all: boolean; agents: { handle: string; room: string }[] } };

/**
 * A signature for `signed` on `runner`, when this browser is paired with it;
 * undefined otherwise, so the job asks on the machine as it always has.
 */
export async function signFor(
  runner: Pick<Runner, "id" | "pairings">,
  signed: SignedJob,
): Promise<DeviceSignature | undefined> {
  if (!runner.pairings?.length) return undefined;
  try {
    const key = await loadDeviceKey();
    if (!key || !pairingWith(runner, key.id)) return undefined;
    const nonce = hex(crypto.getRandomValues(new Uint8Array(8)));
    const body = JSON.stringify({
      v: 1,
      runner: runner.id,
      kind: signed.kind,
      ts: Date.now() / 1000,
      nonce,
      job: signed.job,
    });
    const sig = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      key.privateKey,
      new TextEncoder().encode(body),
    );
    return { key: key.id, body, sig: b64url(sig) };
  } catch {
    // A signature that can't be made leaves the job to ask on the machine.
    return undefined;
  }
}
