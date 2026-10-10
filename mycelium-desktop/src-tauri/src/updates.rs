// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Updating the app in place from the latest release.
//!
//! The release publishes `latest.json` beside the disk image, naming the
//! version and a signed archive of the app. The updater checks it, verifies
//! the archive against the public key built into this app (so only an update
//! we signed installs), replaces the app, and restarts it.
//!
//! The archive is a few hundred megabytes, so the download has a window of its
//! own (`update.html`): the mark, the version, and how far along it is, with
//! the same progress on the menu bar's update item. Only one runs at a time.
//!
//! While a newer version is known and not installed, the room UI says so. The
//! hub's page gets no IPC, so the app tells it: it sets `__myceliumUpdate` on
//! the page and fires a `mycelium:update` event, again on every page load. The
//! page's way back is the `mycelium://update` link, which is Check for
//! Updates…: the same question before anything downloads.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::{Update, UpdaterExt};

/// Set while an update downloads, so a second check doesn't start another.
static UPDATING: AtomicBool = AtomicBool::new(false);

/// A newer version the last check found, until it is installed.
static AVAILABLE: Mutex<Option<String>> = Mutex::new(None);

/// How the download is going, for the update window.
static PROGRESS: Mutex<Option<Progress>> = Mutex::new(None);

/// Who asked for a check, which decides what it says.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Check {
    /// The person chose Check for Updates… (or the room UI's update link):
    /// being up to date, or not being able to check, is said too.
    Asked,
    /// The look at launch: it asks only when there is something to install.
    Launch,
    /// A look while the app runs: it asks nothing, and the room UI says
    /// an update is available.
    Quiet,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    version: String,
    current: String,
    /// `downloading`, `installing`, `restarting` or `failed`.
    phase: &'static str,
    received: u64,
    total: Option<u64>,
    error: Option<String>,
}

/// Look for an update.
pub fn check(app: AppHandle, how: Check) {
    if UPDATING.load(Ordering::SeqCst) {
        if how == Check::Asked {
            open_window(&app);
        }
        return;
    }
    tauri::async_runtime::spawn(async move {
        let found = match app.updater() {
            Ok(updater) => updater.check().await,
            Err(e) => Err(e),
        };
        match found {
            Ok(Some(update)) => {
                remember(&app, Some(update.version.clone()));
                if how != Check::Quiet {
                    offer(app, update).await;
                }
            }
            Ok(None) => {
                remember(&app, None);
                if how == Check::Asked {
                    say(&app, format!("You have the latest Mycelium ({}).", app.package_info().version));
                }
            }
            Err(e) if how == Check::Asked => say(&app, format!("Couldn't check for updates: {e}")),
            Err(_) => {}
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

    let mut state = Progress {
        version: update.version.clone(),
        current: update.current_version.clone(),
        phase: "downloading",
        received: 0,
        total: None,
        error: None,
    };
    publish(&app, &state);
    open_window(&app);
    crate::set_update_status(&app, Some("Downloading update…"));

    // Progress to the window and the menu bar item, sent only when the
    // percentage moves (or, with no size given, every megabyte).
    let progress = app.clone();
    let mut sent = state.clone();
    let mut shown: Option<u64> = None;
    let on_chunk = move |chunk: usize, total: Option<u64>| {
        sent.received += chunk as u64;
        sent.total = total.filter(|t| *t > 0);
        let mark = match sent.total {
            Some(total) => (sent.received * 100 / total).min(100),
            None => sent.received >> 20,
        };
        if shown == Some(mark) {
            return;
        }
        shown = Some(mark);
        publish(&progress, &sent);
        if sent.total.is_some() {
            crate::set_update_status(&progress, Some(&format!("Downloading update… {mark}%")));
        }
    };
    let installing = app.clone();
    let mut done = state.clone();
    let on_done = move || {
        done.phase = "installing";
        publish(&installing, &done);
        crate::set_update_status(&installing, Some("Installing update…"));
    };

    match update.download_and_install(on_chunk, on_done).await {
        Ok(()) => {
            state.phase = "restarting";
            publish(&app, &state);
            crate::shut_down(&app);
            app.restart();
        }
        Err(e) => {
            UPDATING.store(false, Ordering::SeqCst);
            crate::set_update_status(&app, None);
            state.phase = "failed";
            state.error = Some(e.to_string());
            publish(&app, &state);
            open_window(&app);
        }
    }
}

/// Keep how the download is going, and send it to the update window. A phase
/// change keeps the last byte count, which only the download's own updates carry.
fn publish(app: &AppHandle, state: &Progress) {
    let mut kept = PROGRESS.lock().unwrap();
    let mut next = state.clone();
    if let Some(last) = kept.as_ref().filter(|_| next.phase != "downloading") {
        next.received = last.received;
        next.total = last.total;
    }
    *kept = Some(next.clone());
    drop(kept);
    let _ = app.emit_to("update", "update-progress", next);
}

/// The update window's first read: how the download is going, if one is.
pub fn progress() -> Option<Progress> {
    PROGRESS.lock().unwrap().clone()
}

/// The download's own small window, or the one already open.
fn open_window(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window("update") {
            let _ = window.show();
            let _ = window.set_focus();
            return;
        }
        let built = WebviewWindowBuilder::new(&handle, "update", WebviewUrl::App("update.html".into()))
            .title("Updating Mycelium")
            .inner_size(380.0, 320.0)
            .resizable(false)
            .maximizable(false)
            .minimizable(false)
            .center()
            .background_color(tauri::webview::Color(12, 14, 17, 255))
            // A dark title bar, to match the app, whatever the system appearance.
            .theme(Some(tauri::Theme::Dark))
            .build();
        if let Err(e) = built {
            eprintln!("[mycelium] could not open the update window: {e}");
        }
    });
}

/// Keep the version a check found (or that there is none), and tell the room UI.
fn remember(app: &AppHandle, version: Option<String>) {
    *AVAILABLE.lock().unwrap() = version;
    if let Some(window) = app.get_webview_window("main") {
        announce(&window);
    }
}

/// Tell the page in `window` whether an update is available. Called again on
/// every page load, since a load starts the page over.
pub fn announce(window: &WebviewWindow) {
    let version = AVAILABLE.lock().unwrap().clone();
    let detail = serde_json::json!(version.map(|v| serde_json::json!({ "version": v })));
    let _ = window.eval(format!(
        "window.__myceliumUpdate = {detail}; \
         window.dispatchEvent(new CustomEvent('mycelium:update', {{ detail: window.__myceliumUpdate }}));"
    ));
}

fn say(app: &AppHandle, message: String) {
    let app = app.clone();
    std::thread::spawn(move || {
        app.dialog().message(message).title("Mycelium").blocking_show();
    });
}
