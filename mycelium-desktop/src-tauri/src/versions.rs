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
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use tauri::Url;

use crate::paths::home;

const REPO: &str = "mycelium-io/mycelium";
/// The releases GitHub lists, newest first; enough to go back a while. Asked
/// without a token, so GitHub allows 60 an hour from one network address, and
/// an office network shares that between everyone on it.
const RELEASES_API: &str = "https://api.github.com/repos/mycelium-io/mycelium/releases?per_page=40";
/// The same releases as a feed, which isn't counted against that limit: the
/// newest ten, with no word on which carry a `latest.json` or are previews.
const RELEASES_FEED: &str = "https://github.com/mycelium-io/mycelium/releases.atom";
/// The first release that published a `latest.json`; the feed lists only from here.
const FIRST_WITH_MANIFEST: &str = "3.0.9";
/// How long a list read from GitHub is used again before asking it again.
const FRESH_FOR: Duration = Duration::from_secs(10 * 60);

/// A release the app can switch to.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
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

/// Whether the release tagged `tag` published its `latest.json`. A release
/// whose build didn't finish has none, and the feed can't say which those are.
/// A download address, so not counted against the API's limit.
pub async fn has_manifest(tag: &str) -> Result<bool, String> {
    let reply = crate::download::client(None, false)?
        .head(manifest(tag)?)
        .send()
        .await
        .map_err(|_| Unreachable::Offline.sentence())?;
    match reply.status().as_u16() {
        200..=299 => Ok(true),
        404 => Ok(false),
        _ => Err("GitHub didn't answer about that release just now. Try again in a few minutes.".into()),
    }
}

/// Why a release can't be switched to when it has no `latest.json`.
pub fn no_update(tag: &str) -> String {
    format!(
        "{} has no update to install: its build didn't finish. Pick another release.",
        tag.trim_start_matches('v')
    )
}

/// The releases Settings lists, and a line about them when they aren't GitHub's
/// answer just now (a saved list, because GitHub couldn't be asked).
#[derive(Debug, PartialEq)]
pub struct Listed {
    pub releases: Vec<Release>,
    pub note: Option<String>,
}

/// Why GitHub's list couldn't be read, said the way a person can act on it.
#[derive(Debug, Clone, PartialEq)]
enum Unreachable {
    /// GitHub's hourly limit for this network is used up; minutes until it resets, when it said.
    Limited(Option<u64>),
    /// No connection to GitHub at all.
    Offline,
    /// GitHub answered, but not with the list.
    Refused,
}

impl Unreachable {
    fn sentence(&self) -> String {
        match self {
            Self::Limited(minutes) => {
                let when = match minutes {
                    Some(1) => "in a minute".to_string(),
                    Some(n) => format!("in {n} minutes"),
                    None => "in a few minutes".to_string(),
                };
                format!(
                    "GitHub limits how often the list of releases can be read from one network, and yours has used it up. Try again {when}."
                )
            }
            Self::Offline => "Couldn't reach GitHub to list releases. Check your connection and try again.".into(),
            Self::Refused => "GitHub didn't send the list of releases just now. Try again in a few minutes.".into(),
        }
    }
}

/// What a refusal from GitHub means: its rate limit (a 403 or 429 with no
/// requests left, or a `Retry-After`), or something else. `now` is Unix seconds.
fn refusal(status: u16, remaining: Option<&str>, reset: Option<&str>, retry_after: Option<&str>, now: u64) -> Unreachable {
    let limited = (status == 403 || status == 429) && (remaining == Some("0") || retry_after.is_some());
    if !limited {
        return Unreachable::Refused;
    }
    let wait = retry_after
        .and_then(|s| s.trim().parse::<u64>().ok())
        .or_else(|| reset.and_then(|s| s.trim().parse::<u64>().ok()).map(|at| at.saturating_sub(now)));
    Unreachable::Limited(wait.map(|secs| secs.div_ceil(60).max(1)))
}

/// The list read last, in this run of the app, and when.
static LAST: Mutex<Option<(Instant, Vec<Release>)>> = Mutex::new(None);

/// The releases that carry a `latest.json`, newest version first; release
/// candidates only with `with_rc`.
///
/// Read from GitHub's API at most every few minutes. When it can't be read,
/// from the releases feed (which isn't rate limited), added to the list kept
/// from last time; when neither answers, the kept list, saying so.
pub async fn releases(with_rc: bool) -> Result<Listed, String> {
    let fresh = LAST
        .lock()
        .ok()
        .and_then(|last| last.as_ref().filter(|(at, _)| at.elapsed() < FRESH_FOR).map(|(_, list)| list.clone()));
    let all = match fresh {
        Some(list) => Listed { releases: list, note: None },
        None => {
            let client = crate::download::client(None, false)?;
            let api = from_api(&client).await;
            let feed = if api.is_err() { from_feed(&client).await } else { None };
            let listed = choose(api, feed, load_saved(), unix_now())?;
            if listed.note.is_none() {
                save(&listed.releases);
                if let Ok(mut last) = LAST.lock() {
                    *last = Some((Instant::now(), listed.releases.clone()));
                }
            }
            listed
        }
    };
    Ok(Listed {
        releases: all.releases.into_iter().filter(|r| with_rc || !r.prerelease).collect(),
        note: all.note,
    })
}

