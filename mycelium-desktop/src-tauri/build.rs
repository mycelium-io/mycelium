// Every command the app answers, declared to Tauri so each gets an
// `allow-<command>` permission. Tauri lets a page from a remote origin, which
// the hub's UI at http://127.0.0.1:<port> is, call an app command only when a
// capability grants that command by name; undeclared, the hub UI could call
// none, not even the three own-hub-ui.json is meant to allow. Declaring them
// also makes Tauri check the app's own pages, so capabilities/default.json
// grants every one of them to those. `test_desktop_commands.py` keeps this
// list, the handler in lib.rs and both capabilities in step.
const COMMANDS: &[&str] = &[
    "get_state",
    "scan_agents",
    "pick_folder",
    "this_machine",
    "choose_agent_folder",
    "agent_screen",
    "run_doctor",
    "herdr_integrations",
    "get_model",
    "save_model",
    "get_experiences",
    "get_hub_settings",
    "add_experience",
    "remove_experience",
    "open_experience",
    "get_autostart",
    "set_autostart",
    "open_room",
    "open_log",
    "start",
    "update_progress",
    "update_retry",
    "terminal_open",
    "terminal_write",
    "terminal_resize",
    "terminal_close",
    "terminal_agents",
    "app_versions",
    "set_update_channel",
    "switch_version",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
