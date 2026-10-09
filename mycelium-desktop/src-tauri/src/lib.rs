// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Mycelium for macOS, Linux and Windows: a thin shell over `mycelium desktop serve`.
//!
//! The shell starts the supervisor, shows its progress on a local page, then
//! points the main window at the room UI it serves (or at the remote hub).
//! Around that: a tray with what is running, first-run choices, `mycelium://`
//! links, and a window with the agents' terminals. The hub's UI, once loaded,
//! gets no IPC: every command here refuses a page that isn't the app's own.

mod paths;
mod settings;
mod supervisor;
mod terminal;
mod updates;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::Serialize;
use serde_json::Value;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{
    AppHandle, Emitter, Manager, RunEvent, Url, Webview, WebviewUrl, WebviewWindowBuilder,
    WindowEvent, Wry,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as _};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use settings::{Mode, Settings};
use supervisor::Supervisor;
use terminal::Terminal;

/// What copy calls this machine, and the icon the app keeps there.
const MACHINE: &str = if cfg!(target_os = "macos") { "Mac" } else { "computer" };
pub(crate) const TRAY_ICON: &str = if cfg!(target_os = "macos") {
    "menu bar icon"
} else {
    "tray icon"
};

#[derive(Default)]
struct Shell {
    /// Where the app's own pages are served from (a dev server, or the bundle).
    local_base: Mutex<Option<Url>>,
    tray: Mutex<Option<TrayItems>>,
    /// A pane the next terminal window should show.
    pending_pane: Mutex<Option<String>>,
}

struct TrayItems {
    /// One line on whether Mycelium is working; opens the health check.
    status: MenuItem<Wry>,
    /// "Check for Updates…", which says how a download is going while one is.
    updates: MenuItem<Wry>,
    /// The tray menu itself, so the experiences folder can come and go.
    menu: Menu<Wry>,
    /// The experiences added on this Mac, one item each; in the menu only
    /// while there is at least one.
    experiences: Submenu<Wry>,
    experiences_shown: bool,
    /// Whether the status line last said running or joined.
    up: bool,
}

/// What the menu bar's update item says: `Some` while an update downloads
/// (and the item can't start another), `None` to put it back.
pub(crate) fn set_update_status(app: &AppHandle, status: Option<&str>) {
    if let Some(items) = app.state::<Shell>().tray.lock().unwrap().as_ref() {
        let _ = items.updates.set_text(status.unwrap_or("Check for Updates…"));
        let _ = items.updates.set_enabled(status.is_none());
    }
}

// ── pages ───────────────────────────────────────────────────────────────────

/// Where Tauri serves the app's own pages: the dev server, or the bundle.
/// Known from the platform rather than read off the window, whose URL isn't
/// settled when it is built (WebView2 navigates after `build()` returns).
fn app_base(app: &AppHandle) -> Option<Url> {
    if tauri::is_dev() {
        return app.config().build.dev_url.clone();
    }
    // Windows serves a custom protocol as http://<scheme>.localhost.
    let base = if cfg!(windows) { "http://tauri.localhost/" } else { "tauri://localhost/" };
    Url::parse(base).ok()
}

fn local_url(app: &AppHandle, page: &str) -> Option<Url> {
    let base = app.state::<Shell>().local_base.lock().unwrap().clone()?;
    base.join(page).ok()
}

