// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! `~/.mycelium/desktop.json`: whether this Mac runs a hub or joins one.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::paths::home;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    Hub,
    Client,
}

impl Mode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Mode::Hub => "hub",
            Mode::Client => "client",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    pub mode: Mode,
    #[serde(default)]
    pub hub_url: Option<String>,
    #[serde(default)]
    pub roots: Vec<String>,
    /// Whether a hub on this Mac shares its anonymous usage stats. Off unless
    /// asked for on the first-run screen, and meaningless in client mode,
    /// where the hub is someone else's.
    #[serde(default)]
    pub share_usage: bool,
    /// Whether a hub on this Mac transcribes the message box's mic. Off unless
    /// turned on in first run or Settings: the model costs ~150 MB on disk and
    /// ~500 MB of memory while anyone is talking. Meaningless in client mode.
    #[serde(default)]
    pub voice: bool,
}

impl Settings {
    /// A settings value the app can start from, or why not.
    pub fn validate(mut self) -> Result<Settings, String> {
        self.roots = self
            .roots
            .into_iter()
            .map(|r| expand_home(r.trim()))
            .filter(|r| !r.is_empty())
            .collect();
        if self.roots.is_empty() {
            self.roots.push(home().to_string_lossy().to_string());
        }
        match self.mode {
            Mode::Hub => {
                self.hub_url = None;
            }
            Mode::Client => {
                let url = self.hub_url.as_deref().map(str::trim).unwrap_or("");
                let parsed = url::Url::parse(url).map_err(|_| {
                    "Enter the hub's address, for example https://hub.example.com".to_string()
                })?;
                if !matches!(parsed.scheme(), "http" | "https") {
                    return Err("The hub's address has to start with http:// or https://".into());
                }
                self.hub_url = Some(url.trim_end_matches('/').to_string());
            }
        }
        Ok(self)
    }
}

fn expand_home(path: &str) -> String {
    if path == "~" {
        return home().to_string_lossy().to_string();
    }
    // `~\` too: a Windows folder the first-run page shortened before 3.0.31.
    match path.strip_prefix("~/").or_else(|| path.strip_prefix("~\\")) {
        Some(rest) => home().join(rest).to_string_lossy().to_string(),
        None => path.to_string(),
    }
}

/// `~/.mycelium/desktop.json`, or `$MYCELIUM_DESKTOP_SETTINGS` for trying the
/// app against a different setup without touching the real one.
pub fn file() -> PathBuf {
    std::env::var_os("MYCELIUM_DESKTOP_SETTINGS")
        .map(PathBuf::from)
        .unwrap_or_else(|| home().join(".mycelium").join("desktop.json"))
}

pub fn load() -> Option<Settings> {
    let text = std::fs::read_to_string(file()).ok()?;
    serde_json::from_str(&text).ok()
}

pub fn save(settings: &Settings) -> Result<(), String> {
    let path = file();
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    std::fs::write(path, text + "\n").map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_client_needs_a_real_hub_address() {
        let bad = Settings {
            mode: Mode::Client,
            hub_url: Some("hub".into()),
            roots: vec![],
            share_usage: false,
            voice: false,
        };
        assert!(bad.validate().is_err());
        let ok = Settings {
            mode: Mode::Client,
            hub_url: Some(" https://hub.example.com/ ".into()),
            roots: vec!["~/code".into()],
            share_usage: false,
            voice: false,
        }
        .validate()
        .unwrap();
        assert_eq!(ok.hub_url.as_deref(), Some("https://hub.example.com"));
        assert!(ok.roots[0].ends_with("/code") && !ok.roots[0].starts_with('~'));
    }

    #[test]
    fn a_hub_keeps_no_hub_address_and_always_has_a_folder() {
        let s = Settings {
            mode: Mode::Hub,
            hub_url: Some("x".into()),
            roots: vec![" ".into()],
            share_usage: true,
            voice: true,
        }
        .validate()
        .unwrap();
        assert_eq!(s.hub_url, None);
        assert_eq!(s.roots.len(), 1);
    }

    #[test]
    fn settings_saved_before_usage_stats_existed_read_as_not_sharing() {
        let old: Settings = serde_json::from_str(r#"{"mode":"hub","roots":["/tmp"]}"#).unwrap();
        assert!(!old.share_usage);
        let saved = serde_json::to_string(&old).unwrap();
        assert!(saved.contains("\"shareUsage\":false"));
    }

    #[test]
    fn settings_saved_before_voice_existed_read_as_voice_off() {
        let old: Settings = serde_json::from_str(r#"{"mode":"hub","roots":["/tmp"]}"#).unwrap();
        assert!(!old.voice);
        assert!(serde_json::to_string(&old).unwrap().contains("\"voice\":false"));
    }
}
