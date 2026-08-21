// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useCurrentUser } from "./current-user";

/**
 * Browser session state for the OIDC tier. Polls `/api/auth/session` (which
 * reads the backend's /health gate + our cookie), and — when signed in — syncs
 * the self-asserted "acting as" handle to the token's handle, so a gated hub
 * never sees a body handle that disagrees with the token (a 403 in waiting).
 *
 * When the gate is off this is inert: `authRequired` is false and the app
 * renders exactly as before.
 */
interface AuthSessionState {
  loading: boolean;
  authRequired: boolean;
  oidcConfigured: boolean;
  signedIn: boolean;
  handle: string | null;
}

interface AuthSession extends AuthSessionState {
  login: () => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthSession | null>(null);

const INITIAL: AuthSessionState = {
  loading: true,
  authRequired: false,
  oidcConfigured: false,
  signedIn: false,
  handle: null,
};

export function AuthSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthSessionState>(INITIAL);
  const { setPrincipal } = useCurrentUser();

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/auth/session", { cache: "no-store" });
      const d = (await res.json()) as Partial<AuthSessionState>;
      const next: AuthSessionState = {
        loading: false,
        authRequired: Boolean(d.authRequired),
        oidcConfigured: Boolean(d.oidcConfigured),
        signedIn: Boolean(d.signedIn),
        handle: d.handle ?? null,
      };
      setState(next);
      if (next.signedIn && next.handle) setPrincipal(next.handle);
    } catch {
      setState((s) => ({ ...s, loading: false }));
    }
  }, [setPrincipal]);

  useEffect(() => {
    // refresh() is an async fetch; setState is called only inside its .then()
    // callback, not synchronously in the effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  // A 401 from any API call (e.g. an access token that expired mid-session)
  // re-checks the session, so the gate re-engages instead of silently emptying.
  useEffect(() => {
    const onUnauthorized = () => refresh();
    window.addEventListener("mycelium:auth-required", onUnauthorized);
    return () => window.removeEventListener("mycelium:auth-required", onUnauthorized);
  }, [refresh]);

  const login = useCallback(() => {
    const returnTo = window.location.pathname + window.location.search;
    // Full-page navigation is required: the server sets auth cookies on the
    // callback URL, and router.push() would not trigger that round-trip.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/api/auth/login?return_to=${encodeURIComponent(returnTo)}`;
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setPrincipal("");
    // Full-page reload clears all React state after the session cookie is
    // cleared server-side — router.push("/") would leave stale state behind.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/";
  }, [setPrincipal]);

  return <Ctx.Provider value={{ ...state, login, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuthSession(): AuthSession {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuthSession must be used within an AuthSessionProvider");
  return ctx;
}
