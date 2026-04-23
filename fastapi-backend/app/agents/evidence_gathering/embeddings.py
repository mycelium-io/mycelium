# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Embedding manager (ported from ioc-cfn-cognitive-agents).

Rewired: config path resolves relative to this file.
Dependencies: sentence-transformers (huggingface default), openai (optional).
"""

from __future__ import annotations

import os

import numpy as np
import yaml


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


class EmbeddingManager:
    def __init__(self, config_path: str | None = None) -> None:
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "embeddings_config.yml")
        self.config = load_config(config_path)
        self.model_type = self.config.get("embedding_model_type", "huggingface")

        if self.model_type == "huggingface":
            from sentence_transformers import SentenceTransformer

            self.model_name = self.config.get(
                "embedding_model_name", "sentence-transformers/all-MiniLM-L6-v2"
            )
            self.model = SentenceTransformer(self.model_name)
        elif self.model_type == "openai":
            self.model_name = self.config.get("embedding_model_name", "")
            self.openai_key = self.config.get("openai_api_key", "")
            if not self.openai_key:
                from sentence_transformers import SentenceTransformer

                self.model_type = "huggingface"
                self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
                self.model = SentenceTransformer(self.model_name)
        else:
            from sentence_transformers import SentenceTransformer

            self.model_type = "huggingface"
            self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
            self.model = SentenceTransformer(self.model_name)

    def preprocess_text(self, text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start += chunk_size - overlap
        return chunks

    def generate_embeddings(self, text_chunks: list[str]) -> list | np.ndarray:
        if self.model_type == "huggingface":
            return self.model.encode(text_chunks)
        if self.model_type == "openai":
            from openai import OpenAI  # type: ignore[import-untyped]

            embeddings = []
            client = OpenAI(self.openai_key)
            for text in text_chunks:
                response = client.Embedding.create(input=text, model=self.model_name)
                embeddings.append(response["data"][0]["embedding"])
            return embeddings
        return []
