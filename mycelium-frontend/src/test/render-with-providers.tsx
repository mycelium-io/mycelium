// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { ReactElement } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { CurrentUserProvider } from "@/components/current-user";
import { NotificationSettingsProvider } from "@/components/notification-settings";

/** Wraps `ui` with the app's local-storage-backed context providers
 *  (acting-as identity, notification settings) that most page-level
 *  components assume are mounted above them. */
export function renderWithProviders(ui: ReactElement): RenderResult {
  return render(
    <CurrentUserProvider>
      <NotificationSettingsProvider>{ui}</NotificationSettingsProvider>
    </CurrentUserProvider>,
  );
}
