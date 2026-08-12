# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The host-side cognition-engine runtime.

A first-party engine (the SAO mediator) runs *where the daemon runs* — the host —
so its brain executes where ``pi`` lives, not inside the backend container. This
package holds the NEGMAS core (``mediator``), the brains (``brain``: litellm + Pi),
the fuzzy offer snap (``offer_snap``), and the SLIM drive loop (``runtime``). Heavy
deps (negmas, litellm) come from the ``mycelium[engine]`` extra.
"""
