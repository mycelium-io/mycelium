// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useHasAppSettings } from "@/lib/desktop-app";
import { useAuthSession } from "./auth-session";
import { AppConnection } from "./settings/app-connection";

/**
 * Renders the app when the gate is off or the user is signed in; otherwise a
 * sign-in screen. A gated hub with no session shows an explicit "sign in" prompt,
 * not blank room lists.
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const { loading, authRequired, oidcConfigured, signInProblem, signedIn, login } = useAuthSession();

  // Don't flash the sign-in screen on first paint while /api/auth/session
  // resolves — for the common ungated hub it lands on "not required" instantly.
  if (loading) return null;
  if (!authRequired || signedIn) return <>{children}</>;

  return <SignInScreen oidcConfigured={oidcConfigured} problem={signInProblem} onLogin={login} />;
}

function SignInScreen({
  oidcConfigured,
  problem,
  onLogin,
}: {
  oidcConfigured: boolean;
  problem: string | null;
  onLogin: () => void;
}) {
  const authError = useAuthError();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface/40 p-8 text-center">
        <p className="font-serif text-3xl italic text-text">mycelium</p>
        <p className="mt-2 text-sm text-muted-foreground">
          This hub requires you to sign in.
        </p>

        {oidcConfigured ? (
          <Button size="lg" className="mt-6 w-full" onClick={onLogin}>
            Sign in with your identity provider
          </Button>
        ) : problem ? (
          <p className="mt-6 rounded-md border border-border bg-bg/60 p-3 text-left text-xs text-muted-foreground">
            {problem}
          </p>
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
      <OtherHub />
    </main>
  );
}

/**
 * In the desktop app, a way past a hub you can't sign in to: this screen
 * stands in for the whole app, Settings included, so the app's own Hub and
 * Connection is offered here (it asks only the app, never the hub).
 */
function OtherHub() {
  const inApp = useHasAppSettings();
  const [open, setOpen] = useState(false);
  if (!inApp) return null;
  return (
    <div className="mt-4 w-full max-w-xl text-left">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="mx-auto block text-micro text-muted-foreground hover:text-text"
      >
        Use a different hub, or this computer
      </button>
      {open && (
        <div className="mt-3">
          <AppConnection />
        </div>
      )}
    </div>
  );
}

/** Surface `?auth_error=…` from a failed callback, then strip it from the URL. */
function useAuthError(): string | null {
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const url = new URL(window.location.href);
    const e = url.searchParams.get("auth_error");
    if (e) {
      // The error is read and the parameter consumed in one step, so the
      // replaceState that clears it stays beside the state update.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setErr(e);
      url.searchParams.delete("auth_error");
      window.history.replaceState({}, "", url.toString());
    }
  }, []);
  return err;
}
