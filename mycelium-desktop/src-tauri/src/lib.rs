// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Mycelium for macOS: a thin shell over `mycelium desktop serve`.
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

use std::process::Command;
use std::sync::Mutex;

use serde::Serialize;
use serde_json::Value;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{
    AppHandle, Emitter, Manager, RunEvent, Url, Webview, WebviewUrl, WebviewWindowBuilder,
    WindowEvent, Wry,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as _};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};

use settings::{Mode, Settings};
use supervisor::Supervisor;
use terminal::Terminal;

#[derive(Default)]
struct Shell {
    /// Where the app's own pages are served from (a dev server, or the bundle).
    local_base: Mutex<Option<Url>>,
    tray: Mutex<Option<TrayItems>>,
    /// A pane the next terminal window should show.
    pending_pane: Mutex<Option<String>>,
}

struct TrayItems {
    hub: MenuItem<Wry>,
    slim: MenuItem<Wry>,
    runner: MenuItem<Wry>,
    autostart: CheckMenuItem<Wry>,
}

// ── pages ───────────────────────────────────────────────────────────────────

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
    let sup = app.state::<Supervisor>();
    let Some(path) = sup.take_ready(generation) else { return };
    let Some(ui) = status.get("ui_url").and_then(Value::as_str) else { return };
    let target = format!("{}{}", ui.trim_end_matches('/'), path.unwrap_or_default());
    if let Ok(url) = Url::parse(&target) {
        navigate_main(app, url);
    }
}

pub(crate) fn on_log(app: &AppHandle, line: &Value) {
    let _ = app.emit_to("main", "log", line.clone());
}

pub(crate) fn on_error(app: &AppHandle, error: &Value) {
    let _ = app.emit_to("main", "supervisor-error", error.clone());
}

// ── tray ────────────────────────────────────────────────────────────────────

fn tray_line(label: &str, state: &str) -> String {
    let (dot, said) = match state {
        "running" => ("●", "running"),
        "starting" => ("○", "starting"),
        "failed" => ("○", "failed"),
        "stopped" => ("○", "stopped"),
        "disabled" => ("○", "not on this Mac"),
        _ => ("○", "waiting"),
    };
    format!("{dot} {label}  {said}")
}

fn update_tray(app: &AppHandle, status: &Value) {
    let state = |name: &str| {
        status
            .pointer(&format!("/components/{name}/state"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    };
    let shell = app.state::<Shell>();
    let guard = shell.tray.lock().unwrap();
    let Some(items) = guard.as_ref() else { return };
    let _ = items.hub.set_text(tray_line("Hub", &state("hub")));
    let _ = items.slim.set_text(tray_line("SLIM", &state("slim")));
    let _ = items.runner.set_text(tray_line("Runner", &state("runner")));
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let hub = MenuItem::with_id(app, "status-hub", tray_line("Hub", ""), false, None::<&str>)?;
    let slim = MenuItem::with_id(app, "status-slim", tray_line("SLIM", ""), false, None::<&str>)?;
    let runner =
        MenuItem::with_id(app, "status-runner", tray_line("Runner", ""), false, None::<&str>)?;
    let open = MenuItem::with_id(app, "open", "Open Mycelium", true, None::<&str>)?;
    let agents = MenuItem::with_id(app, "terminal", "Agents terminal", true, None::<&str>)?;
    let at_login = app.autolaunch().is_enabled().unwrap_or(false);
    let autostart =
        CheckMenuItem::with_id(app, "autostart", "Start at login", true, at_login, None::<&str>)?;
    let health = MenuItem::with_id(app, "doctor", "Health check…", true, None::<&str>)?;
    let switch = MenuItem::with_id(app, "switch", "Settings…", true, None::<&str>)?;
    let updates = MenuItem::with_id(app, "updates", "Check for Updates…", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit Mycelium", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &hub,
            &slim,
            &runner,
            &PredefinedMenuItem::separator(app)?,
            &open,
            &agents,
            &autostart,
            &health,
            &switch,
            &updates,
            &PredefinedMenuItem::separator(app)?,
            &quit_item,
        ],
    )?;
    let mut tray = TrayIconBuilder::with_id("mycelium")
        .tooltip("Mycelium")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main(app),
            "terminal" => open_terminal_window(app, None),
            "switch" => show_local(app, "onboarding"),
            "doctor" => show_local(app, "doctor"),
            "updates" => updates::check(app.clone(), true),
            "autostart" => toggle_autostart(app),
            "quit" => quit(app),
            _ => {}
        });
    // A template image: one colour with transparency, which macOS tints to
    // match the menu bar (white on dark, black on light) like its own icons.
    let template = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-template.png"))?;
    tray = tray.icon(template).icon_as_template(true);
    tray.build(app)?;
    *app.state::<Shell>().tray.lock().unwrap() = Some(TrayItems { hub, slim, runner, autostart });
    Ok(())
}

