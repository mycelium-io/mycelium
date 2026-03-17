"""
Local embedding service using fastembed.

Provides semantic vector embeddings for persistent memory search.
Uses BAAI/bge-small-en-v1.5 by default (384 dimensions, runs locally).
"""

import logging

from fastembed import TextEmbedding

from app.config import settings

logger = logging.getLogger(__name__)

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    """Lazy-load the embedding model (downloads on first use)."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
        _model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
        logger.info("Embedding model loaded (dimensions=%d)", settings.EMBEDDING_DIMENSIONS)
    return _model


def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    model = _get_model()
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    if not texts:
        return []
    model = _get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]
