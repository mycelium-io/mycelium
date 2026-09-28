# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# The disk image's layout, for dmgbuild: the app on the left, Applications on
# the right, and the background that says to drag one onto the other.
# dmgbuild writes Finder's layout file itself, so this needs no Finder
# automation (which fails on CI runners and asks permission locally).
#
# Run by scripts/package-mac.sh with -D app=<Mycelium.app> -D background=<png>.

import os.path

app = defines["app"]  # noqa: F821 - dmgbuild provides `defines`
app_name = os.path.basename(app)

format = "UDZO"
filesystem = "HFS+"
files = [app]
symlinks = {"Applications": "/Applications"}
background = defines["background"]  # noqa: F821

window_rect = ((200, 120), (660, 400))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 96
text_size = 13
icon_locations = {
    app_name: (180, 200),
    "Applications": (480, 200),
}
