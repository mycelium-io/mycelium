// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! What each agent on this machine uses, for the Agents pane.
//!
//! The runner here reads each agent's memory, CPU and processes from its herdr
//! pane every 30 seconds and writes them to `~/.mycelium/runner/usage.json`
//! (0600). This reads that file for the app's own pages. Like an agent's
//! screen and session, it never goes to the hub, and another hub's pages get
//! nothing: only this machine's agents have numbers, and only here.

use std::path::Path;

use serde_json::Value;

use crate::paths;

/// What the runner here last wrote, or `null` before it has written anything.
pub fn usage() -> Result<Value, String> {
    read(&paths::home().join(".mycelium"))
}

fn read(mycelium: &Path) -> Result<Value, String> {
    let file = mycelium.join("runner").join("usage.json");
    let Ok(raw) = std::fs::read_to_string(file) else { return Ok(Value::Null) };
    // Written whole and renamed into place, so a file that doesn't parse is
    // one that isn't the runner's: say there's nothing, never half of it.
    Ok(serde_json::from_str::<Value>(&raw).ok().filter(Value::is_object).unwrap_or(Value::Null))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_what_the_runner_wrote_and_nothing_else() {
        let dir = std::env::temp_dir().join(format!("mycelium-usage-{}", std::process::id()));
        let runner = dir.join("runner");
        std::fs::create_dir_all(&runner).unwrap();
        assert_eq!(read(&dir).unwrap(), Value::Null);

        std::fs::write(runner.join("usage.json"), r#"{"agents":[{"handle":"scout","ram_mb":700}]}"#)
            .unwrap();
        assert_eq!(read(&dir).unwrap()["agents"][0]["ram_mb"], 700);

        std::fs::write(runner.join("usage.json"), "not json").unwrap();
        assert_eq!(read(&dir).unwrap(), Value::Null);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