/// Commands answer only the app's own pages, never a hub's page loaded in the window.
fn local_only(app: &AppHandle, webview: &Webview) -> Result<(), String> {
    let url = webview.url().map_err(|e| e.to_string())?;
    let base = app.state::<Shell>().local_base.lock().unwrap().clone();
    let ours = url.scheme() == "tauri" || base.is_some_and(|b| b.origin() == url.origin());
    if ours {
        Ok(())
    } else {
        Err("Not available to this page.".into())
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn navigate_main(app: &AppHandle, url: Url) {
    eprintln!("[mycelium] window: {url}");
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.navigate(url);
    }
    show_main(app);
}

/// A page of the room UI for this Mac, once the supervisor says where the UI is.
fn show_page(app: &AppHandle, path: &str) {
    let status = app.state::<Supervisor>().status();
    let Some(ui) = status.as_ref().and_then(|s| s.get("ui_url")).and_then(Value::as_str) else {
        show_main(app);
        return;
    };
    let Ok(mut url) = Url::parse(&format!("{}{path}", ui.trim_end_matches('/'))) else { return };
    if let Some(runner) = status.as_ref().and_then(|s| s.get("runner_id")).and_then(Value::as_str) {
        url.query_pairs_mut().append_pair("machine", runner);
    }
    navigate_main(app, url);
}

fn show_local(app: &AppHandle, view: &str) {
    if let Some(url) = local_url(app, &format!("index.html?view={view}")) {
        navigate_main(app, url);
    }
}

fn open_terminal_window(app: &AppHandle, pane: Option<String>) {
    if let Some(window) = app.get_webview_window("terminal") {
        let _ = window.show();
        let _ = window.set_focus();
        if let Some(pane) = pane {
            std::thread::spawn(move || terminal::focus_pane(&pane));
        }
        return;
    }
    *app.state::<Shell>().pending_pane.lock().unwrap() = pane;
    let built = WebviewWindowBuilder::new(app, "terminal", WebviewUrl::App("terminal.html".into()))
        .title("Agents")
        .inner_size(1100.0, 700.0)
        .min_inner_size(560.0, 320.0)
        .background_color(tauri::webview::Color(12, 14, 17, 255))
        // A dark title bar, to match the app, whatever the system appearance.
        .theme(Some(tauri::Theme::Dark))
        .build();
    if let Err(e) = built {
        eprintln!("[mycelium] could not open the agents terminal: {e}");
    }
}

// ── supervisor events ───────────────────────────────────────────────────────

pub(crate) fn on_status(app: &AppHandle, generation: u64, status: &Value) {
    let _ = app.emit_to("main", "status", status.clone());
    update_tray(app, status);
    if !supervisor::ready(status) {
        return;
    }
    ask_about_integrations(app);
    let sup = app.state::<Supervisor>();
    let Some(path) = sup.take_ready(generation) else { return };
    let Some(ui) = status.get("ui_url").and_then(Value::as_str) else { return };
    let target = format!("{}{}", ui.trim_end_matches('/'), path.unwrap_or_default());
    if let Ok(mut url) = Url::parse(&target) {
        // Tells the page which machine is this one, so it offers only this
        // Mac for starting agents and never lists anyone else's.
        if let Some(runner) = status.get("runner_id").and_then(Value::as_str) {
            let others: Vec<(String, String)> = url
                .query_pairs()
                .filter(|(k, _)| k != "machine")
                .map(|(k, v)| (k.into_owned(), v.into_owned()))
                .collect();
            url.query_pairs_mut().clear().extend_pairs(others).append_pair("machine", runner);
        }
        navigate_main(app, url);
    }
}

/// `mycelium machine integrations` with `args`: herdr's integrations for the
/// agent CLIs on this Mac, and the person's answer about them.
fn machine_integrations(args: &[&str]) -> Option<std::process::Output> {
    let bin = paths::resolve("mycelium")?;
    paths::command(bin)
        .args(["machine", "integrations"])
        .args(args)
        .env("PATH", paths::shell_path())
        .output()
        .ok()
}

/// Once a launch, when Mycelium is up: if nobody has answered yet and an agent
/// CLI here lacks herdr's integration, ask. With it, herdr brings agents back
/// in their own conversation after its server restarts; installing it edits
/// that CLI's settings, so it's only done on a yes. Either answer is kept, so
/// this asks once. First run asks in the wizard instead.
fn ask_about_integrations(app: &AppHandle) {
    static ASKED: AtomicBool = AtomicBool::new(false);
    if ASKED.swap(true, Ordering::SeqCst) {
        return;
    }
    let app = app.clone();
    std::thread::spawn(move || {
        let Some(out) = machine_integrations(&["--json"]) else { return };
        let Ok(state) = serde_json::from_slice::<Value>(&out.stdout) else { return };
        let missing: Vec<&str> = state
            .get("missing")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        if !state.get("answer").is_some_and(Value::is_null) || missing.is_empty() {
            return;
        }
        let install = app
            .dialog()
            .message(format!(
                "When herdr restarts, the agents running in it stop. With herdr's integration \
                 for {} installed, herdr brings each one back in its own conversation.\n\n\
                 Installing adds a hook to that agent program's own settings. You can change \
                 this later with `mycelium machine integrations`.",
                missing.join(", ")
            ))
            .title("Bring your agents back after herdr restarts?")
            .buttons(MessageDialogButtons::OkCancelCustom("Install".into(), "No thanks".into()))
            .blocking_show();
        let answer: &[&str] = if install { &["--install", "--yes"] } else { &["--decline"] };
        if !machine_integrations(answer).is_some_and(|o| o.status.success()) {
            eprintln!("[mycelium] couldn't save the answer about herdr's integrations");
        }
    });
}

/// The first run's answer about herdr's integrations: install them, or don't
/// and don't ask again.
#[tauri::command]
async fn herdr_integrations(app: AppHandle, webview: Webview, install: bool) -> Result<(), String> {
    local_only(&app, &webview)?;
    let args: &'static [&'static str] = if install { &["--install", "--yes"] } else { &["--decline"] };
    let out = tauri::async_runtime::spawn_blocking(move || machine_integrations(args))
        .await
        .map_err(|e| e.to_string())?
        .ok_or("The mycelium program isn't available.")?;
    if out.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&out.stdout).trim().to_string())
    }
}

