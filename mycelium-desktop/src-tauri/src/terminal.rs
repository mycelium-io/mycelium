// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! The agents terminal: herdr, attached in a pseudo-terminal the window draws.
//!
//! The only program this module starts is herdr. There is no command that
//! takes a program or arguments from a page, so nothing that reaches these
//! commands can run anything else on the machine.

use std::io::{Read, Write};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};

use crate::paths;

/// How long to let herdr attach before asking it to show a pane.
const ATTACH_SETTLE: Duration = Duration::from_millis(700);

struct Session {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    child: Box<dyn Child + Send + Sync>,
}

#[derive(Default)]
pub struct Terminal {
    session: Mutex<Option<Session>>,
}

fn herdr() -> Result<std::path::PathBuf, String> {
    paths::resolve("herdr").ok_or_else(|| {
        "herdr isn't installed here, so there is no agents terminal to show.".to_string()
    })
}

/// The variables herdr sets inside its own panes; any of them reads as nesting.
const PANE_MARKERS: [&str; 5] = [
    "HERDR_ENV",
    "HERDR_PANE_ID",
    "HERDR_TAB_ID",
    "HERDR_WORKSPACE_ID",
    "HERDR_STARTUP_CWD",
];

fn size(cols: u16, rows: u16) -> PtySize {
    PtySize { rows: rows.max(2), cols: cols.max(10), pixel_width: 0, pixel_height: 0 }
}

/// Attach herdr in a new pseudo-terminal, or reuse the one already attached.
pub fn open(app: &AppHandle, pane: Option<String>, cols: u16, rows: u16) -> Result<(), String> {
    let term = app.state::<Terminal>();
    let mut guard = term.session.lock().unwrap();
    if guard.is_none() {
        let pty = native_pty_system().openpty(size(cols, rows)).map_err(|e| e.to_string())?;
        let mut cmd = CommandBuilder::new(herdr()?);
        cmd.env("TERM", "xterm-256color");
        cmd.env("COLORTERM", "truecolor");
        cmd.env("PATH", paths::shell_path());
        // When the app itself was started from inside a herdr pane, it carries
        // that pane's markers, and herdr refuses to attach "nested". The
        // socket path stays, so it still finds the same server.
        for marker in PANE_MARKERS {
            cmd.env_remove(marker);
        }
        cmd.cwd(paths::home());
        let child = pty.slave.spawn_command(cmd).map_err(|e| e.to_string())?;
        drop(pty.slave);
        let mut reader = pty.master.try_clone_reader().map_err(|e| e.to_string())?;
        let writer = pty.master.take_writer().map_err(|e| e.to_string())?;
        let handle = app.clone();
        thread::spawn(move || {
            let mut buf = [0u8; 8192];
            let mut carry: Vec<u8> = Vec::new();
            loop {
                match reader.read(&mut buf) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        carry.extend_from_slice(&buf[..n]);
                        // Send only whole characters; keep a split one for the next read.
                        let valid = match std::str::from_utf8(&carry) {
                            Ok(_) => carry.len(),
                            Err(e) if e.error_len().is_none() => e.valid_up_to(),
                            Err(_) => carry.len(),
                        };
                        let text = String::from_utf8_lossy(&carry[..valid]).to_string();
                        carry.drain(..valid);
                        let _ = handle.emit_to("terminal", "terminal-data", text);
                    }
                }
            }
            let _ = handle.emit_to("terminal", "terminal-exit", ());
            if let Some(t) = handle.try_state::<Terminal>() {
                t.session.lock().unwrap().take();
            }
        });
        *guard = Some(Session { master: pty.master, writer, child });
    }
    drop(guard);
    if let Some(pane) = pane {
        thread::spawn(move || {
            thread::sleep(ATTACH_SETTLE);
            focus_pane(&pane);
        });
    }
    Ok(())
}

pub fn write(app: &AppHandle, data: &str) -> Result<(), String> {
    let term = app.state::<Terminal>();
    let mut guard = term.session.lock().unwrap();
    let session = guard.as_mut().ok_or("The agents terminal isn't open.")?;
    session.writer.write_all(data.as_bytes()).map_err(|e| e.to_string())?;
    session.writer.flush().map_err(|e| e.to_string())
}

pub fn resize(app: &AppHandle, cols: u16, rows: u16) -> Result<(), String> {
    let term = app.state::<Terminal>();
    let guard = term.session.lock().unwrap();
    if let Some(session) = guard.as_ref() {
        session.master.resize(size(cols, rows)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Detach: end the herdr client. The herdr session and its agents keep running.
pub fn close(app: &AppHandle) {
    if let Some(term) = app.try_state::<Terminal>() {
        if let Some(mut session) = term.session.lock().unwrap().take() {
            let _ = session.child.kill();
        }
    }
}

/// Bring a pane's workspace and tab to the front in the attached herdr.
///
/// herdr focuses panes only by direction, so the tab the pane is in is the
/// closest a named pane gets: its workspace, then its tab.
pub fn focus_pane(pane: &str) {
    let Ok(bin) = herdr() else { return };
    let run = |args: &[&str]| {
        paths::command(&bin).args(args).env("PATH", paths::shell_path()).output().ok()
    };
    let Some(out) = run(&["pane", "get", pane]) else { return };
    let info: Value = serde_json::from_slice(&out.stdout).unwrap_or(Value::Null);
    let tab = find_str(&info, "tab_id");
    let workspace = find_str(&info, "workspace_id")
        .or_else(|| pane.split_once(':').map(|(w, _)| w.to_string()));
    if let Some(ws) = workspace {
        run(&["workspace", "focus", &ws]);
    }
    if let Some(tab) = tab {
        run(&["tab", "focus", &tab]);
    }
}

fn find_str(value: &Value, key: &str) -> Option<String> {
    match value {
        Value::Object(map) => map
            .get(key)
            .and_then(Value::as_str)
            .map(String::from)
            .or_else(|| map.values().find_map(|v| find_str(v, key))),
        Value::Array(items) => items.iter().find_map(|v| find_str(v, key)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_pane_lookup_finds_its_tab_wherever_herdr_nests_it() {
        let v = json!({"id":"cli:pane:get","result":{"pane":{"pane_id":"w2:p9","tab_id":"w2:t9"}}});
        assert_eq!(find_str(&v, "tab_id").as_deref(), Some("w2:t9"));
        assert_eq!(find_str(&v, "workspace_id"), None);
    }
}
