// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Whether an address someone enters to join a team's hub is a Mycelium hub.
//!
//! Anything can answer at an address: another web app, the hub's site behind
//! a path, a server that isn't Mycelium at all. Taken unchecked, the app would
//! send everything to it, and the first thing to fail would be the name screen
//! with that program's "Not Found". So the address is asked for its health,
//! and counts only when it says it is `mycelium-backend` (as
//! `mycelium.hubs.health` asks a hub on this machine). A hub that serves its
//! own pages answers `/health` with its web app and its health at
//! `/api/health`, so both are asked, as the app's sign-in route does.

use std::time::Duration;

use serde_json::Value;

use crate::download;

/// How long the hub has to answer each question.
const TIMEOUT: Duration = Duration::from_secs(10);

/// Where a hub says how it is: on its own, and behind the pages it serves.
const HEALTH_PATHS: [&str; 2] = ["/health", "/api/health"];

/// Why `url` isn't a hub to join, or `None` when a Mycelium hub answers there.
pub async fn problem(url: &str, machine: &str) -> Option<String> {
    let base = url.trim().trim_end_matches('/');
    let client = match download::client(None, false) {
        Ok(client) => client,
        Err(e) => return Some(format!("Couldn't check the address: {e}")),
    };
    let mut answers = Vec::new();
    for path in HEALTH_PATHS {
        let Ok(resp) = client.get(format!("{base}{path}")).timeout(TIMEOUT).send().await else {
            continue;
        };
        let status = resp.status().as_u16();
        let body = resp.bytes().await.unwrap_or_default().to_vec();
        let hub = is_hub(status, &body);
        answers.push((status, body));
        if hub {
            break;
        }
    }
    verdict(base, machine, &answers)
}

/// Whether one health answer is a Mycelium hub's.
fn is_hub(status: u16, body: &[u8]) -> bool {
    let service = serde_json::from_slice::<Value>(body)
        .ok()
        .and_then(|v| v.get("service").and_then(Value::as_str).map(str::to_string));
    status == 200 && service.as_deref() == Some("mycelium-backend")
}

/// What the health answers from `base` (status and body, one per path that
/// answered at all) say about it.
fn verdict(base: &str, machine: &str, answers: &[(u16, Vec<u8>)]) -> Option<String> {
    if answers.iter().any(|(status, body)| is_hub(*status, body)) {
        return None;
    }
    if answers.is_empty() {
        return Some(format!(
            "Nothing answered at {base}. Check the address, and that this {machine} can reach it."
        ));
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
    const HUB: &[u8] = br#"{"status":"ok","service":"mycelium-backend","version":"3.0.79"}"#;

    fn says(answers: &[(u16, &[u8])]) -> Option<String> {
        let answers: Vec<(u16, Vec<u8>)> = answers.iter().map(|(s, b)| (*s, b.to_vec())).collect();
        verdict(AT, "computer", &answers)
    }

    #[test]
    fn a_hub_says_so() {
        assert_eq!(says(&[(200, HUB)]), None);
    }

    #[test]
    fn a_hub_that_serves_its_own_pages_says_so_under_api() {
        assert_eq!(says(&[(404, b"<html>Not Found</html>"), (200, HUB)]), None);
    }

    #[test]
    fn a_program_that_answers_not_found_is_no_hub() {
        let said = says(&[(404, br#"{"detail":"Not Found"}"#), (404, br#"{"detail":"Not Found"}"#)]).unwrap();
        assert!(said.starts_with("That address isn't a Mycelium hub"));
        assert!(said.contains(AT));
    }

    #[test]
    fn something_healthy_that_isn_t_mycelium_is_no_hub() {
        assert!(says(&[(200, br#"{"status":"ok","service":"billing"}"#)]).is_some());
        assert!(says(&[(200, b"<html>ok</html>")]).is_some());
    }

    #[test]
    fn a_hub_that_is_failing_is_no_hub_to_join_yet() {
        assert!(says(&[(503, br#"{"service":"mycelium-backend"}"#)]).is_some());
    }

    #[test]
    fn nothing_answering_says_so() {
        let said = says(&[]).unwrap();
        assert!(said.starts_with("Nothing answered at"));
        assert!(said.contains("this computer"));
    }
}