/// A launch a hub asked this Mac's runner for, put to the person as a dialog.
///
/// The answer is a file in the runner's folder, which nothing that reaches
/// this Mac over the network can write, so only a yes given here starts it.
pub(crate) fn on_request(app: &AppHandle, event: &Value) {
    let request = event.get("request").cloned().unwrap_or_default();
    let id = request.get("id").and_then(Value::as_str).unwrap_or("").to_string();
    let Some(folder) = event.get("folder").and_then(Value::as_str) else { return };
    // The id becomes a file name: only the hex the hub makes.
    if id.is_empty() || !id.chars().all(|c| c.is_ascii_hexdigit()) {
        return;
    }
    let text = |key: &str| request.get(key).and_then(Value::as_str).unwrap_or("").to_string();
    let (title, message) = (text("title"), text("message"));
    let folder = std::path::PathBuf::from(folder);
    let app = app.clone();
    std::thread::spawn(move || {
        let yes = app
            .dialog()
            .message(message)
            .title(title)
            .kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::OkCancelCustom("Start".into(), "Decline".into()))
            .blocking_show();
        let answer = folder.join(format!("{id}.{}", if yes { "yes" } else { "no" }));
        if let Err(e) = std::fs::write(&answer, "") {
            eprintln!("[mycelium] couldn't answer {id}: {e}");
        }
    });
}

pub(crate) fn on_log(app: &AppHandle, line: &Value) {
    let _ = app.emit_to("main", "log", line.clone());
}

pub(crate) fn on_error(app: &AppHandle, error: &Value) {
    let _ = app.emit_to("main", "supervisor-error", error.clone());
}

// ── tray ────────────────────────────────────────────────────────────────────

/// The menu bar's one status line: running, starting, or something stopped.
/// Which part stopped, and why, is the health check's to say.
fn status_line(status: &Value) -> String {
    let state = |name: &str| {
        status
            .pointer(&format!("/components/{name}/state"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    };
    if status.get("mode").and_then(Value::as_str) == Some("client") {
        // Joined someone else's hub: the runner's connection is the whole story.
        let host = status
            .get("api_url")
            .and_then(Value::as_str)
            .and_then(|u| Url::parse(u).ok())
            .and_then(|u| u.host_str().map(str::to_string))
            .unwrap_or_else(|| "a hub".into());
        return if state("runner") == "running" {
            format!("● Joined {host}")
        } else {
            format!("○ Joining {host}…")
        };
    }
    let parts: Vec<String> = ["herdr", "slim", "hub", "ui", "runner"].iter().map(|p| state(p)).collect();
    // A hub the app didn't start, on its port: running, but not on its own.
    let other_hub = status.get("existing_hub").is_some_and(|h| !h.is_null());
    if parts.iter().any(|s| s == "failed" || s == "stopped") {
        "○ Something stopped: open Health check".into()
    } else if parts.iter().all(|s| s == "running" || s == "disabled") {
        if other_hub {
            "● Running on another hub: open Health check".into()
        } else {
            "● Mycelium is running".into()
        }
    } else {
        "○ Starting…".into()
    }
}

fn update_tray(app: &AppHandle, status: &Value) {
    let line = status_line(status);
    let up_now = {
        let shell = app.state::<Shell>();
        let mut guard = shell.tray.lock().unwrap();
        let Some(items) = guard.as_mut() else { return };
        let _ = items.status.set_text(&line);
        // Once it's running or joined, the experiences can be read: a team's
        // hub's only answer once the runner reaches it.
        let up = line.starts_with('●');
        let became = up && !items.up;
        items.up = up;
        became
    };
    if up_now {
        refresh_experiences(app.clone());
    }
}

/// Where the experiences folder goes: after Open Mycelium and Agents.
const EXPERIENCES_AT: usize = 4;

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    // Clickable, so a line that says something stopped leads to why.
    let status = MenuItem::with_id(app, "status", "○ Starting…", true, None::<&str>)?;
    let open = MenuItem::with_id(app, "open", "Open Mycelium", true, Some("CmdOrCtrl+O"))?;
    let agents = Submenu::with_id_and_items(
        app,
        "agents",
        "Agents",
        true,
        &[
            &MenuItem::with_id(app, "machines", "Your agents…", true, None::<&str>)?,
            &MenuItem::with_id(app, "terminal", "Agents terminal", true, None::<&str>)?,
        ],
    )?;
    let experiences = Submenu::with_id(app, "experiences", "Experiences", true)?;
    let switch = MenuItem::with_id(app, "switch", "Settings…", true, Some("CmdOrCtrl+,"))?;
    let health = MenuItem::with_id(app, "doctor", "Health check…", true, None::<&str>)?;
    let updates = MenuItem::with_id(app, "updates", "Check for Updates…", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit Mycelium", true, Some("CmdOrCtrl+Q"))?;
    let menu = Menu::with_items(
        app,
        &[
            &status,
            &PredefinedMenuItem::separator(app)?,
            &open,
            &agents,
            // The experiences folder goes here while one is added.
            &PredefinedMenuItem::separator(app)?,
            &switch,
            &health,
            &updates,
            &PredefinedMenuItem::separator(app)?,
            &quit_item,
        ],
    )?;
    let mut tray = TrayIconBuilder::with_id("mycelium")
        .tooltip("Mycelium")
        .menu(&menu)
        .show_menu_on_left_click(true);
    // A template image: one colour with transparency, which macOS tints to
    // match the menu bar (white on dark, black on light) like its own icons.
    // Other platforms don't tint, so they get the app's own icon.
    if cfg!(target_os = "macos") {
        let template = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-template.png"))?;
        tray = tray.icon(template).icon_as_template(true);
    } else {
        tray = tray.icon(tauri::image::Image::from_bytes(include_bytes!("../icons/32x32.png"))?);
    }
    tray.build(app)?;
    *app.state::<Shell>().tray.lock().unwrap() = Some(TrayItems {
        status,
        updates,
        menu,
        experiences,
        experiences_shown: false,
        up: false,
    });
    refresh_experiences(app.clone());
    Ok(())
}

/// The id prefix of an experience's menu item; the rest is where it opens.
const EXPERIENCE_ITEM: &str = "experience:";

/// Put the experiences added on this Mac in the menu bar, under Open Mycelium,
/// or take the folder away when there are none. Reads them in the background.
fn refresh_experiences(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        // Joined to a team's hub, the experiences are the hub's, read from it;
        // on this Mac, the ones added here.
        let list = match settings::load() {
            Some(s) if s.mode == Mode::Client => match hub_settings_cli(s.hub_url).await {
                Ok(v) => v.get("experiences").cloned().unwrap_or(Value::Null),
                Err(_) => return,
            },
            _ => match experiences_cli(vec![]).await {
                Ok(v) => v,
                Err(_) => return,
            },
        };
        let added: Vec<(String, String)> = list
            .as_array()
            .into_iter()
            .flatten()
            // The hub's list holds only what it has; this Mac's says which are added.
            .filter(|x| x.get("added").and_then(Value::as_bool) != Some(false))
            .filter_map(|x| {
                let title = x.get("title")?.as_str()?.to_string();
                let open = x.get("open")?.as_str()?.to_string();
                Some((title, open))
            })
            .collect();
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || {
            let shell = handle.state::<Shell>();
            let mut tray = shell.tray.lock().unwrap();
            let Some(items) = tray.as_mut() else { return };
            while let Ok(Some(old)) = items.experiences.remove_at(0) {
                drop(old);
            }
            for (title, open) in &added {
                if let Ok(item) =
                    MenuItem::with_id(&handle, format!("{EXPERIENCE_ITEM}{open}"), title, true, None::<&str>)
                {
                    let _ = items.experiences.append(&item);
                }
            }
            if added.is_empty() && items.experiences_shown {
                if items.menu.remove(&items.experiences).is_ok() {
                    items.experiences_shown = false;
                }
            } else if !added.is_empty()
                && !items.experiences_shown
                && items.menu.insert(&items.experiences, EXPERIENCES_AT).is_ok()
            {
                items.experiences_shown = true;
            }
        });
    });
}

