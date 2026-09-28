// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Finding the programs the app runs, and putting them where agents find them.
//!
//! A bundled app ships `mycelium` and `herdr` beside its own executable. In
//! development they are whatever is installed. Either way, the agents that
//! herdr starts run `mycelium` commands from a shell, so both have to be on
//! the user's PATH, not just the app's.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

use serde::Serialize;

pub fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}

pub fn local_bin() -> PathBuf {
    home().join(".local").join("bin")
}

/// The PATH a login shell gets. A GUI app on macOS starts with a bare PATH,
/// which would hide herdr and the agent CLIs from everything it starts.
pub fn shell_path() -> &'static str {
    static PATH: OnceLock<String> = OnceLock::new();
    PATH.get_or_init(|| {
        let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".into());
        let from_shell = Command::new(shell)
            .args(["-lc", "printf %s \"$PATH\""])
            .output()
            .ok()
            .filter(|o| o.status.success())
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .filter(|p| !p.is_empty());
        let base = from_shell
            .or_else(|| std::env::var("PATH").ok())
            .unwrap_or_else(|| "/usr/bin:/bin:/usr/sbin:/sbin".into());
        let local = local_bin().to_string_lossy().to_string();
        if base.split(':').any(|p| p == local) {
            base
        } else {
            format!("{local}:{base}")
        }
    })
}

/// Whether the user's own login shell has ~/.local/bin on its PATH (before
/// this app adds it for the processes it starts).
pub fn local_bin_on_user_path() -> bool {
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".into());
    let local = local_bin().to_string_lossy().to_string();
    Command::new(shell)
        .args(["-lc", "printf %s \"$PATH\""])
        .output()
        .ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).split(':').any(|p| p == local))
        .unwrap_or(false)
}

/// A program shipped inside the app bundle, beside the app's executable.
pub fn bundled(name: &str) -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let candidate = exe.parent()?.join(name);
    candidate.is_file().then_some(candidate)
}

fn on_path(name: &str) -> Option<PathBuf> {
    std::iter::once(local_bin())
        .chain(shell_path().split(':').map(PathBuf::from))
        .map(|dir| dir.join(name))
        .find(|p| p.is_file())
}

/// Where a program is: the bundled copy first, else the installed one.
pub fn resolve(name: &str) -> Option<PathBuf> {
    bundled(name).or_else(|| on_path(name))
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Found {
    pub name: String,
    pub path: Option<String>,
    pub bundled: bool,
}

pub fn found(name: &str) -> Found {
    let bundled_path = bundled(name);
    let path = bundled_path.clone().or_else(|| on_path(name));
    Found {
        name: name.into(),
        path: path.map(|p| p.to_string_lossy().to_string()),
        bundled: bundled_path.is_some(),
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PathSetup {
    /// Programs now linked into ~/.local/bin.
    pub linked: Vec<String>,
    /// Programs left alone because a file that isn't ours is already there.
    pub skipped: Vec<String>,
    /// Whether the user's shell will find ~/.local/bin.
    pub on_path: bool,
    /// The line to add to the shell profile when it won't.
    pub line: String,
}

/// Link the bundled `mycelium` and `herdr` into ~/.local/bin.
///
/// Only a symlink is ever replaced: a real file there is the user's own
/// install and is left alone. In development nothing is bundled, so there is
/// nothing to link and the installed copies are used as they are.
pub fn link_bundled() -> PathSetup {
    let dir = local_bin();
    let mut linked = Vec::new();
    let mut skipped = Vec::new();
    for name in ["mycelium", "herdr"] {
        let Some(source) = bundled(name) else { continue };
        let _ = std::fs::create_dir_all(&dir);
        let target = dir.join(name);
        match std::fs::symlink_metadata(&target) {
            Ok(meta) if !meta.file_type().is_symlink() => {
                skipped.push(name.to_string());
                continue;
            }
            Ok(_) => {
                let _ = std::fs::remove_file(&target);
            }
            Err(_) => {}
        }
        if symlink(&source, &target).is_ok() {
            linked.push(name.to_string());
        } else {
            skipped.push(name.to_string());
        }
    }
    PathSetup {
        linked,
        skipped,
        on_path: local_bin_on_user_path(),
        line: "export PATH=\"$HOME/.local/bin:$PATH\"".into(),
    }
}

#[cfg(unix)]
fn symlink(source: &Path, target: &Path) -> std::io::Result<()> {
    std::os::unix::fs::symlink(source, target)
}

#[cfg(not(unix))]
fn symlink(source: &Path, target: &Path) -> std::io::Result<()> {
    std::fs::copy(source, target).map(|_| ())
}