fn toggle_autostart(app: &AppHandle) {
    let launcher = app.autolaunch();
    let enabled = launcher.is_enabled().unwrap_or(false);
    let _ = if enabled { launcher.disable() } else { launcher.enable() };
    let now = launcher.is_enabled().unwrap_or(!enabled);
    if let Some(items) = app.state::<Shell>().tray.lock().unwrap().as_ref() {
        let _ = items.autostart.set_checked(now);
    }
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

/// The macOS app menu, with Check for Updates… and Settings… (⌘,) where a
/// Mac app keeps them.
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
            Some(s) if s.mode == Mode::Hub => " This Mac will stop running its own hub.".to_string(),
            Some(s) => format!(" This Mac will leave {}.", s.hub_url.clone().unwrap_or_default()),
            None => String::new(),
        };
        let yes = app
            .dialog()
            .message(format!("Connect this Mac to the hub at {hub}?{leaving}"))
            .title("Join a hub")
            .buttons(MessageDialogButtons::OkCancelCustom("Join".into(), "Cancel".into()))
            .blocking_show();
        if !yes {
            return;
        }
        let roots = current.map(|s| s.roots).unwrap_or_default();
        let next = Settings { mode: Mode::Client, hub_url: Some(hub), roots };
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
        Command::new(bin)
            .args(["runner", "scan", "--json"])
            .env("PATH", paths::shell_path())
            .output()
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err("Couldn't scan this Mac for agent CLIs.".into());
    }
    serde_json::from_slice(&out.stdout).map_err(|_| "The scan returned something unreadable.".into())
}

/// `mycelium doctor --mode desktop`, as JSON: every check of what the app runs.
#[tauri::command]
async fn run_doctor(app: AppHandle, webview: Webview) -> Result<Value, String> {
    local_only(&app, &webview)?;
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = tauri::async_runtime::spawn_blocking(move || {
        Command::new(bin)
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

/// Open the supervisor's log (`~/.mycelium/logs/desktop.log`) in Console.
#[tauri::command]
fn open_log(app: AppHandle, webview: Webview) -> Result<(), String> {
    local_only(&app, &webview)?;
    let log = paths::home().join(".mycelium").join("logs").join("desktop.log");
    if !log.exists() {
        return Err("There's no log yet. It starts when Mycelium does.".into());
    }
    Command::new("open")
        .args(["-a", "Console"])
        .arg(&log)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
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

/// WKWebView's own user agent on macOS.
const WEBKIT_UA: &str =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)";

/// The main window. Its user agent ends in `MyceliumDesktop/<version>`, which
/// is how the room UI knows to offer links only the app can open (the
/// agents terminal, through `mycelium://terminal`).
fn main_window(app: &AppHandle) -> tauri::Result<tauri::WebviewWindow> {
    let ua = format!("{WEBKIT_UA} MyceliumDesktop/{}", app.package_info().version);
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Mycelium")
        .inner_size(1320.0, 860.0)
        .min_inner_size(720.0, 520.0)
        .background_color(tauri::webview::Color(12, 14, 17, 255))
        // A dark title bar, to match the app, whatever the system appearance.
        .theme(Some(tauri::Theme::Dark))
        .user_agent(&ua)
        .build()
}

pub fn run() {
    let app = tauri::Builder::default()
        // First, so a second launch (or a link opened while running) lands here.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| show_main(app)))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, None))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .menu(app_menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "settings" => show_local(app, "onboarding"),
            "updates" => updates::check(app.clone(), true),
            _ => {}
        })
        .manage(Shell::default())
        .manage(Supervisor::default())
        .manage(Terminal::default())
        .invoke_handler(tauri::generate_handler![
            get_state,
            scan_agents,
            pick_folder,
            run_doctor,
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
            let window = main_window(&handle)?;
            *app.state::<Shell>().local_base.lock().unwrap() = window.url().ok();
            build_tray(&handle)?;

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