/// Start at login on or off. Returns what it ended up as.
fn set_autostart_to(app: &AppHandle, on: bool) -> bool {
    let launcher = app.autolaunch();
    let _ = if on { launcher.enable() } else { launcher.disable() };
    launcher.is_enabled().unwrap_or(on)
}

/// Whether Mycelium starts at login, for Settings' This Mac section.
#[tauri::command]
fn get_autostart(app: AppHandle, webview: Webview) -> Result<bool, String> {
    local_only(&app, &webview)?;
    Ok(app.autolaunch().is_enabled().unwrap_or(false))
}

#[tauri::command]
fn set_autostart(app: AppHandle, webview: Webview, on: bool) -> Result<bool, String> {
    local_only(&app, &webview)?;
    Ok(set_autostart_to(&app, on))
}

/// Stop what the app runs (herdr and its agents carry on).
pub(crate) fn shut_down(app: &AppHandle) {
    app.state::<Supervisor>().stop();
    terminal::close(app);
}

fn quit(app: &AppHandle) {
    shut_down(app);
    app.exit(0);
}

/// Every menu item's click, the tray's and the app menu's. Tauri hands each
/// menu event to the app-wide handler whichever menu it came from, so this is
/// the only handler: a second one on the tray would run a shared item (Check
/// for Updates…) twice.
fn on_menu_event(app: &AppHandle, event: tauri::menu::MenuEvent) {
    match event.id().as_ref() {
        "open" => show_main(app),
        "terminal" => open_terminal_window(app, None),
        "machines" => show_page(app, "/machines"),
        "switch" | "settings" => show_local(app, "onboarding"),
        "status" | "doctor" => show_local(app, "doctor"),
        "updates" => updates::check(app.clone(), true),
        "quit" => quit(app),
        // An experience's item carries the path it opens on.
        id => {
            if let Some(path) = id.strip_prefix(EXPERIENCE_ITEM) {
                show_page(app, path);
            }
        }
    }
}

