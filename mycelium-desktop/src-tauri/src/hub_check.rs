// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Whether an address someone enters to join a team's hub is a Mycelium hub.
//!
//! Anything can answer at an address: another web app, the hub's site behind
//! a path, a server that isn't Mycelium at all. Taken unchecked, the app would
//! send everything to it, and the first thing to fail would be the name screen
//! with that program's "Not Found". So the address is asked for `/health`, and
//! counts only when it says it is `mycelium-backend` (as `mycelium.hubs.health`
//! asks a hub on this machine).

use std::time::Duration;

use serde_json::Value;

use crate::download;

/// How long the hub has to answer.
const TIMEOUT: Duration = Duration::from_secs(10);

/// Why `url` isn't a hub to join, or `None` when a Mycelium hub answers there.
pub async fn problem(url: &str, machine: &str) -> Option<String> {
    let base = url.trim().trim_end_matches('/');
    let client = match download::client(None, false) {
        Ok(client) => client,
        Err(e) => return Some(format!("Couldn't check the address: {e}")),
    };
    let answer = client.get(format!("{base}/health")).timeout(TIMEOUT).send().await;
    let Ok(resp) = answer else {
        return Some(format!(
            "Nothing answered at {base}. Check the address, and that this {machine} can reach it."
        ));
    };
    let status = resp.status().as_u16();
    let body = resp.bytes().await.unwrap_or_default();
    verdict(base, status, &body)
}

/// What `/health` at `base` answering `status` with `body` says about it.
fn verdict(base: &str, status: u16, body: &[u8]) -> Option<String> {
    let service = serde_json::from_slice::<Value>(body)
        .ok()
        .and_then(|v| v.get("service").and_then(Value::as_str).map(str::to_string));
    if status == 200 && service.as_deref() == Some("mycelium-backend") {
        return None;
    }
    Some(format!(
        "That address isn't a Mycelium hub: something answers at {base}, but not as a hub. \
         Use the hub's own address, with nothing after it."
    ))
}

#[cfg(test)]
mod tests {
    use super::verdict;

    const AT: &str = "https://hub.example.com";

    #[test]
    fn a_hub_says_so() {
        let body = br#"{"status":"ok","service":"mycelium-backend","version":"3.0.79"}"#;
        assert_eq!(verdict(AT, 200, body), None);
    }

    #[test]
    fn a_program_that_answers_not_found_is_no_hub() {
        let said = verdict(AT, 404, br#"{"detail":"Not Found"}"#).unwrap();
        assert!(said.starts_with("That address isn't a Mycelium hub"));
        assert!(said.contains(AT));
    }

    #[test]
    fn something_healthy_that_isn_t_mycelium_is_no_hub() {
        assert!(verdict(AT, 200, br#"{"status":"ok","service":"billing"}"#).is_some());
        assert!(verdict(AT, 200, b"<html>ok</html>").is_some());
    }

    #[test]
    fn a_hub_that_is_failing_is_no_hub_to_join_yet() {
        let body = br#"{"service":"mycelium-backend"}"#;
        assert!(verdict(AT, 503, body).is_some());
    }
}