async fn from_api(client: &reqwest::Client) -> Result<Vec<Release>, Unreachable> {
    let reply = client
        .get(RELEASES_API)
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|_| Unreachable::Offline)?;
    if !reply.status().is_success() {
        let header = |name: &str| reply.headers().get(name).and_then(|v| v.to_str().ok());
        return Err(refusal(
            reply.status().as_u16(),
            header("x-ratelimit-remaining"),
            header("x-ratelimit-reset"),
            header("retry-after"),
            unix_now(),
        ));
    }
    let body: serde_json::Value = reply.json().await.map_err(|_| Unreachable::Refused)?;
    Ok(parse(&body, true))
}

async fn from_feed(client: &reqwest::Client) -> Option<Vec<Release>> {
    let reply = client.get(RELEASES_FEED).send().await.ok()?;
    if !reply.status().is_success() {
        return None;
    }
    let list = parse_feed(&reply.text().await.ok()?);
    (!list.is_empty()).then_some(list)
}

/// Which list to show, from what each source gave: the API's when it answered;
/// else the feed's, with any older releases kept from last time; else what was
/// kept, saying why it's that; else why there's nothing.
fn choose(
    api: Result<Vec<Release>, Unreachable>,
    feed: Option<Vec<Release>>,
    saved: Option<Saved>,
    now: u64,
) -> Result<Listed, String> {
    let why = match api {
        Ok(releases) => return Ok(Listed { releases, note: None }),
        Err(why) => why,
    };
    if let Some(feed) = feed {
        return Ok(Listed { releases: merge(feed, saved.map(|s| s.releases).unwrap_or_default()), note: None });
    }
    match saved {
        Some(saved) if !saved.releases.is_empty() => Ok(Listed {
            note: Some(format!("{} Showing the list from {}.", why.sentence(), ago(now.saturating_sub(saved.at)))),
            releases: saved.releases,
        }),
        _ => Err(why.sentence()),
    }
}

/// The feed's releases with the kept ones it doesn't name (older than its ten), newest first.
fn merge(feed: Vec<Release>, kept: Vec<Release>) -> Vec<Release> {
    let mut all = feed;
    for r in kept {
        if !all.iter().any(|f| f.tag == r.tag) {
            all.push(r);
        }
    }
    all.sort_by_key(|r| std::cmp::Reverse(semver_of(&r.version)));
    all
}

/// The releases in GitHub's Atom feed: each entry's tag, from its link, and
/// when it was published. A preview is told by its tag (`v3.0.55rc1`), as the
/// release workflow tells it.
fn parse_feed(xml: &str) -> Vec<Release> {
    let floor = semver_of(FIRST_WITH_MANIFEST);
    let mut found: Vec<Release> = xml
        .split("<entry>")
        .skip(1)
        .filter_map(|entry| {
            let after = entry.split("/releases/tag/").nth(1)?;
            let tag = after.split('"').next()?.to_string();
            if !is_tag(&tag) {
                return None;
            }
            let version = version_of(&tag)?;
            if semver_of(&version) < floor {
                return None;
            }
            let published = entry
                .split("<updated>")
                .nth(1)
                .and_then(|s| s.split("</updated>").next())
                .unwrap_or("")
                .to_string();
            Some(Release { prerelease: version.contains('-'), published, tag, version })
        })
        .collect();
    found.sort_by_key(|r| std::cmp::Reverse(semver_of(&r.version)));
    found
}

/// The last list read from GitHub, kept on disk for when it can't be asked.
#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Saved {
    /// When it was read, in Unix seconds.
    at: u64,
    releases: Vec<Release>,
}

fn saved_file() -> PathBuf {
    home().join(".mycelium").join("desktop-releases.json")
}

fn load_saved() -> Option<Saved> {
    serde_json::from_str(&std::fs::read_to_string(saved_file()).ok()?).ok()
}

fn save(releases: &[Release]) {
    let path = saved_file();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let saved = Saved { at: unix_now(), releases: releases.to_vec() };
    // Keeping it is a convenience: the list still shows without it.
    if let Ok(text) = serde_json::to_string(&saved) {
        let _ = std::fs::write(path, text);
    }
}

