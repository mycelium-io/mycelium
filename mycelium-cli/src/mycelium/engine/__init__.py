# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The host-side cognition-engine mediation core (currently unwired).

The first-party SAO mediator: the NEGMAS core (``mediator``), the Pi brain
(``brain``), the fuzzy offer snap (``offer_snap``), and the SLIM drive loop
(``runtime``). The heavy dep (negmas) comes from the ``mycelium[engine]`` extra.

This core was driven host-side by the daemon's engine connector, which has been
removed; engines now run backend-side only. The mediation core is retained,
dormant, to be re-homed on the ``await``/``respond`` resident model rather than
resurrected from a deletion; nothing wires it to a runtime entry point today.
"""
