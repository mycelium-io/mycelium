// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Prevents an extra console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    mycelium_desktop_lib::run()
}