fn unix_now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// How long ago, in words: "a minute ago", "3 hours ago", "2 days ago".
fn ago(secs: u64) -> String {
    let (n, unit) = match secs {
        0..120 => return "a minute ago".into(),
        120..7_200 => (secs / 60, "minutes"),
        7_200..172_800 => (secs / 3_600, "hours"),
        _ => (secs / 86_400, "days"),
    };
    format!("{n} {unit} ago")
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

    fn release(tag: &str) -> Release {
        let version = version_of(tag).unwrap();
        Release { prerelease: version.contains('-'), published: String::new(), tag: tag.into(), version }
    }

    fn tags(list: &[Release]) -> Vec<&str> {
        list.iter().map(|r| r.tag.as_str()).collect()
    }

    #[test]
    fn a_403_with_no_requests_left_is_the_rate_limit_and_says_when_to_try_again() {
        let now = 1_000_000;
        let limited = refusal(403, Some("0"), Some(&(now + 540).to_string()), None, now);
        assert_eq!(limited, Unreachable::Limited(Some(9)));
        let said = limited.sentence();
        assert!(said.contains("Try again in 9 minutes"), "{said}");
        assert!(!said.contains("403"), "{said}");
        assert_eq!(refusal(429, None, None, Some("20"), now), Unreachable::Limited(Some(1)));
        assert_eq!(refusal(403, Some("0"), None, None, now), Unreachable::Limited(None));
        // A 403 with requests left, or a server error, isn't the limit.
        assert_eq!(refusal(403, Some("12"), None, None, now), Unreachable::Refused);
        assert_eq!(refusal(502, None, None, None, now), Unreachable::Refused);
    }

    #[test]
    fn the_feed_lists_releases_with_a_manifest_and_tells_previews_by_their_tag() {
        let xml = r#"<feed><title>Release notes</title>
            <entry><id>1</id><updated>2026-10-21T19:20:16Z</updated>
              <link rel="alternate" type="text/html" href="https://github.com/mycelium-io/mycelium/releases/tag/v3.0.55"/></entry>
            <entry><id>2</id><updated>2026-10-21T02:13:09Z</updated>
              <link rel="alternate" type="text/html" href="https://github.com/mycelium-io/mycelium/releases/tag/v3.0.55rc3"/></entry>
            <entry><id>3</id><updated>2026-01-01T00:00:00Z</updated>
              <link rel="alternate" type="text/html" href="https://github.com/mycelium-io/mycelium/releases/tag/v3.0.8"/></entry>
            <entry><id>4</id><link rel="alternate" href="https://github.com/mycelium-io/mycelium/releases/tag/nightly"/></entry>
            </feed>"#;
        let list = parse_feed(xml);
        assert_eq!(tags(&list), ["v3.0.55", "v3.0.55rc3"]);
        assert!(!list[0].prerelease && list[1].prerelease);
        assert_eq!(list[0].published, "2026-10-21T19:20:16Z");
    }

    #[test]
    fn rate_limited_with_the_feed_up_lists_the_feed_and_the_older_releases_kept() {
        let saved = Saved { at: 0, releases: vec![release("v3.0.54"), release("v3.0.20")] };
        let listed = choose(
            Err(Unreachable::Limited(Some(9))),
            Some(vec![release("v3.0.55"), release("v3.0.54")]),
            Some(saved),
            0,
        )
        .unwrap();
        assert_eq!(tags(&listed.releases), ["v3.0.55", "v3.0.54", "v3.0.20"]);
        assert_eq!(listed.note, None);
    }

    #[test]
    fn rate_limited_with_nothing_else_up_shows_the_kept_list_and_says_why() {
        let saved = Saved { at: 0, releases: vec![release("v3.0.54")] };
        let listed = choose(Err(Unreachable::Limited(Some(9))), None, Some(saved), 3 * 3_600).unwrap();
        assert_eq!(tags(&listed.releases), ["v3.0.54"]);
        let note = listed.note.unwrap();
        assert!(note.contains("Try again in 9 minutes") && note.ends_with("Showing the list from 3 hours ago."), "{note}");
    }

    #[test]
    fn with_no_network_and_nothing_kept_it_says_so_plainly() {
        let err = choose(Err(Unreachable::Offline), None, None, 0).unwrap_err();
        assert_eq!(err, "Couldn't reach GitHub to list releases. Check your connection and try again.");
        let err = choose(Err(Unreachable::Limited(None)), None, Some(Saved { at: 0, releases: vec![] }), 0).unwrap_err();
        assert!(err.ends_with("Try again in a few minutes."), "{err}");
    }

    #[test]
    fn the_api_answering_is_the_list_as_it_is() {
        let listed = choose(Ok(vec![release("v3.0.55")]), None, None, 0).unwrap();
        assert_eq!(listed, Listed { releases: vec![release("v3.0.55")], note: None });
    }

    #[test]
    fn a_release_with_no_update_says_so_by_its_version() {
        assert_eq!(
            no_update("v3.0.55rc1"),
            "3.0.55rc1 has no update to install: its build didn't finish. Pick another release."
        );
    }

    #[test]
    fn how_long_ago_reads_in_words() {
        assert_eq!(ago(30), "a minute ago");
        assert_eq!(ago(25 * 60), "25 minutes ago");
        assert_eq!(ago(5 * 3_600), "5 hours ago");
        assert_eq!(ago(3 * 86_400), "3 days ago");
    }
}
