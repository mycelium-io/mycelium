// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! The one process the app starts: `mycelium desktop serve`.
//!
//! It runs everything else (the SLIM node, the hub, the UI, the runner) and
//! says what state each is in, one JSON object per line on stdout. The app
//! only reads that, restarts the supervisor if it dies, and stops it on quit.
//! A restart bumps a generation number, so a loop left over from the previous
//! settings stops on its own instead of racing the new one.

use std::io::{BufRead, BufReader};
use std::process::{ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

use crate::paths;
use crate::settings::Settings;

/// Longest wait between restarts of a supervisor that keeps exiting.
const MAX_BACKOFF: Duration = Duration::from_secs(30);
/// A supervisor that ran this long before exiting starts over at the shortest wait.
const HEALTHY_RUN: Duration = Duration::from_secs(60);
/// How long a stopped supervisor gets to clean up before it is killed.
const STOP_GRACE: Duration = Duration::from_secs(8);

#[derive(Default)]
struct Inner {
    generation: u64,
    pid: Option<i32>,
    stdin: Option<ChildStdin>,
    status: Option<Value>,
    last_error: Option<String>,
    /// The generation whose UI the main window was sent to, so it is sent once.
    shown: Option<u64>,
    /// A path to open under the UI once it is ready (a room, from an invite).
    pending_path: Option<String>,
}

#[derive(Default)]
pub struct Supervisor {
    inner: Mutex<Inner>,
}

impl Supervisor {
    pub fn status(&self) -> Option<Value> {
        self.inner.lock().unwrap().status.clone()
    }

    pub fn last_error(&self) -> Option<String> {
        self.inner.lock().unwrap().last_error.clone()
    }

    pub fn set_pending_path(&self, path: Option<String>) {
        self.inner.lock().unwrap().pending_path = path;
    }

    /// Whether this status is the first "ready" for its generation; takes the
    /// path waiting to be opened when it is.
    pub fn take_ready(&self, generation: u64) -> Option<Option<String>> {
        let mut inner = self.inner.lock().unwrap();
        if inner.generation != generation || inner.shown == Some(generation) {
            return None;
        }
        inner.shown = Some(generation);
        Some(inner.pending_path.take())
    }

    /// After the supervisor restarts: its next "ready" shows the window again,
    /// at `path` unless a link already asked for somewhere else.
    pub fn rearm(&self, generation: u64, path: Option<String>) {
        let mut inner = self.inner.lock().unwrap();
        if inner.generation != generation {
            return;
        }
        inner.shown = None;
        if inner.pending_path.is_none() {
            inner.pending_path = path;
        }
    }

    fn stale(&self, generation: u64) -> bool {
        self.inner.lock().unwrap().generation != generation
    }

    /// Stop the running supervisor and keep any loop from starting another.
    pub fn stop(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.generation += 1;
        inner.status = None;
        stop_child(&mut inner);
    }
}

fn stop_child(inner: &mut Inner) {
    // Closing stdin asks it to stop; SIGTERM says so again; a supervisor
    // still there after the grace period is killed.
    inner.stdin.take();
    if let Some(pid) = inner.pid.take() {
        unsafe {
            libc::kill(pid, libc::SIGTERM);
        }
        thread::spawn(move || {
            thread::sleep(STOP_GRACE);
            unsafe {
                if libc::kill(pid, 0) == 0 {
                    libc::kill(pid, libc::SIGKILL);
                }
            }
        });
    }
}

/// Start (or restart) the supervisor for `settings`.
pub fn restart(app: &AppHandle, settings: Settings) {
    let sup = app.state::<Supervisor>();
    let generation = {
        let mut inner = sup.inner.lock().unwrap();
        inner.generation += 1;
        inner.status = None;
        inner.last_error = None;
        stop_child(&mut inner);
        inner.generation
    };
    let app = app.clone();
    thread::spawn(move || run(app, settings, generation));
}

fn command(settings: &Settings) -> Result<Command, String> {
    // A stand-in supervisor for development, run with the same arguments.
    let program = match std::env::var_os("MYCELIUM_DESKTOP_SUPERVISOR") {
        Some(p) => p.into(),
        None => paths::resolve("mycelium").ok_or_else(|| {
            "The mycelium program isn't in this app or on this Mac. Reinstall Mycelium.".to_string()
        })?,
    };
    let mut cmd = Command::new(program);
    cmd.args(["desktop", "serve", "--mode", settings.mode.as_str(), "--json"]);
    if let Some(hub) = &settings.hub_url {
        cmd.args(["--hub-url", hub]);
    }
    for root in &settings.roots {
        cmd.args(["--root", root]);
    }
    // The SLIM node's slimctl, pinned to the 2.1.x the hub's bindings speak.
    if let Some(slimctl) = paths::bundled("slimctl") {
        cmd.env("MYCELIUM_SLIMCTL", slimctl);
    }
    // stdin stays piped and open for the supervisor's whole life: it stops
    // when it closes, which is how it goes away even if this app is killed.
    cmd.env("PATH", paths::shell_path())
        .current_dir(paths::home())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    Ok(cmd)
}

fn run(app: AppHandle, settings: Settings, generation: u64) {
    let mut backoff = Duration::from_secs(1);
    loop {
        let sup = app.state::<Supervisor>();
        if sup.stale(generation) {
            return;
        }
        let started = Instant::now();
        match command(&settings).and_then(|mut c| c.spawn().map_err(|e| e.to_string())) {
            Ok(mut child) => {
                {
                    let mut inner = sup.inner.lock().unwrap();
                    if inner.generation != generation {
                        // Settings changed while it was starting.
                        let _ = child.kill();
                        return;
                    }
                    inner.pid = Some(child.id() as i32);
                    inner.stdin = child.stdin.take();
                }
                if let Some(stderr) = child.stderr.take() {
                    thread::spawn(move || {
                        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                            eprintln!("[mycelium] {line}");
                        }
                    });
                }
                if let Some(stdout) = child.stdout.take() {
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        if sup.stale(generation) {
                            break;
                        }
                        handle_line(&app, generation, &line);
                    }
                }
                let _ = child.wait();
            }
            Err(message) => report_error(&app, generation, "app", &message),
        }
        if sup.stale(generation) {
            return;
        }
        if started.elapsed() > HEALTHY_RUN {
            backoff = Duration::from_secs(1);
        }
        // What it serves went away with it: show the window again once it
        // is back, on the page it was on.
        sup.rearm(generation, room_path(&app));
        report_error(
            &app,
            generation,
            "app",
            &format!("Mycelium stopped. Starting it again in {}s.", backoff.as_secs()),
        );
        thread::sleep(backoff);
        backoff = (backoff * 2).min(MAX_BACKOFF);
    }
}

