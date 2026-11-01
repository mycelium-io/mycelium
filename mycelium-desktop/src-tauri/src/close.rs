//! ⌘W (Ctrl+W elsewhere) closes the room's front tab, as in an editor, and the
//! window only when there's no tab left to close.
//!
//! The page owns the tabs: its `tab.close` action answers ⌘W, and leaves the
//! key alone (doesn't `preventDefault`) when nothing closes, such as on a
//! room's Channel or a page with no tabs. Whatever is left closes the window,
//! by a navigation to [`HOST`] that [`is_close_address`] catches and cancels:
//! the hub's pages get no IPC, so, as with zoom, an address is how they ask.
//!
//! On a Mac the File menu's Close Tab owns ⌘W, so the key never reaches the
//! page by itself: the menu item hands it on with [`MENU_SCRIPT`]. Windows and
//! Linux have no menu bar, so the page gets Ctrl+W, and [`keys_script`] closes
//! the window when the page left it alone.

use tauri::Url;

/// The address that asks for the window to close. `.invalid` never resolves,
/// so a navigation that somehow wasn't cancelled goes nowhere.
pub const HOST: &str = "close.mycelium.invalid";

/// Whether a navigation asks for the window to close; it is never let through.
pub fn is_close_address(url: &Url) -> bool {
    url.host_str() == Some(HOST)
}

/// What the Mac menu's Close Tab runs in the main window: ⌘W as the page
/// would get it from the keyboard, and the window closing when no one took it.
#[cfg(target_os = "macos")]
pub fn menu_script() -> String {
    format!(
        r#"(() => {{
  const key = new KeyboardEvent("keydown", {{ key: "w", code: "KeyW", metaKey: true, bubbles: true, cancelable: true }});
  if ((document.activeElement || document.body).dispatchEvent(key)) window.location.href = "https://{HOST}/";
}})();"#
    )
}

/// Close the window on a Ctrl+W the page didn't take. The page's own handler
/// runs after this listener, so the check waits for the event to finish.
#[cfg(not(target_os = "macos"))]
pub fn keys_script() -> String {
    format!(
        r#"(() => {{
  window.addEventListener("keydown", (e) => {{
    if (!e.ctrlKey || e.altKey || e.shiftKey || e.metaKey || e.key.toLowerCase() !== "w") return;
    setTimeout(() => {{
      if (!e.defaultPrevented) window.location.href = "https://{HOST}/";
    }}, 0);
  }});
}})();"#
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_close_address_closes() {
        let closes = |u: &str| is_close_address(&Url::parse(u).unwrap());
        assert!(closes("https://close.mycelium.invalid/"));
        assert!(!closes("https://zoom.mycelium.invalid/in"));
        assert!(!closes("http://127.0.0.1:3717/room/checkout"));
        assert!(!closes("https://close.mycelium.invalid.example.com/"));
    }
}
