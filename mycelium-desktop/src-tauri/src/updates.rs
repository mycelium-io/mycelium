// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Updating the app in place from the latest release.
//!
//! The release publishes `latest.json` beside the disk image, naming the
//! version and a signed archive of the app. The updater checks it, verifies
//! the archive against the public key built into this app (so only an update
//! we signed installs), replaces the app, and restarts it.

use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::{Update, UpdaterExt};

/// Look for an update. `asked`: the person chose "Check for Updates…", so
/// being up to date, or not being able to check, is said too; a check at
/// launch speaks only when there is something to install.
pub fn check(app: AppHandle, asked: bool) {
    tauri::async_runtime::spawn(async move {
        let found = match app.updater() {
            Ok(updater) => updater.check().await,
            Err(e) => Err(e),
        };
        match found {
            Ok(Some(update)) => offer(app, update).await,
            Ok(None) if asked => say(
                &app,
                format!("You have the latest Mycelium ({}).", app.package_info().version),
            ),
            Err(e) if asked => say(&app, format!("Couldn't check for updates: {e}")),
            _ => {}
        }
    });
}

async fn offer(app: AppHandle, update: Update) {
    let ask = app.clone();
    let text = format!(
        "Mycelium {} is available. You have {}.\n\nIt restarts to finish; agents keep running in herdr.",
        update.version, update.current_version
    );
    // A dialog that waits for an answer must not block the async runtime.
    let yes = tauri::async_runtime::spawn_blocking(move || {
        ask.dialog()
            .message(text)
            .title("Update Mycelium")
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Update and Restart".into(),
                "Later".into(),
            ))
            .blocking_show()
    })
    .await
    .unwrap_or(false);
    if !yes {
        return;
    }
    match update.download_and_install(|_, _| {}, || {}).await {
        Ok(()) => {
            crate::shut_down(&app);
            app.restart();
        }
        Err(e) => say(&app, format!("The update didn't install: {e}")),
    }
}

fn say(app: &AppHandle, message: String) {
    let app = app.clone();
    std::thread::spawn(move || {
        app.dialog().message(message).title("Mycelium").blocking_show();
    });
}
