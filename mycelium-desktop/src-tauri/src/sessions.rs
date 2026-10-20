// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! A person's sign-in, kept by the app, given to the CLI only with their yes.
//!
//! Every agent on this computer runs as the same user as the person, so a
//! sign-in in a file the CLI reads is one any agent can act as. The app keeps
//! it instead: in the macOS keychain, on an item only this app can read
//! without asking, and in memory while the app runs elsewhere. The CLI asks
//! for it through the supervisor (`mycelium.desktop.session_relay`), which
//! passes each request here as a `session` event and takes the answer back on
//! its stdin.
//!
//! Before the CLI gets it, the person is asked: Touch ID or their password on
//! macOS, a dialog elsewhere, naming the command that asked and its folder (as
//! the supervisor read them from the socket's peer, never from the request).
//! An agent can't answer either. After a yes, reads for the same hub from the
//! same terminal go through for [`GRACE`], so a person typing several commands
//! isn't asked each time, while an agent in its own pane (another terminal) or
//! a program with no terminal is still asked.

use std::collections::HashMap;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

/// How long a yes lets the same hub's sign-in through without asking again.
pub const GRACE: Duration = Duration::from_secs(5 * 60);
/// The keychain service the sign-ins are kept under, one item per hub.
#[cfg(target_os = "macos")]
const SERVICE: &str = "Mycelium sign-in";

#[derive(Default)]
pub struct Sessions {
    /// Sign-ins kept in memory where there's no keychain to keep them in.
    #[cfg(not(target_os = "macos"))]
    kept: Mutex<HashMap<String, String>>,
    /// When the person last said yes, per hub.
    approved: Mutex<HashMap<String, Instant>>,
}

/// Answer one `session` event from the supervisor, off the reading thread:
/// a question to the person can take as long as they take.
pub fn on_event(app: &AppHandle, event: &Value) {
    let app = app.clone();
    let event = event.clone();
    thread::spawn(move || {
        let id = event.get("id").cloned().unwrap_or(Value::Null);
        let reply = answer(&app, &event);
        let line = json!({ "session_reply": id }).as_object().cloned().map(|mut m| {
            if let Value::Object(body) = reply {
                m.extend(body);
            }
            Value::Object(m)
        });
        if let Some(line) = line {
            crate::supervisor::reply(&app, &line.to_string());
        }
    });
}

/// Who's asking, as the supervisor read it from the socket (never from the
/// request): the command, its folder, and its terminal.
struct Caller {
    command: String,
    cwd: String,
    tty: Option<String>,
}

impl Caller {
    fn of(event: &Value) -> Self {
        let field = |k: &str| {
            event.get("caller").and_then(|c| c.get(k)).and_then(Value::as_str).map(String::from)
        };
        Self {
            command: field("command").unwrap_or_else(|| "a program".into()),
            cwd: field("cwd").unwrap_or_else(|| "an unknown folder".into()),
            tty: field("tty").filter(|t| !t.is_empty()),
        }
    }

    /// What a yes covers for [`GRACE`]: this hub, from this terminal only. A
    /// program with no terminal (an agent's background job, a script) gets
    /// none, and is asked every time.
    fn grace_key(&self, hub: &str) -> Option<String> {
        self.tty.as_ref().map(|tty| format!("{hub}\n{tty}"))
    }
}

fn answer(app: &AppHandle, event: &Value) -> Value {
    let Some(hub) = event.get("hub").and_then(Value::as_str) else {
        return json!({ "ok": false, "error": "no hub" });
    };
    let caller = Caller::of(event);
    let sessions = app.state::<Sessions>();
    match event.get("op").and_then(Value::as_str) {
        Some("get") => {
            let Some(kept) = load(&sessions, hub) else {
                // Nothing kept: nothing to ask about.
                return json!({ "ok": true, "session": null });
            };
            let what = format!(
                "give your sign-in for {hub} to “{}”, run in {}",
                caller.command, caller.cwd
            );
            if !approved(app, &sessions, caller.grace_key(hub), &what) {
                return json!({ "ok": false, "error": "you said no, or didn't answer" });
            }
            json!({ "ok": true, "session": serde_json::from_str::<Value>(&kept).unwrap_or(Value::Null) })
        }
        Some("put") => {
            let Some(session) = event.get("session").filter(|s| s.is_object()) else {
                return json!({ "ok": false, "error": "no sign-in to keep" });
            };
            let what = format!(
                "keep your sign-in for {hub}, from “{}”, run in {}",
                caller.command, caller.cwd
            );
            if !approved(app, &sessions, caller.grace_key(hub), &what) {
                return json!({ "ok": false, "error": "you said no, or didn't answer" });
            }
            match store(&sessions, hub, &session.to_string()) {
                Ok(()) => json!({ "ok": true }),
                Err(e) => json!({ "ok": false, "error": e }),
            }
        }
        Some("delete") => {
            let prefix = format!("{hub}\n");
            sessions.approved.lock().unwrap().retain(|k, _| !k.starts_with(&prefix));
            json!({ "ok": remove(&sessions, hub) })
        }
        _ => json!({ "ok": false, "error": "unknown request" }),
    }
}

