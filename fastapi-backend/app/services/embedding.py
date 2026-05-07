# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Local embedding service using fastembed (ONNX-based).

Provides semantic vector embeddings for persistent memory search.
Uses BAAI/bge-small-en-v1.5 (384 dimensions, runs locally, no PyTorch).

Drop-in replacement for the previous sentence-transformers implementation.
Aligned with cisco-eti/ioc-cfn-cognitive-agents embedding stack.
"""

import logging
import os
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_model: Any = None

# Set MYCELIUM_STUB_EMBEDDINGS=1 to skip model loading (CI, offline environments).
_STUB = os.getenv("MYCELIUM_STUB_EMBEDDINGS", "").strip() not in ("", "0", "false")

# fastembed model name — BAAI/bge-small-en-v1.5 produces 384-dim vectors,
# same dimensionality as all-MiniLM-L6-v2.
_FASTEMBED_MODEL = os.getenv("FASTEMBED_MODEL", "BAAI/bge-small-en-v1.5")
_FASTEMBED_CACHE = os.getenv("FASTEMBED_CACHE_PATH", "/opt/fastembed")


def _load_model() -> Any:
    """Load the ONNX embedding model via fastembed."""
    from fastembed import TextEmbedding

    logger.info("Loading embedding model: %s (cache: %s)", _FASTEMBED_MODEL, _FASTEMBED_CACHE)
    model = TextEmbedding(model_name=_FASTEMBED_MODEL, cache_dir=_FASTEMBED_CACHE)
    logger.info("Embedding model loaded (dimensions=%d)", settings.EMBEDDING_DIMENSIONS)
    return model


def _get_model() -> Any:
    global _model
    if _model is None:
        _model = _load_model()
    return _model


def warmup() -> None:
    """Pre-load the model. Call during startup to avoid first-request latency."""
    if _STUB:
        return
    _get_model()
    logger.info("Embedding model warmed up")


def _stub_vector(seed: str) -> list[float]:
    """Deterministic non-zero unit-ish vector for CI stubs."""
    import hashlib

    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    dim = settings.EMBEDDING_DIMENSIONS
    v = [float((h >> i) & 0xFF) / 255.0 + 0.01 for i in range(dim)]
    return v


def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    import time as _time

    from app.services.metrics import record_embedding, record_embedding_latency

    t0 = _time.monotonic()
    if _STUB:
        result = _stub_vector(text)
    else:
        # fastembed.embed() returns a generator of numpy arrays;
        # .tolist() converts np.float32 → Python float for pgvector compatibility.
        result = next(iter(_get_model().embed([text]))).tolist()
    elapsed_ms = (_time.monotonic() - t0) * 1000
    record_embedding(source="local", text_length=len(text))
    record_embedding_latency(elapsed_ms)
    return result


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    if not texts:
        return []

    import time as _time

    from app.services.metrics import record_embedding_batch, record_embedding_latency

    t0 = _time.monotonic()
    if _STUB:
        result = [_stub_vector(t) for t in texts]
    else:
        result = [e.tolist() for e in _get_model().embed(texts)]
    elapsed_ms = (_time.monotonic() - t0) * 1000
    record_embedding_batch(
        source="local", count=len(texts), total_text_length=sum(len(t) for t in texts)
    )
    record_embedding_latency(elapsed_ms)
    return result