/// The macOS app menu, with Check for Updates… and Settings… (⌘,) where a
/// Mac app keeps them. Windows and Linux get no menu bar: the tray menu has
/// everything, and a native menu bar there is a bare strip over the app.
#[cfg(target_os = "macos")]
fn app_menu(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let menu = Menu::default(app)?;
    if let Some(first) = menu.items()?.into_iter().next() {
        if let Some(app_submenu) = first.as_submenu() {
            let updates =
                MenuItem::with_id(app, "updates", "Check for Updates…", true, None::<&str>)?;
            let settings = MenuItem::with_id(app, "settings", "Settings…", true, Some("CmdOrCtrl+,"))?;
            // After "About Mycelium" and its separator.
            app_submenu.insert(&updates, 2)?;
            app_submenu.insert(&settings, 3)?;
            app_submenu.insert(&PredefinedMenuItem::separator(app)?, 4)?;
        }
    }
    Ok(menu)
}

// ── links ───────────────────────────────────────────────────────────────────

fn same_hub(a: &str, b: &str) -> bool {
    a.trim_end_matches('/').eq_ignore_ascii_case(b.trim_end_matches('/'))
}

fn handle_link(app: &AppHandle, link: &Url) {
    if link.scheme() != "mycelium" {
        return;
    }
    let param = |name: &str| {
        link.query_pairs().find(|(k, _)| k == name).map(|(_, v)| v.to_string())
    };
    match link.host_str() {
        Some("terminal") => open_terminal_window(app, param("pane").filter(|p| !p.is_empty())),
        Some("settings") => show_local(app, "onboarding"),
        Some("join") => {
            let Some(hub) = param("hub") else { return };
            let path = param("room").filter(|r| !r.is_empty()).map(|room| {
                format!("/room/{}", url::form_urlencoded::byte_serialize(room.as_bytes()).collect::<String>())
            });
            join(app.clone(), hub, path);
        }
        _ => {}
    }
}

fn join(app: AppHandle, hub: String, path: Option<String>) {
    let current = settings::load();
    let already = current
        .as_ref()
        .is_some_and(|s| s.mode == Mode::Client && s.hub_url.as_deref().is_some_and(|h| same_hub(h, &hub)));
    if already {
        let sup = app.state::<Supervisor>();
        let ui = sup
            .status()
            .and_then(|s| s.get("ui_url").and_then(Value::as_str).map(String::from))
            .unwrap_or_else(|| hub.clone());
        let target = format!("{}{}", ui.trim_end_matches('/'), path.unwrap_or_default());
        if let Ok(url) = Url::parse(&target) {
            navigate_main(&app, url);
        }
        return;
    }
    // A dialog that waits for an answer must not block the main thread.
    std::thread::spawn(move || {
        let leaving = match &current {
            Some(s) if s.mode == Mode::Hub => format!(" This {MACHINE} will stop running its own hub."),
            Some(s) => format!(" This {MACHINE} will leave {}.", s.hub_url.clone().unwrap_or_default()),
            None => String::new(),
        };
        let yes = app
            .dialog()
            .message(format!("Connect this {MACHINE} to the hub at {hub}?{leaving}"))
            .title("Join a hub")
            .buttons(MessageDialogButtons::OkCancelCustom("Join".into(), "Cancel".into()))
            .blocking_show();
        if !yes {
            return;
        }
        let roots = current.map(|s| s.roots).unwrap_or_default();
        let next = Settings { mode: Mode::Client, hub_url: Some(hub), roots, share_usage: false };
        match next.validate() {
            Ok(next) => {
                if settings::save(&next).is_ok() {
                    paths::link_bundled();
                    app.state::<Supervisor>().set_pending_path(path);
                    show_local(&app, "loading");
                    supervisor::restart(&app, next);
                }
            }
            Err(message) => {
                app.dialog().message(message).title("Join a hub").blocking_show();
            }
        }
    });
}

// ── commands (the app's own pages only) ─────────────────────────────────────

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Snapshot {
    settings: Option<Settings>,
    status: Option<Value>,
    last_error: Option<String>,
    mycelium: paths::Found,
    herdr: paths::Found,
    home: String,
}

#[tauri::command]
fn get_state(app: AppHandle, webview: Webview) -> Result<Snapshot, String> {
    local_only(&app, &webview)?;
    let sup = app.state::<Supervisor>();
    Ok(Snapshot {
        settings: settings::load(),
        status: sup.status(),
        last_error: sup.last_error(),
        mycelium: paths::found("mycelium"),
        herdr: paths::found("herdr"),
        home: paths::home().to_string_lossy().to_string(),
    })
}

