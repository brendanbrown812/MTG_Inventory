from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.embeddings.base import EmbeddingBatch, normalize_vector
from app.logging_setup import get_logger
from app.services.openai_usage import (
    complete_openai_usage,
    estimate_tokens,
    fail_openai_usage,
    reserve_openai_usage,
)


_log = get_logger(".embeddings.openai")


class OpenAIEmbeddingProvider:
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        dimensions: int,
        *,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        client_factory: Callable[..., Any] | None = None,
    ):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        if dimensions < 1:
            raise ValueError("Embedding dimensions must be positive")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._client_factory = client_factory

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _client(self):
        if self._client_factory is not None:
            factory = self._client_factory
        else:
            from openai import OpenAI

            factory = OpenAI
        return factory(
            api_key=self._api_key,
            timeout=self._timeout_seconds,
            max_retries=self._max_retries,
        )

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(())
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding inputs cannot be empty")
        started = time.perf_counter()
        reservation_id = reserve_openai_usage(
            "semantic_embedding",
            self._model,
            estimated_input_tokens=sum(estimate_tokens(text) for text in texts),
        )
        try:
            response = self._client().embeddings.create(
                model=self._model,
                input=texts,
                dimensions=self._dimensions,
                encoding_format="float",
            )
        except Exception as exc:
            fail_openai_usage(reservation_id, exc)
            raise
        complete_openai_usage(reservation_id, response)
        ordered = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(texts))):
            raise RuntimeError("OpenAI returned incomplete or unexpected embedding indexes")
        vectors = tuple(normalize_vector(item.embedding) for item in ordered)
        usage = getattr(response, "usage", None)
        input_tokens = (
            getattr(usage, "prompt_tokens", None)
            or getattr(usage, "total_tokens", 0)
            or 0
        )
        _log.info(
            "Embedding request completed model=%s inputs=%s dimensions=%s "
            "input_tokens=%s elapsed_ms=%s",
            self._model,
            len(texts),
            self._dimensions,
            input_tokens,
            round((time.perf_counter() - started) * 1_000),
        )
        return EmbeddingBatch(vectors=vectors, input_tokens=input_tokens)
