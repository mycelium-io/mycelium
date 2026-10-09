// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

//! Finding the programs the app runs, and putting them where agents find them.
//!
//! A bundled app ships `mycelium` and `herdr` beside its own executable. In
//! development they are whatever is installed. Either way, the agents that
//! herdr starts run `mycelium` commands from a shell, so both have to be on
//! the user's PATH, not just the app's: on macOS and Linux they are linked
//! into ~/.local/bin; on Windows the app's own folder is put on the PATH of
//! everything it starts.

use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

use serde::Serialize;

pub fn home() -> PathBuf {
    std::env::home_dir().unwrap_or_else(|| PathBuf::from("/"))
}

/// A program to run in the background. On Windows it gets no console window,
/// which a windowed app would otherwise open for every console program it runs.
pub fn command(program: impl AsRef<OsStr>) -> Command {
    #[allow(unused_mut)]
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

/// A program's file name on this platform.
pub fn exe(name: &str) -> String {
    format!("{name}{}", std::env::consts::EXE_SUFFIX)
}

/// The shell to ask for a login PATH: the user's own, else the platform's.
#[cfg(unix)]
fn login_shell() -> String {
    let fallback = if cfg!(target_os = "macos") { "/bin/zsh" } else { "/bin/sh" };
    std::env::var("SHELL").unwrap_or_else(|_| fallback.into())
}

#[cfg(unix)]
fn login_path() -> Option<String> {
    login_shell_path()
}

#[cfg(unix)]
fn login_shell_path() -> Option<String> {
    command(login_shell())
        .args(["-lc", "printf %s \"$PATH\""])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .filter(|p| !p.is_empty())
}

/// Windows has no login shell: a GUI app starts with the user's PATH already.
#[cfg(windows)]
fn login_path() -> Option<String> {
    None
}

/// The folder the programs the app starts should find first: ~/.local/bin,
/// where macOS and Linux link them, or on Windows the app's own folder.
fn first_dir() -> PathBuf {
    #[cfg(windows)]
    if let Some(dir) = std::env::current_exe().ok().and_then(|e| e.parent().map(Path::to_path_buf)) {
        return dir;
    }
    local_bin()
}

pub fn local_bin() -> PathBuf {
    home().join(".local").join("bin")
}

/// The PATH a login shell gets. A GUI app on macOS starts with a bare PATH,
/// which would hide herdr and the agent CLIs from everything it starts.
pub fn shell_path() -> &'static str {
    static PATH: OnceLock<String> = OnceLock::new();
    PATH.get_or_init(|| {
        let base = login_path()
            .or_else(|| std::env::var("PATH").ok())
            .unwrap_or_else(|| "/usr/bin:/bin:/usr/sbin:/sbin".into());
        let first = first_dir();
        let mut dirs: Vec<PathBuf> = std::env::split_paths(&base).collect();
        if !dirs.contains(&first) {
            dirs.insert(0, first);
        }
        std::env::join_paths(dirs)
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or(base)
    })
}

/// Whether the user's own shell will find the bundled programs (before this
/// app adds their folder for the processes it starts).
#[cfg(unix)]
pub fn local_bin_on_user_path() -> bool {
    let first = first_dir();
    login_shell_path().is_some_and(|p| std::env::split_paths(&p).any(|d| d == first))
}

/// On Windows, whether the user's PATH (the registry's, not this process's)
/// has the app's folder.
#[cfg(windows)]
pub fn local_bin_on_user_path() -> bool {
    windows_path::has(&first_dir())
}

/// The user's own PATH on Windows: the `Path` value under HKCU\Environment,
/// which every terminal and program started from then on reads. Not the
/// app's process PATH, which was fixed when the app started.
#[cfg(windows)]
mod windows_path {
    use std::path::Path;

    use winreg::enums::{RegType, HKEY_CURRENT_USER, KEY_READ, KEY_WRITE};
    use winreg::{RegKey, RegValue};

    fn same(a: &str, b: &Path) -> bool {
        let b = b.to_string_lossy();
        a.trim().trim_end_matches('\\').eq_ignore_ascii_case(b.trim_end_matches('\\'))
    }

    fn read() -> Option<(String, RegType)> {
        let env = RegKey::predef(HKEY_CURRENT_USER).open_subkey("Environment").ok()?;
        let raw = env.get_raw_value("Path").ok()?;
        let value: String = env.get_value("Path").ok()?;
        Some((value, raw.vtype))
    }

    /// Whether `dir` is one of the entries of the user's PATH.
    pub fn has(dir: &Path) -> bool {
        read().is_some_and(|(value, _)| value.split(';').any(|entry| same(entry, dir)))
    }

    /// Add `dir` to the end of the user's PATH, keeping its type (most are
    /// REG_EXPAND_SZ, holding `%USERPROFILE%`-style entries that a REG_SZ
    /// would stop expanding), then tell running programs the environment
    /// changed, so a terminal opened from now on finds it.
    pub fn add(dir: &Path) -> std::io::Result<()> {
        if has(dir) {
            return Ok(());
        }
        let (env, _) =
            RegKey::predef(HKEY_CURRENT_USER).create_subkey_with_flags("Environment", KEY_READ | KEY_WRITE)?;
        let (current, vtype) = read().unwrap_or((String::new(), RegType::REG_EXPAND_SZ));
        let current = current.trim_end_matches(';');
        let value = if current.is_empty() {
            dir.to_string_lossy().to_string()
        } else {
            format!("{current};{}", dir.display())
        };
        let mut bytes: Vec<u8> = value.encode_utf16().chain(std::iter::once(0)).flat_map(u16::to_le_bytes).collect();
        bytes.shrink_to_fit();
        env.set_raw_value("Path", &RegValue { bytes: bytes.into(), vtype })?;
        broadcast();
        Ok(())
    }

