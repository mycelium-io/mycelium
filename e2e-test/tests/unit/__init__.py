"""Unit tests for the three-axis matrix refactor.

These tests run with no infrastructure: no SSH, no Docker, no LLM. They
use ``unittest.mock`` to stub :mod:`subprocess` so transport selection
and provisioner wiring can be verified in CI within seconds.
"""
