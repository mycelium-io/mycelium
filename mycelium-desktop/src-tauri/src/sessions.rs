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
    let refused = || json!({ "ok": false, "error": "you said no, or didn't answer" });
    let kept = load(&sessions, hub).and_then(|k| serde_json::from_str::<Value>(&k).ok());
    match event.get("op").and_then(Value::as_str) {
        Some("get") => {
            // Nothing kept: nothing to ask about.
            let Some(kept) = kept else { return json!({ "ok": true, "session": null }) };
            let what = format!(
                "give your sign-in for {hub}{} to “{}”, run in {}",
                as_whom(&kept),
                caller.command,
                caller.cwd
            );
            if !approved(app, &sessions, caller.grace_key(hub), &what) {
                return refused();
            }
            // Renewed here, with the refresh token that never leaves the app,
            // so a command only ever holds something that runs out in minutes.
            let current = match renew_if_due(&kept) {
                Renewal::Fresh => kept,
                Renewal::Renewed(next) => {
                    let _ = store(&sessions, hub, &next.to_string());
                    next
                }
                Renewal::Failed(why) => {
                    return json!({ "ok": false, "error": format!("{why}; sign in again with mycelium login") })
                }
            };
            json!({ "ok": true, "session": handed_out(&current) })
        }
        Some("put") => {
            let Some(session) = event.get("session").filter(|s| s.is_object()) else {
                return json!({ "ok": false, "error": "no sign-in to keep" });
            };
            let new_handle = handle_of(session);
            let old_handle = kept.as_ref().and_then(handle_of);
            let account = new_handle.as_deref().map_or("an account it doesn't name".to_string(), |h| format!("@{h}"));
            let what = match old_handle {
                Some(old) if Some(&old) != new_handle.as_ref() => format!(
                    "replace your sign-in for {hub} as @{old} with one as {account}, from “{}”, run in {}",
                    caller.command, caller.cwd
                ),
                _ => format!(
                    "keep a sign-in for {hub} as {account}, from “{}”, run in {}",
                    caller.command, caller.cwd
                ),
            };
            // Always asked: whose account your commands act as is never covered
            // by a yes given for something else.
            if !approved(app, &sessions, None, &what) {
                return refused();
            }
            match store(&sessions, hub, &session.to_string()) {
                Ok(()) => json!({ "ok": true }),
                Err(e) => json!({ "ok": false, "error": e }),
            }
        }
        Some("delete") => {
            let Some(kept) = kept else { return json!({ "ok": false }) };
            let what = format!(
                "remove your sign-in for {hub}{}, for “{}”, run in {}",
                as_whom(&kept),
                caller.command,
                caller.cwd
            );
            if !approved(app, &sessions, None, &what) {
                return refused();
            }
            let prefix = format!("{hub}\n");
            sessions.approved.lock().unwrap().retain(|k, _| !k.starts_with(&prefix));
            json!({ "ok": remove(&sessions, hub) })
        }
        _ => json!({ "ok": false, "error": "unknown request" }),
    }
}

/// " as @handle" for a kept sign-in whose token names one, else nothing.
fn as_whom(session: &Value) -> String {
    handle_of(session).map(|h| format!(" as @{h}")).unwrap_or_default()
}

/// Whose account a sign-in is, from its access token's claims (read, never
/// verified: the hub verifies; this only names it in a question).
fn handle_of(session: &Value) -> Option<String> {
    use base64::Engine;

    let token = session.get("access_token")?.as_str()?;
    let payload = token.split('.').nth(1)?;
    let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload.trim_end_matches('='))
        .ok()?;
    let claims: Value = serde_json::from_slice(&bytes).ok()?;
    ["preferred_username", "sub"]
        .iter()
        .find_map(|k| claims.get(*k).and_then(Value::as_str))
        .map(|h| h.trim_start_matches('@').to_lowercase())
}

/// What a command gets: the sign-in without its refresh token, which stays
/// with the app, so nothing a command holds outlives its access token.
fn handed_out(session: &Value) -> Value {
    let mut out = session.clone();
    if let Some(map) = out.as_object_mut() {
        map.remove("refresh_token");
        map.remove("refresh_expires_at");
    }
    out
}

enum Renewal {
    Fresh,
    Renewed(Value),
    Failed(String),
}

/// Seconds before expiry a sign-in is renewed, so a command's call can't
/// carry one that dies on the way.
const RENEW_SKEW_S: f64 = 60.0;

