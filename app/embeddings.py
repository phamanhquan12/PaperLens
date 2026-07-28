"""Embedding providers and paper chunk indexing."""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from abc import ABC, abstractmethod
from typing import Any, Iterable, Sequence

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.models import PaperChunk
from app.db.session import session_scope

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class EmbeddingProvider(ABC):
    name: str
    dimensions: int

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic local embeddings for tests/dev without paid APIs."""

    def __init__(self, dimensions: int = 384, model_name: str = "hashing-v1") -> None:
        self.dimensions = dimensions
        self.name = model_name

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = text.lower().split()
        if not tokens:
            tokens = ["empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # Use multiple hash lanes per token
            for i in range(0, min(len(digest), 32), 4):
                idx = struct.unpack_from(">I", digest, i)[0] % self.dimensions
                sign = 1.0 if digest[i] % 2 == 0 else -1.0
                vec[idx] += sign
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, api_key: str, model: str, base_url: str | None = None, dimensions: int = 1536) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.dimensions = dimensions
        self.name = model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = OpenAI(**kwargs)
        response = client.embeddings.create(model=self.model, input=list(texts))
        data = sorted(response.data, key=lambda row: row.index)
        vectors = [list(row.embedding) for row in data]
        if vectors and len(vectors[0]) != self.dimensions:
            # Adapt declared dimensions to provider response
            self.dimensions = len(vectors[0])
        return vectors


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    cfg = settings or get_settings()
    provider = (cfg.embedding_provider or "hashing").lower()
    if provider == "hashing":
        return HashingEmbeddingProvider(dimensions=cfg.embedding_dimensions, model_name="hashing-v1")
    if provider == "openai":
        if not cfg.embedding_api_key:
            raise EmbeddingError("EMBEDDING_API_KEY required for openai embedding provider")
        if not cfg.embedding_model:
            raise EmbeddingError("EMBEDDING_MODEL required for openai embedding provider")
        return OpenAIEmbeddingProvider(
            api_key=cfg.embedding_api_key,
            model=cfg.embedding_model,
            base_url=cfg.embedding_base_url,
            dimensions=cfg.embedding_dimensions,
        )
    raise EmbeddingError(f"Unknown embedding provider: {provider}")


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return float(dot / (na * nb))


def index_paper_chunks(
    paper_id: str,
    *,
    settings: Settings | None = None,
    force: bool = False,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Embed paper chunks idempotently. Skips chunks that already have matching model embeddings unless force."""
    cfg = settings or get_settings()
    provider = get_embedding_provider(cfg)
    updated = 0
    skipped = 0
    with session_scope(cfg) as session:
        rows = list(
            session.scalars(
                select(PaperChunk)
                .where(PaperChunk.paper_id == paper_id)
                .order_by(PaperChunk.chunk_type, PaperChunk.id)
            )
        )
        pending: list[PaperChunk] = []
        for row in rows:
            if (
                not force
                and row.embedding is not None
                and row.embedding_model == provider.name
                and isinstance(row.embedding, list)
                and len(row.embedding) == provider.dimensions
            ):
                skipped += 1
                continue
            pending.append(row)

        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            vectors = provider.embed_documents([r.content for r in batch])
            if vectors and len(vectors[0]) != provider.dimensions:
                raise EmbeddingError(
                    f"Embedding dimension mismatch: got {len(vectors[0])}, expected {provider.dimensions}"
                )
            for row, vec in zip(batch, vectors):
                row.embedding = vec
                row.embedding_model = provider.name
                updated += 1
        session.flush()

    result = {
        "paper_id": paper_id,
        "provider": provider.name,
        "dimensions": provider.dimensions,
        "updated": updated,
        "skipped": skipped,
        "total": updated + skipped,
    }
    logger.info("Indexed embeddings %s", result)
    return result