/// Whether the person says yes, or said yes for this key (hub and terminal)
/// within [`GRACE`]. With no key there's no grace: it asks.
fn approved(app: &AppHandle, sessions: &Sessions, key: Option<String>, what: &str) -> bool {
    if let Some(key) = &key {
        let approved = sessions.approved.lock().unwrap();
        if approved.get(key).is_some_and(|at| at.elapsed() < GRACE) {
            return true;
        }
    }
    let yes = ask(app, what);
    if let (true, Some(key)) = (yes, key) {
        sessions.approved.lock().unwrap().insert(key, Instant::now());
    }
    yes
}

/// Touch ID or the account password, through the system's own sheet.
#[cfg(target_os = "macos")]
fn ask(_app: &AppHandle, what: &str) -> bool {
    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2_foundation::{NSError, NSString};
    use objc2_local_authentication::{LAContext, LAPolicy};
    use std::sync::mpsc;

    let (tx, rx) = mpsc::channel::<bool>();
    // The system shows it as "Mycelium is trying to <reason>."
    let reason = NSString::from_str(what);
    let reply = RcBlock::new(move |ok: Bool, _error: *mut NSError| {
        let _ = tx.send(ok.as_bool());
    });
    unsafe {
        let context = LAContext::new();
        context.evaluatePolicy_localizedReason_reply(
            LAPolicy::DeviceOwnerAuthentication,
            &reason,
            &reply,
        );
    }
    rx.recv_timeout(Duration::from_secs(120)).unwrap_or(false)
}

/// A dialog only the person at the screen can answer.
#[cfg(not(target_os = "macos"))]
fn ask(app: &AppHandle, what: &str) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

    app.dialog()
        .message(format!("Mycelium is asked to {what}. Allow it?"))
        .title("Mycelium")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Allow".into(), "Don't allow".into()))
        .blocking_show()
}

#[cfg(target_os = "macos")]
fn load(_sessions: &Sessions, hub: &str) -> Option<String> {
    let bytes = security_framework::passwords::get_generic_password(SERVICE, hub).ok()?;
    String::from_utf8(bytes).ok()
}

#[cfg(target_os = "macos")]
fn store(_sessions: &Sessions, hub: &str, value: &str) -> Result<(), String> {
    // Created by this app, so only this app reads it without the system asking.
    security_framework::passwords::set_generic_password(SERVICE, hub, value.as_bytes())
        .map_err(|e| e.to_string())
}

#[cfg(target_os = "macos")]
fn remove(_sessions: &Sessions, hub: &str) -> bool {
    security_framework::passwords::delete_generic_password(SERVICE, hub).is_ok()
}

#[cfg(not(target_os = "macos"))]
fn load(sessions: &Sessions, hub: &str) -> Option<String> {
    sessions.kept.lock().unwrap().get(hub).cloned()
}

#[cfg(not(target_os = "macos"))]
fn store(sessions: &Sessions, hub: &str, value: &str) -> Result<(), String> {
    sessions.kept.lock().unwrap().insert(hub.to_string(), value.to_string());
    Ok(())
}

#[cfg(not(target_os = "macos"))]
fn remove(sessions: &Sessions, hub: &str) -> bool {
    sessions.kept.lock().unwrap().remove(hub).is_some()
}

/// A token for this launch of the app, for its UI server to require of every
/// request: held in memory and handed to the window, never written down.
pub fn launch_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the system's random source");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
