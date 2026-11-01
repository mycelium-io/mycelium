// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Updating the app in place from the latest release.
//!
//! The release publishes `latest.json` beside the disk image, naming the
//! version and a signed archive of the app. The updater plugin checks it. The
//! app downloads the archive itself (`download.rs`), verifies it against the
//! public key built into this app (`signature.rs`, so only an update we signed
//! installs), has the plugin replace the app, and restarts.
//!
//! The archive is a few hundred megabytes, so the download survives a dropped
//! connection: it goes into a partial file in the app's cache folder, each try
//! asks only for the bytes still missing, and a dropped connection is tried
//! again on its own, waiting a little longer each time, for as long as
//! [`GIVE_UP_AFTER`] passes without progress. A partial file outlives the app,
//! so quitting mid-download and updating again later carries on where it
//! stopped. Another version's partial file is deleted, and so is one that
//! fails the signature check.
//!
//! The download has a window of its own (`update.html`): the mark, the
//! version, and how far along it is, with the same progress on the menu bar's
//! update item. Only one runs at a time.
//!
//! While a newer version is known and not installed, the room UI says so. The
//! hub's page gets no IPC, so the app tells it: it sets `__myceliumUpdate` on
//! the page and fires a `mycelium:update` event, again on every page load. The
//! page's way back is the `mycelium://update` link, which is Check for
//! Updates…: the same question before anything downloads.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::{Update, UpdaterExt};

use crate::download::{self, Failed};
use crate::signature;
use crate::versions;

/// The waits between tries after a dropped connection, in seconds; the last
/// one repeats.
const BACKOFF_S: [u64; 5] = [2, 4, 8, 15, 30];
/// How long the download keeps trying without getting any further.
const GIVE_UP_AFTER: Duration = Duration::from_secs(10 * 60);

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
    /// Try again, from the update window after a download failed: the person
    /// already said yes, so it starts without asking.
    Retry,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    version: String,
    current: String,
    /// `downloading`, `retrying` (the connection dropped and it will try again
    /// on its own), `installing`, `restarting` or `failed`.
    phase: &'static str,
    received: u64,
    total: Option<u64>,
    error: Option<String>,
}

/// Look for an update.
pub fn check(app: AppHandle, how: Check) {
    let asked = matches!(how, Check::Asked | Check::Retry);
    if UPDATING.load(Ordering::SeqCst) {
        if asked {
            open_window(&app);
        }
        return;
    }
    tauri::async_runtime::spawn(async move {
        let found = find(&app).await;
        match found {
            Ok(Some(update)) => {
                remember(&app, Some(update.version.clone()));
                match how {
                    Check::Quiet => {}
                    Check::Retry => install(app, update).await,
                    Check::Asked | Check::Launch => offer(app, update).await,
                }
            }
            Ok(None) => {
                remember(&app, None);
                if asked {
                    say(&app, format!("You have the latest Mycelium ({}).", app.package_info().version));
                }
            }
            Err(e) if asked => say(&app, format!("Couldn't check for updates: {e}")),
            Err(_) => {}
        }
    });
}

/// A newer version on the chosen channel. Stable reads the app's own endpoint
/// (`releases/latest`); release candidates read the newest release's own
/// `latest.json`, RC or not, so a newer stable still wins.
async fn find(app: &AppHandle) -> Result<Option<Update>, String> {
    let updater = match versions::channel() {
        versions::Channel::Stable => app.updater().map_err(|e| e.to_string())?,
        versions::Channel::ReleaseCandidates => {
            // The newest release that published an update, stepping past one
            // whose build didn't finish (the feed lists those too).
            let mut newest = None;
            for release in versions::releases(true).await?.releases.into_iter().take(3) {
                if versions::has_manifest(&release.tag).await? {
                    newest = Some(release);
                    break;
                }
            }
            let Some(newest) = newest else {
                return Ok(None);
            };
            app.updater_builder()
                .endpoints(vec![versions::manifest(&newest.tag)?])
                .and_then(|b| b.build())
                .map_err(|e| e.to_string())?
        }
    };
    updater.check().await.map_err(|e| e.to_string())
}

/// Install the release tagged `tag`, older or newer, which the person chose in
/// Settings. The download is checked against the app's key like any update.
pub async fn switch(app: AppHandle, tag: &str) -> Result<(), String> {
    if UPDATING.load(Ordering::SeqCst) {
        open_window(&app);
        return Err("An update is already downloading.".into());
    }
    // A release listed from the feed may be one whose build didn't finish.
    if !versions::has_manifest(tag).await? {
        return Err(versions::no_update(tag));
    }
    let update = app
        .updater_builder()
        .endpoints(vec![versions::manifest(tag)?])
        // Any version but this one: going back is allowed here, as asked.
        .and_then(|b| b.version_comparator(|current, remote| remote.version != current).build())
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| format!("couldn't read that release: {e}"))?
        .ok_or("That's the version you have.")?;
    tauri::async_runtime::spawn(install(app, update));
    Ok(())
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
    if yes {
        install(app, update).await;
    }
}

