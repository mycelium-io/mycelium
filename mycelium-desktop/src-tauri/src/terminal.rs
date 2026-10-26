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

/// One agent herdr is running, as the window names it.
#[derive(serde::Serialize, Debug, PartialEq)]
pub struct Agent {
    pub name: String,
    pub status: String,
    pub pane: String,
}

/// The agents herdr is running and whether each is working, idle or
/// waiting for someone. Empty when herdr can't be asked.
pub fn agents() -> Vec<Agent> {
    let Ok(bin) = herdr() else { return Vec::new() };
    let Ok(out) =
        paths::command(&bin).args(["agent", "list"]).env("PATH", paths::shell_path()).output()
    else {
        return Vec::new();
    };
    parse_agents(&serde_json::from_slice(&out.stdout).unwrap_or(Value::Null))
}

fn parse_agents(value: &Value) -> Vec<Agent> {
    let field = |a: &Value, k: &str| a.get(k).and_then(Value::as_str).map(String::from);
    value
        .pointer("/result/agents")
        .and_then(Value::as_array)
        .map(|agents| {
            agents
                .iter()
                .filter_map(|a| {
                    Some(Agent {
                        name: field(a, "name").or_else(|| field(a, "agent"))?,
                        status: field(a, "agent_status").unwrap_or_else(|| "unknown".into()),
                        pane: field(a, "pane_id")?,
                    })
                })
                .collect()
        })
        .unwrap_or_default()
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

/// How many of a terminal's recent lines a page gets: its screen and the
/// scrollback above it, so a view taller than the herdr pane is filled.
const SCREEN_LINES: &str = "500";

/// What @`handle`'s terminal in `room` shows, in color, with the recent lines
/// above its screen, read from herdr on this machine for the app's own pages
/// to draw. It goes nowhere else: no hub, no network, so a screen with a key
/// or private code on it stays here.
///
/// The page names an agent, never a pane: the pane is looked up in the herdr
/// registry Mycelium keeps of its agents, so a page can't read the person's
/// own shells or any other terminal, however it guesses at pane ids.
pub fn screen(room: &str, handle: &str) -> Result<Screen, String> {
    let registry = paths::home().join(".mycelium").join("herdr").join("registry.json");
    let pane = agent_pane(&registry, room, handle).ok_or(NOT_HERE)?;
    let bin = herdr()?;
    let out = paths::command(&bin)
        .args(["pane", "read", &pane, "--source", "recent", "--lines", SCREEN_LINES, "--format", "ansi"])
        .env("PATH", paths::shell_path())
        .output()
        .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err("herdr couldn't read that terminal. It may have closed.".into());
    }
    Ok(Screen { pane, text: String::from_utf8_lossy(&out.stdout).into_owned() })
}

/// What `screen` refuses with when the agent has no terminal on this machine;
/// the page says where it runs instead (`agent-screen.tsx` matches it).
pub const NOT_HERE: &str = "That agent isn't running in a terminal on this machine.";

/// An agent's screen, and the pane it's in, for Open its terminal.
#[derive(serde::Serialize)]
pub struct Screen {
    pub pane: String,
    pub text: String,
}

/// The pane the registry at `registry` (`{"room/handle": {"pane": …}}`, written
/// by the runner and `mycelium herdr`) maps @`handle` of `room` to, if it's a
/// well-formed one.
fn agent_pane(registry: &std::path::Path, room: &str, handle: &str) -> Option<String> {
    if room.is_empty() || handle.is_empty() || room.contains('/') || handle.contains('/') {
        return None;
    }
    let raw: Value = serde_json::from_str(&std::fs::read_to_string(registry).ok()?).ok()?;
    let pane = raw.get(format!("{room}/{handle}"))?.get("pane")?.as_str()?;
    is_pane_id(pane).then(|| pane.to_string())
}

/// A herdr pane id as herdr writes one (`w2:p3D`), so nothing from the
/// registry can be slipped into herdr's arguments as an option.
fn is_pane_id(pane: &str) -> bool {
    let ok = |s: &str| !s.is_empty() && s.len() <= 16 && s.chars().all(|c| c.is_ascii_alphanumeric());
    matches!(pane.split_once(':'), Some((w, p)) if w.starts_with('w') && p.starts_with('p') && ok(w) && ok(p))
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

    #[test]
    fn only_a_pane_id_reaches_herdr() {
        assert!(is_pane_id("w2:p3D"));
        assert!(is_pane_id("w15:p1"));
        for bad in ["", "w2", "--help:p1", "w2:p1 --raw", "w2:p1;ls", "x2:p1", "w2:t1", "w2:p1:p2"] {
            assert!(!is_pane_id(bad), "{bad}");
        }
    }

    #[test]
    fn only_an_agents_own_pane_is_ever_read() {
        let dir = std::env::temp_dir().join(format!("myc-registry-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let registry = dir.join("registry.json");
        std::fs::write(
            &registry,
            r#"{"checkout/builder": {"pane": "w3:p1", "kind": "claude"},
                "checkout/odd": {"pane": "--raw"}}"#,
        )
        .unwrap();
        assert_eq!(agent_pane(&registry, "checkout", "builder").as_deref(), Some("w3:p1"));
        // Not an agent of that room, or not in the registry at all: the
        // person's own shells can't be named.
        assert_eq!(agent_pane(&registry, "storefront", "builder"), None);
        assert_eq!(agent_pane(&registry, "checkout", "w1:p1"), None);
        // A key can't be built to reach another entry, and a bad pane is refused.
        assert_eq!(agent_pane(&registry, "checkout/builder", ""), None);
        assert_eq!(agent_pane(&registry, "checkout", "odd"), None);
        assert_eq!(agent_pane(&dir.join("missing.json"), "checkout", "builder"), None);
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn an_agent_is_named_by_its_handle_else_its_cli() {
        let v = json!({"result":{"agents":[
            {"agent":"claude","name":"builder","agent_status":"blocked","pane_id":"w1:p1"},
            {"agent":"codex","agent_status":"idle","pane_id":"w1:p2"},
            {"agent":"pi"}
        ]}});
        let got = parse_agents(&v);
        assert_eq!(got.len(), 2);
        assert_eq!(
            got[0],
            Agent { name: "builder".into(), status: "blocked".into(), pane: "w1:p1".into() }
        );
        assert_eq!(got[1].name, "codex");
        assert!(parse_agents(&Value::Null).is_empty());
    }
}
