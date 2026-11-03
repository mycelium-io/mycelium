// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! An agent's session as the rendered view draws it, beside its terminal.
//!
//! The runner on this machine follows each agent CLI's own session file and
//! writes what it converts to `~/.mycelium/runner/sessions/<room>/<handle>.json`:
//! the session (`agent-session.ts`'s `AgentSession`), or why there is none.
//! This reads that file for the app's own pages. Like the screen, it never
//! goes to the hub.

use std::path::Path;

use serde_json::Value;

use crate::{paths, terminal};

/// What `session` refuses with when the agent's CLI has no converter; the
/// page matches it (`UNAVAILABLE` in `agent-session.ts`).
pub const NO_CONVERTER: &str = "No rendered view for this agent's CLI.";
/// What `session` refuses with when the runner found no session file for the
/// agent, or hasn't written one yet; the page matches it too.
pub const NO_SESSION: &str = "Can't find this agent's session.";

/// @`handle`'s session in `room`, as the runner last wrote it.
pub fn session(room: &str, handle: &str) -> Result<Value, String> {
    read(&paths::home().join(".mycelium"), room, handle)
}

/// The page names an agent, never a file: only an agent Mycelium runs in a
/// terminal here (in its herdr registry, the rule `agent_screen` keeps) has
/// a session to read, so no other file under the folder can be named.
fn read(mycelium: &Path, room: &str, handle: &str) -> Result<Value, String> {
    let registry = mycelium.join("herdr").join("registry.json");
    terminal::agent_pane(&registry, room, handle).ok_or(terminal::NOT_HERE)?;
    if [room, handle].iter().any(|s| s.starts_with('.') || s.contains('\\')) {
        return Err(terminal::NOT_HERE.into());
    }
    let file = mycelium.join("runner").join("sessions").join(room).join(format!("{handle}.json"));
    let Ok(raw) = std::fs::read_to_string(file) else { return Err(NO_SESSION.into()) };
    let Ok(value) = serde_json::from_str::<Value>(&raw) else { return Err(NO_SESSION.into()) };
    match value.get("unavailable").and_then(Value::as_str) {
        Some("no_converter") => Err(NO_CONVERTER.into()),
        Some(_) => Err(NO_SESSION.into()),
        None if value.is_object() => Ok(value),
        None => Err(NO_SESSION.into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Home(std::path::PathBuf);

    impl Home {
        fn new(name: &str) -> Self {
            let dir = std::env::temp_dir().join(format!("myc-session-{name}-{}", std::process::id()));
            std::fs::create_dir_all(dir.join("herdr")).unwrap();
            std::fs::write(
                dir.join("herdr").join("registry.json"),
                r#"{"checkout/builder": {"pane": "w3:p1"}, "checkout/..": {"pane": "w3:p2"}}"#,
            )
            .unwrap();
            Self(dir)
        }

        fn wrote(&self, room: &str, handle: &str, body: &str) {
            let dir = self.0.join("runner").join("sessions").join(room);
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join(format!("{handle}.json")), body).unwrap();
        }
    }

    impl Drop for Home {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).ok();
        }
    }

    #[test]
    fn a_session_the_runner_wrote_reaches_the_page_as_written() {
        let home = Home::new("written");
        home.wrote("checkout", "builder", r#"{"version": 1, "sessionId": "s1", "entries": []}"#);
        let got = read(&home.0, "checkout", "builder").unwrap();
        assert_eq!(got["sessionId"], "s1");
    }

    #[test]
    fn no_session_says_which_of_the_two_reasons() {
        let home = Home::new("reasons");
        // Nothing written yet.
        assert_eq!(read(&home.0, "checkout", "builder").unwrap_err(), NO_SESSION);
        home.wrote("checkout", "builder", r#"{"unavailable": "no_converter"}"#);
        assert_eq!(read(&home.0, "checkout", "builder").unwrap_err(), NO_CONVERTER);
        home.wrote("checkout", "builder", r#"{"unavailable": "no_session"}"#);
        assert_eq!(read(&home.0, "checkout", "builder").unwrap_err(), NO_SESSION);
        // Half a file, or not a session at all.
        home.wrote("checkout", "builder", r#"{"version": 1, "sess"#);
        assert_eq!(read(&home.0, "checkout", "builder").unwrap_err(), NO_SESSION);
        home.wrote("checkout", "builder", "[]");
        assert_eq!(read(&home.0, "checkout", "builder").unwrap_err(), NO_SESSION);
    }

    #[test]
    fn only_an_agent_mycelium_runs_here_has_a_session_to_read() {
        let home = Home::new("own");
        home.wrote("storefront", "builder", r#"{"version": 1}"#);
        // Not in the registry for that room: refused as the screen is.
        assert_eq!(read(&home.0, "storefront", "builder").unwrap_err(), terminal::NOT_HERE);
        // A name that would climb out of the folder, even one in the registry.
        assert_eq!(read(&home.0, "checkout", "..").unwrap_err(), terminal::NOT_HERE);
        assert_eq!(read(&home.0, "checkout/builder", "").unwrap_err(), terminal::NOT_HERE);
    }
}