/// Download `update` (carrying on from a partial file when there is one),
/// check its signature, install it and restart.
async fn install(app: AppHandle, update: Update) {
    if UPDATING.swap(true, Ordering::SeqCst) {
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

    let installed = match fetch(&app, &update, &mut state).await {
        Ok(bytes) => {
            state.phase = "installing";
            publish(&app, &state);
            crate::set_update_status(&app, Some("Installing update…"));
            update.install(bytes).map_err(|e| format!("it didn't install: {e}"))
        }
        Err(why) => Err(why),
    };
    match installed {
        Ok(()) => {
            state.phase = "restarting";
            publish(&app, &state);
            crate::shut_down(&app);
            app.restart();
        }
        Err(why) => {
            UPDATING.store(false, Ordering::SeqCst);
            crate::set_update_status(&app, None);
            state.phase = "failed";
            state.error = Some(capitalized(&why));
            publish(&app, &state);
            open_window(&app);
        }
    }
}

fn capitalized(text: &str) -> String {
    let mut chars = text.chars();
    chars.next().map_or_else(String::new, |c| c.to_uppercase().chain(chars).collect())
}

/// Where a version's partial download is kept, and the folder it's in.
fn partial(app: &AppHandle, version: &str) -> Result<(PathBuf, PathBuf), String> {
    let dir = app
        .path()
        .app_cache_dir()
        .map_err(|e| format!("couldn't find the app's cache folder: {e}"))?
        .join("updates");
    let file = dir.join(format!("Mycelium-{version}.part"));
    Ok((dir, file))
}

/// Delete every partial download in `dir` but `keep`: another version's is
/// of no use now.
fn forget_others(dir: &Path, keep: &Path) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        if entry.path() != keep {
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

/// The public key the app was built with, which every update must be signed by.
fn pubkey(app: &AppHandle) -> Option<String> {
    let updater = app.config().plugins.0.get("updater")?;
    updater.get("pubkey")?.as_str().map(str::to_string)
}

/// Download the update's archive, trying again after a dropped connection,
/// and return its bytes once the signature checks out.
async fn fetch(app: &AppHandle, update: &Update, state: &mut Progress) -> Result<Vec<u8>, String> {
    let (dir, path) = partial(app, &update.version)?;
    std::fs::create_dir_all(&dir).map_err(|e| format!("couldn't save the download: {e}"))?;
    forget_others(&dir, &path);
    let client = download::client(update.proxy.as_ref().map(|p| p.as_str()), update.no_proxy)?;
    let url = update.download_url.to_string();

    let mut tries = 0usize;
    let mut moved_at = Instant::now();
    loop {
        let before = download::held(&path);
        // Progress to the window and the menu bar item, sent only when the
        // percentage moves (or, with no size given, every megabyte).
        let window = app.clone();
        let mut sent = state.clone();
        sent.phase = "downloading";
        sent.error = None;
        let mut shown: Option<u64> = None;
        let mut on_progress = move |on_disk: u64, total: Option<u64>| {
            sent.received = on_disk;
            sent.total = total.filter(|t| *t > 0);
            let mark = match sent.total {
                Some(total) => (on_disk * 100 / total).min(100),
                None => on_disk >> 20,
            };
            if shown == Some(mark) {
                return;
            }
            shown = Some(mark);
            publish(&window, &sent);
            if sent.total.is_some() {
                crate::set_update_status(&window, Some(&format!("Downloading update… {mark}%")));
            }
        };
        match download::attempt(&client, &url, &update.headers, &path, &mut on_progress).await {
            Ok(()) => break,
            Err(Failed::Stop(why)) => return Err(why),
            Err(Failed::Retry(why)) => {
                if download::held(&path) > before {
                    tries = 0;
                    moved_at = Instant::now();
                }
                if moved_at.elapsed() >= GIVE_UP_AFTER {
                    return Err(format!(
                        "the download stopped and didn't get any further for {} minutes ({why})",
                        GIVE_UP_AFTER.as_secs() / 60
                    ));
                }
                state.phase = "retrying";
                state.error = Some(capitalized(&why));
                publish(app, state);
                crate::set_update_status(app, Some("Connection lost, retrying…"));
                let wait = BACKOFF_S[tries.min(BACKOFF_S.len() - 1)];
                tokio::time::sleep(Duration::from_secs(wait)).await;
                tries += 1;
            }
        }
    }

    let bytes = std::fs::read(&path).map_err(|e| format!("couldn't read the download: {e}"))?;
    let key = pubkey(app).ok_or("the app has no update key to check the download with")?;
    if let Err(why) = signature::verify(&bytes, &update.signature, &key, &update.version) {
        // A file that fails its check is no use to resume either.
        let _ = std::fs::remove_file(&path);
        return Err(why);
    }
    let _ = std::fs::remove_file(&path);
    Ok(bytes)
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
            .inner_size(380.0, 360.0)
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
