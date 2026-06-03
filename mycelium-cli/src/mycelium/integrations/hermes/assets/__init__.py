# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Asset bundle for the hermes integration.

Subdirectories under ``mycelium/`` are static assets — the hermes-side
plugin tree, the agent skill, etc. — staged into ``~/.hermes/`` by the
install facet. They are *not* imported from the mycelium-cli runtime.
``importlib.resources.files("mycelium.integrations.hermes.assets")``
needs this ``__init__.py`` to treat the directory as a package so
:func:`mycelium.integrations._resources._resolve_asset` can find the
plugin tree on both editable and zipped installs.
"""
