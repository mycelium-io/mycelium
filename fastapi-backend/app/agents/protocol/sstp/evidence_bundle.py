# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""sstp/evidence_bundle.py — EvidenceBundleMessage kind."""

from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class EvidenceBundleMessage(_STBaseMessage):
    """A collection of evidence supporting a claim or decision."""

    kind: Literal["evidence_bundle"]
