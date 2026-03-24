"""
Pluggable embedding service for persistent memory semantic search.

Providers:
  - local:    sentence-transformers (default, 384 dims, no API key)
  - model2vec: Model2Vec potion models (tiny, armv7 compatible, 256 dims)
  - openai:   OpenAI/litellm embedding API (1536 dims, remote)
  - none:     disable embeddings entirely (search unavailable)

All embeddings are zero-padded to EMBEDDING_VECTOR_SIZE (default 1536)
so the pgvector column doesn't need resizing on provider change.
"""

import logging
import os
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# pgvector column size — all embeddings are padded/truncated to this.
EMBEDDING_VECTOR_SIZE: int = max(1536, settings.EMBEDDING_DIMENSIONS)

# Set MYCELIUM_STUB_EMBEDDINGS=1 to skip model loading (CI, offline environments).
_STUB = os.getenv("MYCELIUM_STUB_EMBEDDINGS", "").strip() not in ("", "0", "false")

# ── Public API ──────────────────────────────────────────────────────────────


def embed_text(text: str) -> list[float] | None:
    """Generate embedding for a single text string. Returns None if provider is 'none'."""
    if _STUB:
        return _stub_vector(text)
    provider = settings.EMBEDDING_PROVIDER
    if provider == "none":
        return None
    raw = _get_provider(provider)(text)
    return _pad(raw)


def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for multiple texts."""
    if not texts:
        return []
    if _STUB:
        return [_stub_vector(t) for t in texts]
    provider = settings.EMBEDDING_PROVIDER
    if provider == "none":
        return [None] * len(texts)
    fn = _get_provider(provider)
    return [_pad(fn(t)) for t in texts]


def get_dimensions() -> int:
    """Return the vector size used for the pgvector column."""
    return EMBEDDING_VECTOR_SIZE


# ── Padding ─────────────────────────────────────────────────────────────────


def _pad(vec: list[float]) -> list[float]:
    """Pad or truncate to EMBEDDING_VECTOR_SIZE."""
    if len(vec) >= EMBEDDING_VECTOR_SIZE:
        return vec[:EMBEDDING_VECTOR_SIZE]
    return vec + [0.0] * (EMBEDDING_VECTOR_SIZE - len(vec))


# ── Stub (CI / offline) ────────────────────────────────────────────────────


def _stub_vector(seed: str) -> list[float]:
    """Deterministic non-zero vector for CI stubs."""
    import hashlib

    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    v = [float((h >> i) & 0xFF) / 255.0 + 0.01 for i in range(EMBEDDING_VECTOR_SIZE)]
    return v


# ── Provider registry ──────────────────────────────────────────────────────

_providers: dict[str, Any] = {}


def _get_provider(name: str) -> Any:
    """Get or lazily initialize the embedding provider."""
    if name not in _providers:
        init = _PROVIDER_INIT.get(name)
        if init is None:
            msg = (
                f"Unknown embedding provider: {name!r}. "
                f"Valid options: {', '.join(_PROVIDER_INIT.keys())}, none"
            )
            raise ValueError(msg)
        _providers[name] = init()
    return _providers[name]


# ── Local: sentence-transformers ────────────────────────────────────────────


def _init_local():
    from sentence_transformers import SentenceTransformer

    hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
    model_slug = settings.EMBEDDING_MODEL.replace("/", "--")
    snapshots_dir = os.path.join(hf_cache, f"models--{model_slug}", "snapshots")
    model_path = settings.EMBEDDING_MODEL
    if os.path.isdir(snapshots_dir):
        snapshots = [s for s in os.listdir(snapshots_dir) if not s.startswith(".")]
        if snapshots:
            model_path = os.path.join(snapshots_dir, snapshots[0])

    logger.info("Loading sentence-transformers model: %s", model_path)
    model = SentenceTransformer(model_path)
    logger.info("Embedding model loaded (%d dims)", settings.EMBEDDING_DIMENSIONS)

    def _embed(text: str) -> list[float]:
        return model.encode(text).tolist()

    return _embed


# ── Model2Vec: lightweight static embeddings ────────────────────────────────


def _init_model2vec():
    from model2vec import StaticModel

    model_name = settings.EMBEDDING_MODEL
    if model_name.startswith("sentence-transformers/"):
        model_name = "minishlab/potion-base-8M"  # sensible default for model2vec

    logger.info("Loading Model2Vec model: %s", model_name)
    model = StaticModel.from_pretrained(model_name)
    logger.info("Model2Vec loaded (%s)", model_name)

    def _embed(text: str) -> list[float]:
        return model.encode(text).tolist()

    return _embed


# ── OpenAI / litellm: remote embedding API ──────────────────────────────────


def _init_openai():
    import litellm

    model_name = settings.EMBEDDING_MODEL
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY

    if not api_key:
        msg = "EMBEDDING_API_KEY or LLM_API_KEY required for openai embedding provider"
        raise ValueError(msg)

    logger.info("Using remote embedding: %s", model_name)

    def _embed(text: str) -> list[float]:
        response = litellm.embedding(model=model_name, input=[text], api_key=api_key)
        return response.data[0]["embedding"]

    return _embed


# ── Registry ────────────────────────────────────────────────────────────────

_PROVIDER_INIT = {
    "local": _init_local,
    "model2vec": _init_model2vec,
    "openai": _init_openai,
}
