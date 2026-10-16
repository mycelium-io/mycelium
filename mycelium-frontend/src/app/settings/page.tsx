// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useRouter } from "next/navigation";
import { Suspense, useEffect } from "react";
import { AppShell } from "@/components/app-shell";
import { SettingsScreen } from "@/components/settings/settings-screen";
import { isSettingsPage, settingHref } from "@/lib/client-settings";

/** Settings opens on General; each page has its own address under it. A link
 *  written as `/settings#<page>` (or `#/<page>`) is sent on to that page. */
export default function SettingsPage() {
  const router = useRouter();
  useEffect(() => {
    const page = window.location.hash.replace(/^#\/?/, "");
    if (isSettingsPage(page)) router.replace(settingHref(page));
  }, [router]);
  return (
    <AppShell activeRoom={null} title="Settings">
      <Suspense>
        <SettingsScreen page="general" />
      </Suspense>
    </AppShell>
  );
}
