// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! An agent's session as the rendered view draws it, beside its terminal.
//!
//! The runner on this machine follows each agent CLI's own session file and
//! writes what it converts to `~/.mycelium/runner/sessions/<room>/<handle>.json`:
//! the session (`agent-session.ts`'s `AgentSession`), or why there is none.
//! This reads that file for the app's own pages. Like the screen, it never
//! goes to the hub.
//!
//! It also lists this machine's earlier sessions with their titles, for the
//! Add member dialog to bring one into a room. A title is the person's own
//! words (the CLI's title for a session, else what it was first asked), so it
//! comes from the local `mycelium` program to this window only; the runner's
//! scan, which goes through the hub, carries the same sessions with none.

use std::path::Path;

use serde_json::Value;

use crate::{paths, terminal};

/// What `session` refuses with when the agent's CLI has no converter; the
/// page matches it (`UNAVAILABLE` in `agent-session.ts`).
pub const NO_CONVERTER: &str = "No rendered view for this agent's CLI.";
/// What `session` refuses with when the runner found no session file for the
/// agent, or hasn't written one yet; the page matches it too.
pub const NO_SESSION: &str = "Can't find this agent's session.";
/// What `page` refuses with when the entry it reads back from isn't in the
/// agent's session (the page matches it).
pub const NO_ENTRY: &str = "That entry isn't in this session.";
/// The most entries one earlier page may ask for.
const PAGE_MAX: u32 = 500;

/// @`handle`'s session in `room`, as the runner last wrote it.
pub fn session(room: &str, handle: &str) -> Result<Value, String> {
    read(&paths::home().join(".mycelium"), room, handle)
}

/// The `limit` entries of @`handle`'s session before the entry `before`, for
/// the view to show on scroll-up: `{entries, earlier}`. The runner writes only
/// the latest entries, so an earlier page is converted on demand by the
/// `mycelium` program on this machine, which reads the agent CLI's own file.
pub fn page(room: &str, handle: &str, before: &str, limit: u32) -> Result<Value, String> {
    let args = page_args(&paths::home().join(".mycelium"), room, handle, before, limit)?;
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = paths::command(bin)
        .args(args)
        .env("PATH", paths::shell_path())
        .output()
        .map_err(|e| e.to_string())?;
    page_answer(&out.stdout)
}

/// The page names an agent, never a file: only an agent Mycelium runs in a
/// terminal here (in its herdr registry, the rule `agent_screen` keeps) has
/// a session to read, so no other file under the folder can be named.
fn own_agent(mycelium: &Path, room: &str, handle: &str) -> Result<(), String> {
    let registry = mycelium.join("herdr").join("registry.json");
    terminal::agent_pane(&registry, room, handle).ok_or(terminal::NOT_HERE)?;
    if [room, handle].iter().any(|s| s.starts_with(['.', '-']) || s.contains('\\')) {
        return Err(terminal::NOT_HERE.into());
    }
    Ok(())
}

fn read(mycelium: &Path, room: &str, handle: &str) -> Result<Value, String> {
    own_agent(mycelium, room, handle)?;
    let file = mycelium.join("runner").join("sessions").join(room).join(format!("{handle}.json"));
    let Ok(raw) = std::fs::read_to_string(file) else { return Err(NO_SESSION.into()) };
    let Ok(value) = serde_json::from_str::<Value>(&raw) else { return Err(NO_SESSION.into()) };
    answer(value, NO_SESSION)
}

/// The value itself, or the refusal for why there's none: `unavailable`'s
/// reason, else `otherwise` when it isn't a session or a page at all.
fn answer(value: Value, otherwise: &str) -> Result<Value, String> {
    match value.get("unavailable").and_then(Value::as_str) {
        Some("no_converter") => Err(NO_CONVERTER.into()),
        Some("no_entry") => Err(NO_ENTRY.into()),
        Some(_) => Err(NO_SESSION.into()),
        None if value.is_object() => Ok(value),
        None => Err(otherwise.into()),
    }
}

/// What the `mycelium` program is run with for an earlier page, once
/// everything the page sent is checked: an agent of this machine's, an entry
/// id that can only be an id, and a limit in range. Each value is joined to
/// its flag with `=`, and the handle comes after `--`, so none can be read as
/// an option.
fn page_args(
    mycelium: &Path,
    room: &str,
    handle: &str,
    before: &str,
    limit: u32,
) -> Result<Vec<String>, String> {
    own_agent(mycelium, room, handle)?;
    // A line's uuid, or a CLI's own id for a call or a reply (`toolu_01…`).
    let id = |s: &str| {
        !s.is_empty()
            && s.len() <= 64
            && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    };
    if !id(before) || before.starts_with('-') {
        return Err(NO_ENTRY.into());
    }
    if !(1..=PAGE_MAX).contains(&limit) {
        return Err(format!("A page holds 1 to {PAGE_MAX} entries."));
    }
    Ok(vec![
        "machine".into(),
        "session".into(),
        format!("--room={room}"),
        format!("--before={before}"),
        format!("--limit={limit}"),
        "--json".into(),
        "--".into(),
        handle.into(),
    ])
}

