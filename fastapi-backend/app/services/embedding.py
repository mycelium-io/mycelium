"""
Local embedding service using sentence-transformers.

Provides semantic vector embeddings for persistent memory search.
Uses all-MiniLM-L6-v2 (384 dimensions, runs locally from HF cache).
"""

import logging
import os

from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None

# Set MYCELIUM_STUB_EMBEDDINGS=1 to skip model loading (CI, offline environments).
_STUB = os.getenv("MYCELIUM_STUB_EMBEDDINGS", "").strip() not in ("", "0", "false")


def _load_model() -> SentenceTransformer:
    """Load the model, preferring the local HF cache snapshot to avoid network calls."""
    hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
    model_slug = settings.EMBEDDING_MODEL.replace("/", "--")
    snapshots_dir = os.path.join(hf_cache, f"models--{model_slug}", "snapshots")
    model_path = settings.EMBEDDING_MODEL
    if os.path.isdir(snapshots_dir):
        snapshots = [s for s in os.listdir(snapshots_dir) if not s.startswith(".")]
        if snapshots:
            model_path = os.path.join(snapshots_dir, snapshots[0])

    logger.info("Loading embedding model from: %s", model_path)
    model = SentenceTransformer(model_path)
    logger.info("Embedding model loaded (dimensions=%d)", settings.EMBEDDING_DIMENSIONS)
    return model


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = _load_model()
    return _model


def _stub_vector(seed: str) -> list[float]:
    """Deterministic non-zero unit-ish vector for CI stubs."""
    import hashlib

    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    dim = settings.EMBEDDING_DIMENSIONS
    v = [float((h >> i) & 0xFF) / 255.0 + 0.01 for i in range(dim)]
    return v


def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    if _STUB:
        return _stub_vector(text)
    return _get_model().encode(text).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    if not texts:
        return []
    if _STUB:
        return [_stub_vector(t) for t in texts]
    return [e.tolist() for e in _get_model().encode(texts)]