/// What `mycelium runner scan --json` finds: the agent CLIs here, and herdr.
#[tauri::command]
async fn scan_agents(app: AppHandle, webview: Webview) -> Result<Value, String> {
    local_only(&app, &webview)?;
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = tauri::async_runtime::spawn_blocking(move || {
        paths::command(bin)
            .args(["runner", "scan", "--json"])
            .env("PATH", paths::shell_path())
            .output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(format!("Couldn't scan this {MACHINE} for agent CLIs."));
    }
    serde_json::from_slice(&out.stdout).map_err(|_| "The scan returned something unreadable.".into())
}

/// `mycelium doctor --mode desktop`, as JSON: every check of what the app runs.
#[tauri::command]
async fn run_doctor(app: AppHandle, webview: Webview) -> Result<Value, String> {
    local_only(&app, &webview)?;
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = tauri::async_runtime::spawn_blocking(move || {
        paths::command(bin)
            .args(["--json", "doctor", "--mode", "desktop"])
            .env("PATH", paths::shell_path())
            .output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    serde_json::from_slice(&out.stdout).map_err(|_| {
        let err = String::from_utf8_lossy(&out.stderr);
        format!("The health check didn't finish. {}", err.lines().last().unwrap_or_default())
    })
}

/// `mycelium desktop model`: the model the hub's own agents use. The key is
/// never in the answer, only whether one is saved and its last four characters.
#[tauri::command]
async fn get_model(app: AppHandle, webview: Webview) -> Result<Value, String> {
    local_only(&app, &webview)?;
    model_cli(None).await
}

/// `mycelium desktop model --set`, with the new settings on its stdin: a key
/// passed as an argument would show in the process list. A field left out
/// keeps its saved value.
#[tauri::command]
async fn save_model(app: AppHandle, webview: Webview, model: Value) -> Result<Value, String> {
    local_only(&app, &webview)?;
    if !model.is_object() {
        return Err("The model settings must be an object.".into());
    }
    model_cli(Some(model.to_string())).await
}

async fn model_cli(input: Option<String>) -> Result<Value, String> {
    use std::io::Write as _;
    use std::process::Stdio;

    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = tauri::async_runtime::spawn_blocking(move || {
        let mut cmd = paths::command(bin);
        cmd.args(["desktop", "model"])
            .env("PATH", paths::shell_path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if input.is_some() {
            cmd.arg("--set");
        }
        let mut child = cmd.spawn()?;
        if let (Some(text), Some(mut stdin)) = (input, child.stdin.take()) {
            stdin.write_all(text.as_bytes())?;
        }
        child.wait_with_output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(err.lines().last().unwrap_or("Couldn't save the model settings.").trim().to_string());
    }
    serde_json::from_slice(&out.stdout).map_err(|_| "The model settings came back unreadable.".into())
}

/// `mycelium desktop experiences`: the ready-made rooms this Mac has, and the
/// ones it could add.
#[tauri::command]
async fn get_experiences(app: AppHandle, webview: Webview) -> Result<Value, String> {
    local_only(&app, &webview)?;
    experiences_cli(vec![]).await
}

/// Add an experience's content from a file the person picks: the macOS file
/// picker, then `mycelium desktop experiences --add`. `None` when they cancel.
#[tauri::command]
async fn add_experience(app: AppHandle, webview: Webview, id: String) -> Result<Option<Value>, String> {
    local_only(&app, &webview)?;
    let dialog = app
        .dialog()
        .file()
        .set_title("Add an experience")
        .add_filter("Experience", &["zip"]);
    let picked = tauri::async_runtime::spawn_blocking(move || dialog.blocking_pick_file())
        .await
        .map_err(|e| e.to_string())?;
    let Some(path) = picked.and_then(|p| p.into_path().ok()) else {
        return Ok(None);
    };
    let path = path.to_string_lossy().to_string();
    let list = experiences_cli(vec!["--add".into(), id, path]).await?;
    refresh_experiences(app);
    Ok(Some(list))
}

/// `mycelium desktop experiences --remove`. Rooms it made stay.
#[tauri::command]
async fn remove_experience(app: AppHandle, webview: Webview, id: String) -> Result<Value, String> {
    local_only(&app, &webview)?;
    let list = experiences_cli(vec!["--remove".into(), id]).await?;
    refresh_experiences(app);
    Ok(list)
}

async fn experiences_cli(args: Vec<String>) -> Result<Value, String> {
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = tauri::async_runtime::spawn_blocking(move || {
        paths::command(bin)
            .args(["desktop", "experiences"])
            .args(&args)
            .env("PATH", paths::shell_path())
            .env("NO_COLOR", "1")
            .output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(err.lines().last().unwrap_or("Couldn't change the experiences.").trim().to_string());
    }
    serde_json::from_slice(&out.stdout).map_err(|_| "The experiences came back unreadable.".into())
}

/// What the hub is set up with, read-only: `mycelium hub settings --json`
/// against the team's hub (or this Mac's). No key is ever in the answer.
#[tauri::command]
async fn get_hub_settings(app: AppHandle, webview: Webview) -> Result<Value, String> {
    local_only(&app, &webview)?;
    let hub = settings::load().filter(|s| s.mode == Mode::Client).and_then(|s| s.hub_url);
    hub_settings_cli(hub).await
}

async fn hub_settings_cli(hub: Option<String>) -> Result<Value, String> {
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = tauri::async_runtime::spawn_blocking(move || {
        let mut cmd = paths::command(bin);
        cmd.args(["hub", "settings", "--json"])
            .env("PATH", paths::shell_path())
            .env("NO_COLOR", "1");
        if let Some(hub) = hub {
            cmd.args(["--hub", &hub]);
        }
        cmd.output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(err.lines().last().unwrap_or("Couldn't ask the hub.").trim().to_string());
    }
    serde_json::from_slice(&out.stdout).map_err(|_| "The hub's answer was unreadable.".into())
}

/// Open an experience: the room UI, at the path the experience opens on.
#[tauri::command]
fn open_experience(app: AppHandle, webview: Webview, path: String) -> Result<(), String> {
    local_only(&app, &webview)?;
    if !path.starts_with('/') || path.starts_with("//") {
        return Err("An experience opens on a path in the room UI.".into());
    }
    let status = app.state::<Supervisor>().status().ok_or("Mycelium is still starting.")?;
    let ui = status.get("ui_url").and_then(Value::as_str).ok_or("Mycelium is still starting.")?;
    let url = Url::parse(ui).and_then(|u| u.join(&path)).map_err(|e| e.to_string())?;
    navigate_main(&app, url);
    Ok(())
}

/// Open the supervisor's log (`~/.mycelium/logs/desktop.log`): in Console on
/// a Mac, elsewhere in whatever opens text files.
#[tauri::command]
fn open_log(app: AppHandle, webview: Webview) -> Result<(), String> {
    local_only(&app, &webview)?;
    let log = paths::home().join(".mycelium").join("logs").join("desktop.log");
    if !log.exists() {
        return Err("There's no log yet. It starts when Mycelium does.".into());
    }
    #[cfg(target_os = "macos")]
    let opened = paths::command("open").args(["-a", "Console"]).arg(&log).spawn().map(|_| ());
    #[cfg(not(target_os = "macos"))]
    let opened = paths::open(log.as_os_str());
    opened.map_err(|e| e.to_string())
}

/// Back to the room UI from one of the app's own pages, once it is up.
#[tauri::command]
fn open_room(app: AppHandle, webview: Webview) -> Result<(), String> {
    local_only(&app, &webview)?;
    let status = app.state::<Supervisor>().status().ok_or("Mycelium is still starting.")?;
    let ui = status.get("ui_url").and_then(Value::as_str).ok_or("Mycelium is still starting.")?;
    let url = Url::parse(ui).map_err(|e| e.to_string())?;
    navigate_main(&app, url);
    Ok(())
}

/// The macOS folder picker, opened at `start`. `None` when the person cancels.
#[tauri::command]
async fn pick_folder(
    app: AppHandle,
    webview: Webview,
    start: Option<String>,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    local_only(&app, &webview)?;
    let mut dialog = app
        .dialog()
        .file()
        .set_title("Folder agents may start in")
        .set_can_create_directories(true);
    if let Some(start) = start.filter(|s| !s.is_empty()) {
        dialog = dialog.set_directory(start);
    }
    let picked = tauri::async_runtime::spawn_blocking(move || dialog.blocking_pick_folder())
        .await
        .map_err(|e| e.to_string())?;
    Ok(picked
        .and_then(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().to_string()))
}

/// Save the first-run choice and start. Returns what happened to PATH.
#[tauri::command]
fn start(app: AppHandle, webview: Webview, settings: Settings) -> Result<paths::PathSetup, String> {
    local_only(&app, &webview)?;
    let settings = settings.validate()?;
    settings::save(&settings)?;
    let setup = paths::link_bundled();
    app.state::<Supervisor>().set_pending_path(None);
    supervisor::restart(&app, settings);
    Ok(setup)
}

#[tauri::command]
fn terminal_open(
    app: AppHandle,
    webview: Webview,
    pane: Option<String>,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    local_only(&app, &webview)?;
    let pending = app.state::<Shell>().pending_pane.lock().unwrap().take();
    terminal::open(&app, pane.or(pending), cols, rows)
}

#[tauri::command]
fn terminal_write(app: AppHandle, webview: Webview, data: String) -> Result<(), String> {
    local_only(&app, &webview)?;
    terminal::write(&app, &data)
}

#[tauri::command]
fn terminal_resize(app: AppHandle, webview: Webview, cols: u16, rows: u16) -> Result<(), String> {
    local_only(&app, &webview)?;
    terminal::resize(&app, cols, rows)
}

#[tauri::command]
fn terminal_close(app: AppHandle, webview: Webview) -> Result<(), String> {
    local_only(&app, &webview)?;
    terminal::close(&app);
    Ok(())
}

// ── the app ─────────────────────────────────────────────────────────────────

/// The webview's own user agent on this platform, which the pages read to
/// name the machine and its keys.
#[cfg(target_os = "macos")]
const WEBVIEW_UA: &str =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)";
#[cfg(windows)]
const WEBVIEW_UA: &str =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)";
#[cfg(target_os = "linux")]
const WEBVIEW_UA: &str =
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko)";

/// The main window. Its user agent ends in `MyceliumDesktop/<version>`, which
/// is how the room UI knows to offer links only the app can open (the
/// agents terminal, through `mycelium://terminal`).
fn main_window(app: &AppHandle) -> tauri::Result<tauri::WebviewWindow> {
    let ua = format!("{WEBVIEW_UA} MyceliumDesktop/{}", app.package_info().version);
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Mycelium")
        .inner_size(1320.0, 860.0)
        .min_inner_size(720.0, 520.0)
        .background_color(tauri::webview::Color(12, 14, 17, 255))
        // A dark title bar, to match the app, whatever the system appearance.
        .theme(Some(tauri::Theme::Dark))
        .user_agent(&ua)
        // Tauri's own drop handler (for files dropped from Finder) takes every
        // drag in the window, so the page's HTML5 drag and drop (board cards,
        // room folders, panels) never sees a drop. The UI listens for none of
        // Tauri's drop events, so the page gets them all.
        .disable_drag_drop_handler()
        // A link the UI opens in a new tab (one out of the app, from chat or a
        // memory) goes to the default browser: the app never opens a second
        // web window of its own, and only web and mail links are passed on.
        .on_new_window(|url, _features| {
            if matches!(url.scheme(), "http" | "https" | "mailto") {
                let _ = paths::open(url.as_str().as_ref());
            }
            tauri::webview::NewWindowResponse::Deny
        })
        .build()
}

pub fn run() {
    // WebKitGTK's DMA-BUF renderer draws a blank window on some GPUs (NVIDIA's
    // driver among them) and in VMs; the person can still turn it back on.
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
    let builder = tauri::Builder::default()
        // First, so a second launch (or a link opened while running) lands here.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| show_main(app)))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, None))
        .plugin(tauri_plugin_updater::Builder::new().build());
    #[cfg(target_os = "macos")]
    let builder = builder.menu(app_menu);
    let app = builder
        // The tray's items, and on a Mac the menu bar's.
        .on_menu_event(on_menu_event)
        .manage(Shell::default())
        .manage(Supervisor::default())
        .manage(Terminal::default())
        .invoke_handler(tauri::generate_handler![
            get_state,
            scan_agents,
            pick_folder,
            run_doctor,
            herdr_integrations,
            get_model,
            save_model,
            get_experiences,
            get_hub_settings,
            add_experience,
            remove_experience,
            open_experience,
            get_autostart,
            set_autostart,
            open_room,
            open_log,
            start,
            terminal_open,
            terminal_write,
            terminal_resize,
            terminal_close
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            #[cfg(windows)]
            paths::clear_moved_aside();
            *app.state::<Shell>().local_base.lock().unwrap() = app_base(&handle);
            main_window(&handle)?;
            build_tray(&handle)?;

            // macOS and the Windows installer register mycelium:// links with
            // the system; an AppImage has no installer, so it registers itself.
            #[cfg(target_os = "linux")]
            if let Err(e) = app.deep_link().register_all() {
                eprintln!("[mycelium] could not register mycelium:// links: {e}");
            }
            let links = handle.clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    handle_link(&links, &url);
                }
            });
            if let Ok(Some(urls)) = app.deep_link().get_current() {
                for url in urls {
                    handle_link(&handle, &url);
                }
            }

            if let Some(saved) = settings::load().and_then(|s| s.validate().ok()) {
                paths::link_bundled();
                supervisor::restart(&handle, saved);
            }
            // A quiet look for an update once the app has settled; it speaks
            // only if there is one. Not in development, where every release is newer.
            if !cfg!(debug_assertions) {
                let later = handle.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(10));
                    updates::check(later, false);
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| match (window.label(), event) {
            // Closing the main window hides it; the tray keeps the app and its agents.
            ("main", WindowEvent::CloseRequested { api, .. }) => {
                api.prevent_close();
                let _ = window.hide();
            }
            ("terminal", WindowEvent::Destroyed) => terminal::close(window.app_handle()),
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building Mycelium");

    app.run(|app, event| match event {
        RunEvent::ExitRequested { api, code, .. } if code.is_none() => api.prevent_exit(),
        RunEvent::Exit => {
            app.state::<Supervisor>().stop();
            terminal::close(app);
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_main(app),
        _ => {}
    });
}