/// What the program printed: a page, a refusal, or (nothing parseable) an
/// error that says the page couldn't be read.
fn page_answer(stdout: &[u8]) -> Result<Value, String> {
    const UNREAD: &str = "Couldn't read that part of the session.";
    let value = serde_json::from_slice::<Value>(stdout).map_err(|_| UNREAD.to_string())?;
    let page = answer(value, UNREAD)?;
    if page.get("entries").is_some_and(Value::is_array) {
        Ok(page)
    } else {
        Err(UNREAD.into())
    }
}

/// What `earlier` refuses with when the program answered with anything but a listing.
const UNLISTED: &str = "Couldn't list this computer's agent sessions.";

/// Every agent CLI's earlier sessions here, with their titles, as
/// `mycelium machine sessions` lists them.
pub fn earlier() -> Result<Value, String> {
    let bin = paths::resolve("mycelium").ok_or("The mycelium program isn't available.")?;
    let out = paths::command(bin)
        .args(["machine", "sessions", "--json"])
        .env("PATH", paths::shell_path())
        .output()
        .map_err(|e| e.to_string())?;
    listing(&out.stdout)
}

/// The program's listing, or why there's none: what it printed wasn't one.
fn listing(stdout: &[u8]) -> Result<Value, String> {
    match serde_json::from_slice::<Value>(stdout) {
        Ok(value) if value.is_array() || value.is_object() => Ok(value),
        _ => Err(UNLISTED.into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_listing_reaches_the_page_as_the_program_printed_it() {
        let got = listing(br#"[{"id": "s1", "folder": "/work/api", "title": "Fix the refund"}]"#);
        assert_eq!(got.unwrap()[0]["title"], "Fix the refund");
    }

    #[test]
    fn anything_but_a_listing_says_it_couldnt_list_them() {
        for bad in [&b""[..], b"Traceback (most recent call last):", b"3", br#""no""#] {
            assert_eq!(listing(bad).unwrap_err(), UNLISTED);
        }
    }

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

    #[test]
    fn an_earlier_page_runs_the_program_only_with_what_was_checked() {
        let home = Home::new("page-args");
        let id = "3f2a9c1e-7b44-4d0a-9e1f-2c8b5a6d7e90";
        assert_eq!(
            page_args(&home.0, "checkout", "builder", id, 200).unwrap(),
            [
                "machine",
                "session",
                "--room=checkout",
                &format!("--before={id}"),
                "--limit=200",
                "--json",
                "--",
                "builder",
            ]
        );
        // A call's or a reply's own id pages back as well as a line's uuid.
        for ok in ["toolu_01AbC", "msg_01XyZ"] {
            assert!(page_args(&home.0, "checkout", "builder", ok, 200).is_ok(), "{ok}");
        }
        // Not this machine's agent: nothing runs.
        assert_eq!(page_args(&home.0, "storefront", "builder", id, 200).unwrap_err(), terminal::NOT_HERE);
        // An entry id can't carry an option, a path or anything else.
        for bad in ["", "--help", "-x", "a b", "a;b", "../x", &"a".repeat(65)] {
            assert_eq!(page_args(&home.0, "checkout", "builder", bad, 200).unwrap_err(), NO_ENTRY, "{bad}");
        }
        assert!(page_args(&home.0, "checkout", "builder", id, 0).is_err());
        assert!(page_args(&home.0, "checkout", "builder", id, PAGE_MAX + 1).is_err());
    }

    #[test]
    fn an_earlier_page_is_the_program_s_answer_or_why_not() {
        let page = page_answer(br#"{"entries": [{"sessionUpdate": "plan"}], "earlier": true}"#).unwrap();
        assert_eq!(page["earlier"], true);
        assert_eq!(page_answer(br#"{"unavailable": "no_entry"}"#).unwrap_err(), NO_ENTRY);
        assert_eq!(page_answer(br#"{"unavailable": "no_converter"}"#).unwrap_err(), NO_CONVERTER);
        assert_eq!(page_answer(br#"{"unavailable": "no_session"}"#).unwrap_err(), NO_SESSION);
        // A crash, or JSON that isn't a page.
        for bad in [&b""[..], b"Traceback (most recent call last):", b"{}", br#"{"entries": 3}"#] {
            assert_eq!(page_answer(bad).unwrap_err(), "Couldn't read that part of the session.");
        }
    }
}