/// The room UI page the main window is on, as a path, or `None` when it is
/// showing one of the app's own pages.
fn room_path(app: &AppHandle) -> Option<String> {
    let url = app.get_webview_window("main")?.url().ok()?;
    if !matches!(url.scheme(), "http" | "https") || url.port() == Some(1420) {
        return None;
    }
    let mut path = url.path().to_string();
    if let Some(query) = url.query() {
        path = format!("{path}?{query}");
    }
    Some(path)
}

fn handle_line(app: &AppHandle, generation: u64, line: &str) {
    let Ok(value) = serde_json::from_str::<Value>(line) else {
        eprintln!("[mycelium] {line}");
        return;
    };
    match value.get("type").and_then(Value::as_str) {
        Some("status") => {
            app.state::<Supervisor>().inner.lock().unwrap().status = Some(value.clone());
            crate::on_status(app, generation, &value);
        }
        Some("error") => {
            let component = value.get("component").and_then(Value::as_str).unwrap_or("app");
            let message = value.get("message").and_then(Value::as_str).unwrap_or("");
            report_error(app, generation, component, message);
        }
        Some("log") => crate::on_log(app, &value),
        _ => {}
    }
}

fn report_error(app: &AppHandle, generation: u64, component: &str, message: &str) {
    let sup = app.state::<Supervisor>();
    {
        let mut inner = sup.inner.lock().unwrap();
        if inner.generation != generation {
            return;
        }
        inner.last_error = Some(message.to_string());
    }
    eprintln!("[mycelium] {component}: {message}");
    crate::on_error(app, &json!({ "component": component, "message": message }));
}

/// Whether a status says the window has something to show: the UI in hub
/// mode, the runner in client mode (the UI is the remote hub's).
pub fn ready(status: &Value) -> bool {
    let state = |name: &str| {
        status
            .pointer(&format!("/components/{name}/state"))
            .and_then(Value::as_str)
            .unwrap_or("")
            == "running"
    };
    match status.get("mode").and_then(Value::as_str) {
        Some("hub") => state("ui"),
        _ => state("runner"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_hub_is_ready_when_its_ui_is_and_a_client_when_its_runner_is() {
        let hub = json!({"mode":"hub","components":{"ui":{"state":"running"},"runner":{"state":"starting"}}});
        assert!(ready(&hub));
        let client = json!({"mode":"client","components":{"ui":{"state":"disabled"},"runner":{"state":"starting"}}});
        assert!(!ready(&client));
        let client = json!({"mode":"client","components":{"runner":{"state":"running"}}});
        assert!(ready(&client));
    }
}
