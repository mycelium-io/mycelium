// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { notFound, useParams } from "next/navigation";
import { Suspense } from "react";
import { AppShell } from "@/components/app-shell";
import { SettingsScreen } from "@/components/settings/settings-screen";
import { isSettingsPage } from "@/lib/client-settings";

/** One settings page, at `/settings/<page>`. */
export default function SettingsSubPage() {
  const params = useParams<{ page: string }>();
  if (!isSettingsPage(params.page)) notFound();
  return (
    <AppShell activeRoom={null} title="Settings">
      <Suspense>
        <SettingsScreen page={params.page} />
      </Suspense>
    </AppShell>
  );
}
