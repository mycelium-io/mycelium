// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useAuthSession } from "./auth-session";

/**
 * Renders the app when the gate is off or the user is signed in; otherwise a
 * sign-in screen. A gated hub with no session shows an explicit "sign in" prompt,
 * not blank room lists.
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const { loading, authRequired, oidcConfigured, signedIn, login } = useAuthSession();

  // Don't flash the sign-in screen on first paint while /api/auth/session
  // resolves — for the common ungated hub it lands on "not required" instantly.
  if (loading) return null;
  if (!authRequired || signedIn) return <>{children}</>;

  return <SignInScreen oidcConfigured={oidcConfigured} onLogin={login} />;
}

function SignInScreen({ oidcConfigured, onLogin }: { oidcConfigured: boolean; onLogin: () => void }) {
  const authError = useAuthError();

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface/40 p-8 text-center">
        <p className="font-serif text-3xl italic text-text">mycelium</p>
        <p className="mt-2 text-sm text-muted-foreground">
          This hub requires you to sign in.
        </p>

        {oidcConfigured ? (
          <Button size="lg" className="mt-6 w-full" onClick={onLogin}>
            Sign in with your identity provider
          </Button>
        ) : (
          <p className="mt-6 rounded-md border border-border bg-bg/60 p-3 text-left text-xs text-muted-foreground">
            The backend gate is on, but browser login isn&apos;t configured on this
            server. Set <code className="text-accent">MYCELIUM_OIDC_ISSUER</code> and{" "}
            <code className="text-accent">AUTH_SESSION_SECRET</code>, then reload.
          </p>
        )}

        {authError && (
          <p className="mt-4 text-left text-xs text-red">Sign-in failed: {authError}</p>
        )}
      </div>
    </main>
  );
}

/** Surface `?auth_error=…` from a failed callback, then strip it from the URL. */
function useAuthError(): string | null {
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const url = new URL(window.location.href);
    const e = url.searchParams.get("auth_error");
    if (e) {
      setErr(e);
      url.searchParams.delete("auth_error");
      window.history.replaceState({}, "", url.toString());
    }
  }, []);
  return err;
}
