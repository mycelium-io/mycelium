# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The host-side cognition-engine mediation core (currently unwired, backend-side only).

The first-party SAO mediator: the NEGMAS core (``mediator``), the Pi brain
(``brain``), the fuzzy offer snap (``offer_snap``), and the SLIM drive loop
(``runtime``). The heavy dep (negmas) comes from the ``mycelium[engine]`` extra.

The mediation core is retained dormant, pending integration with the
``await``/``respond`` resident model. Nothing wires it to a runtime entry
point today.
"""
