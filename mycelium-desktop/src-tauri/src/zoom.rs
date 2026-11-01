//! Zooming the main window in and out, as a browser does, and keeping the
//! level across restarts in `~/.mycelium/desktop-zoom.json`.
//!
//! On a Mac the View menu's Zoom In (⌘=), Zoom Out (⌘−) and Actual Size (⌘0)
//! do it. Windows and Linux have no menu bar, so a script in the window turns
//! Ctrl + = or +, Ctrl + − and Ctrl + 0 into a navigation to [`HOST`], which
//! [`from_navigation`] reads and cancels. The hub's pages get no IPC, so this
//! is the one way they can ask, and all they can ask for is a zoom step.

use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager, Url};

use crate::paths::home;

/// The levels a step moves between, as in a browser.
const LEVELS: [f64; 13] = [0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];
/// The address the keyboard script navigates to. `.invalid` can never resolve,
/// so a navigation that somehow wasn't cancelled goes nowhere.
pub const HOST: &str = "zoom.mycelium.invalid";

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Step {
    In,
    Out,
    Reset,
}

impl Step {
    pub fn from_id(id: &str) -> Option<Step> {
        match id {
            "zoom:in" => Some(Step::In),
            "zoom:out" => Some(Step::Out),
            "zoom:reset" => Some(Step::Reset),
            _ => None,
        }
    }
}

/// The zoom level the window is at, for the next step to start from.
#[derive(Default)]
pub struct Zoom(Mutex<Option<f64>>);

/// The level one step from `level`: the next one up or down the list, or 100%.
pub fn next(level: f64, step: Step) -> f64 {
    match step {
        Step::Reset => 1.0,
        Step::In => LEVELS.iter().copied().find(|l| *l > level + 1e-6).unwrap_or(LEVELS[LEVELS.len() - 1]),
        Step::Out => LEVELS.iter().rev().copied().find(|l| *l < level - 1e-6).unwrap_or(LEVELS[0]),
    }
}

fn file() -> PathBuf {
    home().join(".mycelium").join("desktop-zoom.json")
}

/// The saved level, kept within the levels a step reaches; 100% when there's none.
pub fn saved() -> f64 {
    std::fs::read_to_string(file())
        .ok()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
        .and_then(|v| v.get("zoom").and_then(serde_json::Value::as_f64))
        .filter(|z| z.is_finite())
        .map(|z| z.clamp(LEVELS[0], LEVELS[LEVELS.len() - 1]))
        .unwrap_or(1.0)
}

fn save(level: f64) {
    let path = file();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Err(e) = std::fs::write(&path, format!("{{\"zoom\": {level}}}\n")) {
        eprintln!("[mycelium] couldn't save the zoom level: {e}");
    }
}

fn current(app: &AppHandle) -> f64 {
    let state = app.state::<Zoom>();
    let mut level = state.0.lock().unwrap();
    *level.get_or_insert_with(saved)
}

/// Put the main window at the level it's at: on start, and after every page
/// load, since a new page can start at 100%.
pub fn restore(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_zoom(current(app));
    }
}

/// Take one step, and remember where it landed.
pub fn apply(app: &AppHandle, step: Step) {
    let level = next(current(app), step);
    *app.state::<Zoom>().0.lock().unwrap() = Some(level);
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_zoom(level);
    }
    save(level);
}

/// The step a navigation to [`HOST`] asks for, or `None` for any other address.
pub fn from_navigation(url: &Url) -> Option<Step> {
    if url.host_str() != Some(HOST) {
        return None;
    }
    match url.path() {
        "/in" => Some(Step::In),
        "/out" => Some(Step::Out),
        "/reset" => Some(Step::Reset),
        _ => None,
    }
}

/// Whether a navigation is to [`HOST`], which is never let through.
pub fn is_zoom_address(url: &Url) -> bool {
    url.host_str() == Some(HOST)
}

/// The script that turns Ctrl + = / + / − / 0 into a zoom step, for windows
/// without a menu bar to carry the shortcuts. It leaves every other key, and
/// the same keys with Alt or Shift held for other things (except the Shift a
/// `+` needs), to the page.
#[cfg(not(target_os = "macos"))]
pub fn keys_script() -> String {
    format!(
        r#"(() => {{
  const steps = {{ "=": "in", "+": "in", "-": "out", "_": "out", "0": "reset" }};
  window.addEventListener("keydown", (e) => {{
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const step = steps[e.key];
    if (!step) return;
    e.preventDefault();
    e.stopPropagation();
    window.location.href = "https://{HOST}/" + step;
  }}, true);
}})();"#
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_step_moves_one_level_and_stops_at_the_ends() {
        assert_eq!(next(1.0, Step::In), 1.1);
        assert_eq!(next(1.0, Step::Out), 0.9);
        assert_eq!(next(3.0, Step::In), 3.0);
        assert_eq!(next(0.5, Step::Out), 0.5);
        assert_eq!(next(2.5, Step::Reset), 1.0);
        // A level between two steps moves to the next one in that direction.
        assert_eq!(next(1.2, Step::In), 1.25);
        assert_eq!(next(1.2, Step::Out), 1.1);
    }

    #[test]
    fn only_the_zoom_address_is_a_zoom_step() {
        let step = |u: &str| from_navigation(&Url::parse(u).unwrap());
        assert_eq!(step("https://zoom.mycelium.invalid/in"), Some(Step::In));
        assert_eq!(step("https://zoom.mycelium.invalid/out"), Some(Step::Out));
        assert_eq!(step("https://zoom.mycelium.invalid/reset"), Some(Step::Reset));
        assert_eq!(step("https://zoom.mycelium.invalid/elsewhere"), None);
        assert_eq!(step("http://127.0.0.1:3717/room/checkout"), None);
        assert_eq!(step("https://zoom.mycelium.invalid.example.com/in"), None);
    }

    #[test]
    fn menu_items_name_their_step() {
        assert_eq!(Step::from_id("zoom:in"), Some(Step::In));
        assert_eq!(Step::from_id("zoom:reset"), Some(Step::Reset));
        assert_eq!(Step::from_id("settings"), None);
    }
}
