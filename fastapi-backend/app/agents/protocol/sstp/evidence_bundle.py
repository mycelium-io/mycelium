"""sstp/evidence_bundle.py — EvidenceBundleMessage kind."""

from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class EvidenceBundleMessage(_STBaseMessage):
    """A collection of evidence supporting a claim or decision."""

    kind: Literal["evidence_bundle"]