/// The kept sign-in renewed with its refresh token when its access token is
/// about to run out.
fn renew_if_due(session: &Value) -> Renewal {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    match session.get("expires_at").and_then(Value::as_f64) {
        Some(at) if at - RENEW_SKEW_S > now => return Renewal::Fresh,
        None => return Renewal::Fresh, // no expiry given: nothing to renew against
        _ => {}
    }
    let field = |k: &str| session.get(k).and_then(Value::as_str).filter(|s| !s.is_empty());
    let (Some(refresh), Some(endpoint), Some(client_id)) =
        (field("refresh_token"), field("token_endpoint"), field("client_id"))
    else {
        return Renewal::Failed("your sign-in has expired and can't be renewed".into());
    };
    let body = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("grant_type", "refresh_token")
        .append_pair("refresh_token", refresh)
        .append_pair("client_id", client_id)
        .finish();
    let endpoint = endpoint.to_string();
    let answer = tauri::async_runtime::block_on(async move {
        let client = crate::download::client(None, false)?;
        let resp = client
            .post(&endpoint)
            .header(reqwest::header::CONTENT_TYPE, "application/x-www-form-urlencoded")
            .body(body)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        let status = resp.status();
        let bytes = resp.bytes().await.map_err(|e| e.to_string())?;
        if !status.is_success() {
            return Err(format!("the sign-in provider refused to renew it ({status})"));
        }
        serde_json::from_slice::<Value>(&bytes).map_err(|e| e.to_string())
    });
    let grant = match answer {
        Ok(grant) => grant,
        Err(why) => return Renewal::Failed(why),
    };
    let Some(access) = grant.get("access_token").and_then(Value::as_str) else {
        return Renewal::Failed("the sign-in provider sent no new token".into());
    };
    let mut next = session.clone();
    if let Some(map) = next.as_object_mut() {
        map.insert("access_token".into(), json!(access));
        let lasts = grant.get("expires_in").and_then(Value::as_f64).unwrap_or(300.0);
        map.insert("expires_at".into(), json!(now + lasts));
        // Issuers that rotate refresh tokens send a new one; keep it here.
        if let Some(rotated) = grant.get("refresh_token").and_then(Value::as_str) {
            map.insert("refresh_token".into(), json!(rotated));
            if let Some(r) = grant.get("refresh_expires_in").and_then(Value::as_f64) {
                map.insert("refresh_expires_at".into(), json!(now + r));
            }
        }
    }
    Renewal::Renewed(next)
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

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;

    fn jwt(claims: Value) -> String {
        let b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD;
        format!("{}.{}.sig", b64.encode(b"{}"), b64.encode(claims.to_string()))
    }

    #[test]
    fn a_command_never_gets_the_refresh_token() {
        let kept = json!({
            "access_token": "at", "refresh_token": "rt", "refresh_expires_at": 9.0, "expires_at": 1.0
        });
        let out = handed_out(&kept);
        assert_eq!(out["access_token"], "at");
        assert!(out.get("refresh_token").is_none());
        assert!(out.get("refresh_expires_at").is_none());
    }

    #[test]
    fn a_sign_in_is_named_by_its_tokens_account() {
        let s = json!({ "access_token": jwt(json!({ "preferred_username": "Julia", "sub": "x" })) });
        assert_eq!(handle_of(&s).as_deref(), Some("julia"));
        let only_sub = json!({ "access_token": jwt(json!({ "sub": "avery" })) });
        assert_eq!(handle_of(&only_sub).as_deref(), Some("avery"));
        assert_eq!(handle_of(&json!({ "access_token": "opaque" })), None);
        assert_eq!(as_whom(&s), " as @julia");
    }

    #[test]
    fn a_fresh_sign_in_isnt_renewed() {
        let later = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs_f64()
            + 3600.0;
        assert!(matches!(renew_if_due(&json!({ "expires_at": later })), Renewal::Fresh));
        assert!(matches!(renew_if_due(&json!({ "expires_at": 1.0 })), Renewal::Failed(_)));
    }

    #[test]
    fn a_yes_holds_for_one_terminal_and_none_without_one() {
        let event = |tty: Value| json!({ "caller": { "command": "mycelium x", "cwd": "~", "tty": tty } });
        assert_eq!(Caller::of(&event(json!("ttys003"))).grace_key("h").as_deref(), Some("h\nttys003"));
        assert_eq!(Caller::of(&event(Value::Null)).grace_key("h"), None);
    }
}
