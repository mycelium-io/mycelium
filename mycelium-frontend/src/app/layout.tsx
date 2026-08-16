// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { CurrentUserProvider } from "@/components/current-user";
import { AuthSessionProvider } from "@/components/auth-session";
import { LoginGate } from "@/components/login-gate";
import { KeymapProvider } from "@/components/keymap-provider";
import { NotificationsProvider } from "@/components/notifications-provider";

export const metadata: Metadata = {
  title: "mycelium",
  description: "Multi-agent coordination + persistent memory",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@1,600&family=IBM+Plex+Sans:wght@400;500;600&family=Geist+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-bg text-text antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          <CurrentUserProvider>
            <AuthSessionProvider>
              {/* Gate the whole app: when the backend requires auth and there's
                  no session, this renders the sign-in screen instead of the
                  shell (and its silently-empty room lists). Inert when the gate
                  is off. */}
              <LoginGate>
                <NotificationsProvider>
                  {/* Above the pages, not inside a page's shell: a page registers
                      its own bindings, so it has to sit under the provider. */}
                  <KeymapProvider>{children}</KeymapProvider>
                </NotificationsProvider>
              </LoginGate>
            </AuthSessionProvider>
          </CurrentUserProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