    fn broadcast() {
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            SendMessageTimeoutW, HWND_BROADCAST, SMTO_ABORTIFHUNG, WM_SETTINGCHANGE,
        };
        let what: Vec<u16> = "Environment".encode_utf16().chain(std::iter::once(0)).collect();
        // SAFETY: `what` outlives the call, which copies the string before returning.
        unsafe {
            SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                what.as_ptr() as isize,
                SMTO_ABORTIFHUNG,
                5000,
                std::ptr::null_mut(),
            );
        }
    }
}

/// Delete the programs an update moved aside as `<name>.old` (see
/// `windows/hooks.nsh`), in the background. One a process still runs (an
/// agent's herdr from before the update) can't be deleted yet and is left for
/// a later launch.
#[cfg(windows)]
pub fn clear_moved_aside() {
    fn clear(dir: &Path) {
        let Ok(entries) = std::fs::read_dir(dir) else { return };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                clear(&path);
            } else if path.extension().is_some_and(|e| e == "old") {
                let _ = std::fs::remove_file(&path);
            }
        }
    }
    if let Some(dir) = std::env::current_exe().ok().and_then(|e| e.parent().map(Path::to_path_buf)) {
        std::thread::spawn(move || clear(&dir));
    }
}

/// A program shipped inside the app bundle, beside the app's executable.
pub fn bundled(name: &str) -> Option<PathBuf> {
    let current = std::env::current_exe().ok()?;
    let candidate = current.parent()?.join(exe(name));
    candidate.is_file().then_some(candidate)
}

fn on_path(name: &str) -> Option<PathBuf> {
    std::iter::once(local_bin())
        .chain(std::env::split_paths(shell_path()))
        .map(|dir| dir.join(exe(name)))
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
/// nothing to link and the installed copies are used as they are. On Windows
/// nothing is linked: the app's folder goes on the user's PATH, as an
/// installer would put it, so a terminal (and an agent in one) finds
/// `mycelium`. The installer keeps that folder across updates.
#[cfg(windows)]
pub fn link_bundled() -> PathSetup {
    let dir = first_dir();
    let linked: Vec<String> = ["mycelium", "herdr"]
        .into_iter()
        .filter(|name| bundled(name).is_some())
        .map(String::from)
        .collect();
    if !linked.is_empty() {
        if let Err(e) = windows_path::add(&dir) {
            eprintln!("[mycelium] could not add {} to your PATH: {e}", dir.display());
        }
    }
    PathSetup {
        linked,
        skipped: Vec::new(),
        on_path: local_bin_on_user_path(),
        // PowerShell, adding to the user's own PATH only. Not `setx PATH
        // "%PATH%;…"`: that copies the system PATH into the user's and cuts the
        // result at 1024 characters, which damages a typical developer's PATH.
        line: format!(
            "[Environment]::SetEnvironmentVariable(\"Path\", \
             [Environment]::GetEnvironmentVariable(\"Path\", \"User\") + \";{}\", \"User\")",
            dir.display()
        ),
    }
}

#[cfg(unix)]
pub fn link_bundled() -> PathSetup {
    let dir = local_bin();
    let mut linked = Vec::new();
    let mut skipped = Vec::new();
    for name in ["mycelium", "herdr"] {
        let Some(source) = bundled(name) else { continue };
        // An AppImage's programs live in a mount that is new on every launch
        // and gone once the app exits, while the agents in herdr keep running.
        // Link to a copy kept outside it instead, so their `mycelium` commands
        // still work after the app closes.
        let Some(source) = stable_copy(&source, name) else {
            skipped.push(name.to_string());
            continue;
        };
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

/// Where a bundled program can be linked from for as long as it's installed.
///
/// Inside an AppImage (`$APPIMAGE` is set) that's a copy under
/// ~/.local/share/mycelium/bin, refreshed when this launch's program differs.
/// The copy is written beside the old one and renamed over it, so an agent
/// still running the old copy keeps running. Anywhere else the bundled
/// program already has a lasting path.
#[cfg(unix)]
fn stable_copy(source: &Path, name: &str) -> Option<PathBuf> {
    if std::env::var_os("APPIMAGE").is_none() {
        return Some(source.to_path_buf());
    }
    let dir = home().join(".local").join("share").join("mycelium").join("bin");
    let target = dir.join(name);
    let same = |a: &Path, b: &Path| -> bool {
        let (Ok(a), Ok(b)) = (std::fs::metadata(a), std::fs::metadata(b)) else { return false };
        a.len() == b.len() && a.modified().ok() == b.modified().ok()
    };
    if same(source, &target) {
        return Some(target);
    }
    std::fs::create_dir_all(&dir).ok()?;
    let partial = dir.join(format!(".{name}.partial"));
    std::fs::copy(source, &partial).ok()?;
    // Keep the source's modified time, so the next launch can tell it's current.
    if let Ok(modified) = std::fs::metadata(source).and_then(|m| m.modified()) {
        let _ = std::fs::File::options()
            .write(true)
            .open(&partial)
            .and_then(|f| f.set_modified(modified));
    }
    std::fs::rename(&partial, &target).ok()?;
    Some(target)
}

/// Open a web or mail link, or a file, with what this machine opens it with.
pub fn open(target: &OsStr) -> std::io::Result<()> {
    #[cfg(target_os = "macos")]
    let mut cmd = command("open");
    #[cfg(target_os = "linux")]
    let mut cmd = command("xdg-open");
    #[cfg(windows)]
    let mut cmd = {
        // Not `cmd /c start`, which reads `&` in a URL as a second command.
        let mut c = command("rundll32");
        c.arg("url.dll,FileProtocolHandler");
        c
    };
    cmd.arg(target).spawn().map(|_| ())
}
