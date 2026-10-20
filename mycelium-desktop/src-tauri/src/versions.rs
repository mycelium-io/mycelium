// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Which version of the app to run: the releases you can switch to, and the
//! channel the updater follows.
//!
//! Every release, release candidates included, publishes its own
//! `latest.json` beside its assets, naming its version and its signed archive.
//! Switching to one points the updater at that release's `latest.json`, and the
//! download is checked against the key built into this app like any update
//! (`updates.rs`). The bundled hub and CLI come with the app, so they change
//! with it.
//!
//! The channel is `stable` (the normal path: `releases/latest`, which GitHub
//! keeps on the newest stable release) or `rc`, which also offers the newest
//! release candidate. It's kept in `~/.mycelium/desktop-updates.json`.

use std::path::PathBuf;

use serde::Serialize;
use tauri::Url;

use crate::paths::home;

const REPO: &str = "mycelium-io/mycelium";
/// The releases GitHub lists, newest first; enough to go back a while.
const RELEASES_API: &str = "https://api.github.com/repos/mycelium-io/mycelium/releases?per_page=40";

/// A release the app can switch to.
#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Release {
    /// The release's tag, which names its `latest.json`.
    pub tag: String,
    /// The app's version in it, as the updater compares them (`3.0.55-rc1`).
    pub version: String,
    pub prerelease: bool,
    /// When it was published, as GitHub says (RFC 3339).
    pub published: String,
}

/// The version an app built from `tag` reports: Tauri's semver, so a PEP 440
/// release candidate (`v3.0.55rc1`) becomes `3.0.55-rc1`, as the release build
/// writes it (`desktop.yml`).
pub fn version_of(tag: &str) -> Option<String> {
    let bare = tag.strip_prefix('v')?;
    let split = bare.find(|c: char| c.is_ascii_alphabetic());
    let text = match split {
        Some(i) => format!("{}-{}", bare[..i].trim_end_matches('.'), &bare[i..]),
        None => bare.to_string(),
    };
    semver::Version::parse(&text).ok().map(|_| text)
}

/// A tag as releases are tagged (`v3.0.55`, `v3.0.55rc1`): nothing else is
/// put into a download address.
pub fn is_tag(tag: &str) -> bool {
    tag.len() <= 32
        && tag.starts_with('v')
        && tag[1..].chars().all(|c| c.is_ascii_alphanumeric() || c == '.')
        && version_of(tag).is_some()
}

/// Where a release's own `latest.json` is.
pub fn manifest(tag: &str) -> Result<Url, String> {
    if !is_tag(tag) {
        return Err(format!("{tag} isn't a release"));
    }
    Url::parse(&format!("https://github.com/{REPO}/releases/download/{tag}/latest.json"))
        .map_err(|e| e.to_string())
}

/// The releases that carry a `latest.json`, newest version first; release
/// candidates only with `with_rc`.
pub async fn releases(with_rc: bool) -> Result<Vec<Release>, String> {
    let client = crate::download::client(None, false)?;
    let reply = client
        .get(RELEASES_API)
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|e| format!("couldn't reach GitHub: {e}"))?;
    if !reply.status().is_success() {
        return Err(format!("GitHub answered {}", reply.status()));
    }
    let body: serde_json::Value = reply.json().await.map_err(|e| e.to_string())?;
    Ok(parse(&body, with_rc))
}

fn parse(body: &serde_json::Value, with_rc: bool) -> Vec<Release> {
    let mut found: Vec<Release> = body
        .as_array()
        .map(|list| {
            list.iter()
                .filter(|r| !r.get("draft").and_then(serde_json::Value::as_bool).unwrap_or(false))
                .filter(|r| {
                    r.get("assets").and_then(serde_json::Value::as_array).is_some_and(|assets| {
                        assets.iter().any(|a| a.get("name").and_then(serde_json::Value::as_str) == Some("latest.json"))
                    })
                })
                .filter_map(|r| {
                    let tag = r.get("tag_name")?.as_str()?.to_string();
                    let version = version_of(&tag)?;
                    Some(Release {
                        prerelease: r.get("prerelease").and_then(serde_json::Value::as_bool).unwrap_or(false),
                        published: r.get("published_at").and_then(serde_json::Value::as_str).unwrap_or("").into(),
                        tag,
                        version,
                    })
                })
                .filter(|r| with_rc || !r.prerelease)
                .collect()
        })
        .unwrap_or_default();
    found.sort_by_key(|r| std::cmp::Reverse(semver_of(&r.version)));
    found
}

pub fn semver_of(version: &str) -> semver::Version {
    semver::Version::parse(version).unwrap_or_else(|_| semver::Version::new(0, 0, 0))
}

/// Which releases the updater offers.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Channel {
    Stable,
    ReleaseCandidates,
}

fn file() -> PathBuf {
    home().join(".mycelium").join("desktop-updates.json")
}

/// The channel chosen in Settings; stable when nothing was.
pub fn channel() -> Channel {
    let rc = std::fs::read_to_string(file())
        .ok()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
        .and_then(|v| v.get("channel").and_then(serde_json::Value::as_str).map(|c| c == "rc"))
        .unwrap_or(false);
    if rc {
        Channel::ReleaseCandidates
    } else {
        Channel::Stable
    }
}

pub fn set_channel(channel: Channel) -> Result<(), String> {
    let path = file();
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let name = match channel {
        Channel::Stable => "stable",
        Channel::ReleaseCandidates => "rc",
    };
    std::fs::write(&path, format!("{{\"channel\": \"{name}\"}}\n")).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_release_candidate_tag_reads_as_the_version_its_app_reports() {
        assert_eq!(version_of("v3.0.55rc1").as_deref(), Some("3.0.55-rc1"));
        assert_eq!(version_of("v3.0.54").as_deref(), Some("3.0.54"));
        assert_eq!(version_of("3.0.54"), None);
        assert_eq!(version_of("vnext"), None);
        // An RC comes before its release, and after the one before it.
        assert!(semver_of("3.0.55-rc1") < semver_of("3.0.55"));
        assert!(semver_of("3.0.55-rc1") > semver_of("3.0.54"));
    }

    #[test]
    fn only_a_release_tag_goes_into_a_download_address() {
        assert!(manifest("v3.0.55rc1").unwrap().as_str().ends_with("/releases/download/v3.0.55rc1/latest.json"));
        for bad in ["", "v3.0.55/../x", "v3.0.55?x=1", "3.0.55", "v3.0.55 rc1"] {
            assert!(manifest(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn the_list_is_releases_with_an_update_newest_first_rcs_on_request() {
        let body = json!([
            {"tag_name": "v3.0.54", "prerelease": false, "draft": false, "published_at": "2026-10-20T00:06:41Z",
             "assets": [{"name": "latest.json"}]},
            {"tag_name": "v3.0.55rc1", "prerelease": true, "draft": false, "published_at": "2026-10-20T10:00:00Z",
             "assets": [{"name": "latest.json"}]},
            {"tag_name": "v3.0.53", "prerelease": false, "draft": false, "assets": [{"name": "notes.txt"}]},
            {"tag_name": "v3.0.56", "prerelease": false, "draft": true, "assets": [{"name": "latest.json"}]}
        ]);
        let stable = parse(&body, false);
        assert_eq!(stable.iter().map(|r| r.tag.as_str()).collect::<Vec<_>>(), ["v3.0.54"]);
        let all = parse(&body, true);
        assert_eq!(all.iter().map(|r| r.tag.as_str()).collect::<Vec<_>>(), ["v3.0.55rc1", "v3.0.54"]);
        assert!(all[0].prerelease);
    }
}
