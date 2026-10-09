// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Updating the app in place from the latest release.
//!
//! The release publishes `latest.json` beside the disk image, naming the
//! version and a signed archive of the app. The updater checks it, verifies
//! the archive against the public key built into this app (so only an update
//! we signed installs), replaces the app, and restarts it.
//!
//! The archive is a few hundred megabytes, so the download is said out loud:
//! a note when it starts, and its progress on the menu bar's update item until
//! the app restarts. Only one runs at a time.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::{Update, UpdaterExt};

/// Set while an update downloads, so a second check doesn't start another.
static UPDATING: AtomicBool = AtomicBool::new(false);

/// Look for an update. `asked`: the person chose "Check for Updates…", so
/// being up to date, or not being able to check, is said too; a check at
/// launch speaks only when there is something to install.
pub fn check(app: AppHandle, asked: bool) {
    if UPDATING.load(Ordering::SeqCst) {
        if asked {
            say(&app, "An update is already downloading. Mycelium restarts itself when it's ready.".into());
        }
        return;
    }
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
    if !yes || UPDATING.swap(true, Ordering::SeqCst) {
        return;
    }

    say(
        &app,
        format!(
            "Downloading Mycelium {}. It restarts itself when it's ready; the {} shows how far along it is.",
            update.version,
            crate::TRAY_ICON
        ),
    );
    crate::set_update_status(&app, Some("Downloading update…"));

    // Progress on the menu bar item, rewritten only when the percentage moves.
    let progress = app.clone();
    let mut received: u64 = 0;
    let mut shown: Option<u64> = None;
    let on_chunk = move |chunk: usize, total: Option<u64>| {
        received += chunk as u64;
        let Some(total) = total.filter(|t| *t > 0) else { return };
        let percent = (received * 100 / total).min(100);
        if shown != Some(percent) {
            shown = Some(percent);
            crate::set_update_status(&progress, Some(&format!("Downloading update… {percent}%")));
        }
    };
    let installing = app.clone();
    let on_done = move || crate::set_update_status(&installing, Some("Installing update…"));

    match update.download_and_install(on_chunk, on_done).await {
        Ok(()) => {
            crate::shut_down(&app);
            app.restart();
        }
        Err(e) => {
            UPDATING.store(false, Ordering::SeqCst);
            crate::set_update_status(&app, None);
            say(&app, format!("The update didn't install: {e}"));
        }
    }
}

fn say(app: &AppHandle, message: String) {
    let app = app.clone();
    std::thread::spawn(move || {
        app.dialog().message(message).title("Mycelium").blocking_show();
    });
}
