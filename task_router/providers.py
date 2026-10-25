"""Explicit providers: fixtures test plumbing; live failures never fall back.

Every HTTP attempt reserves calls/tokens/cost in SQLite before I/O. Reservations
survive restarts. Rates are conservative *estimates*, not provider price guarantees.
"""

import hashlib
import json
import math
import os
import re
import time
from typing import Protocol

import httpx
import numpy as np


class EmbeddingProvider(Protocol):
    model: str
    dimension: int

    def embed(self, texts: list[str], request_id: str | None = None) -> list[list[float]]: ...


class FixtureEmbeddings:
    """Signed feature hashing, with no semantic model or scenario-answer table."""

    model = "fixture-hash-v1"

    def __init__(self, dimension=256):
        self.dimension = dimension

    def embed(self, texts, request_id=None):
        output = []
        for text in texts:
            vector = np.zeros(self.dimension)
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(word.encode()).digest()
                vector[int.from_bytes(digest[:4], "big") % self.dimension] += 1 if digest[4] % 2 else -1
            norm = np.linalg.norm(vector)
            if not norm:
                vector[0] = 1
                norm = 1
            output.append((vector / norm).tolist())
        return output


class ProviderError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, store, settings, transport=None):
        self.store, self.settings = store, settings
        self.model, self.dimension = settings.embedding_model, settings.dimension
        self.transport = transport

    def _reserve(self, kind, model, payload, request_id):
        s = self.settings
        if not s.allow_live:
            raise ProviderError("Live calls disabled. Use the explicit bounded live command.")
        if not os.getenv("OPENROUTER_API_KEY"):
            raise ProviderError("OPENROUTER_API_KEY is missing")
        # UTF-8 byte count is a conservative token bound, intentionally over-reserving.
        incoming = len(json.dumps(payload, ensure_ascii=False).encode())
        outgoing = s.max_output if kind == "chat" else 0
        cost = (
            incoming * (s.input_rate if kind == "chat" else s.embedding_rate) + outgoing * s.output_rate
        ) / 1e6
        with self.store.connect(write=True) as db:
            used = db.execute(
                "SELECT count(*),coalesce(sum(tokens),0),coalesce(sum(cost_bound),0) FROM provider_calls"
            ).fetchone()
            if (
                used[0] + 1 > s.max_calls
                or used[1] + incoming + outgoing > s.max_tokens
                or used[2] + cost > s.max_cost
            ):
                raise ProviderError("Persistent live request/token/cost reservation budget exhausted")
            return db.execute(
                "INSERT INTO provider_calls(request_id,kind,model,tokens,cost_bound,status) "
                "VALUES(?,?,?,?,?,'reserved')",
                (request_id, kind, model, incoming + outgoing, cost),
            ).lastrowid

    def request(self, kind, payload, request_id=None):
        model = payload["model"]
        for attempt in range(self.settings.retries + 1):
            call_id = self._reserve(kind, model, payload, request_id)
            start = time.perf_counter()
            try:
                with httpx.Client(timeout=self.settings.timeout, transport=self.transport) as client:
                    response = client.post(
                        "https://openrouter.ai/api/v1/"
                        + ("embeddings" if kind == "embedding" else "chat/completions"),
                        headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]},
                        json=payload,
                    )
                    response.raise_for_status()
                    result = response.json()
                if "error" in result:
                    raise ProviderError(str(result["error"]))
                with self.store.connect(write=True) as db:
                    db.execute(
                        "UPDATE provider_calls SET status='completed',usage=?,elapsed_ms=? WHERE id=?",
                        (json.dumps(result.get("usage", {})), (time.perf_counter() - start) * 1000, call_id),
                    )
                return result
            except (httpx.HTTPError, ValueError, ProviderError) as exc:
                with self.store.connect(write=True) as db:
                    db.execute(
                        "UPDATE provider_calls SET status='failed',elapsed_ms=? WHERE id=?",
                        ((time.perf_counter() - start) * 1000, call_id),
                    )
                retryable = isinstance(exc, httpx.TransportError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in {429, 500, 502, 503, 504}
                )
                if not retryable or attempt == self.settings.retries:
                    raise ProviderError(f"OpenRouter {kind} failed: {type(exc).__name__}") from exc
                time.sleep(0.15 * 2**attempt)
        raise ProviderError("retry limit")

    def embed(self, texts, request_id=None):
        data = self.request(
            "embedding",
            {"model": self.model, "input": texts, "dimensions": self.dimension, "encoding_format": "float"},
            request_id,
        )
        records = sorted(data.get("data", []), key=lambda x: x["index"])
        if len(records) != len(texts) or [x["index"] for x in records] != list(range(len(texts))):
            raise ProviderError("Embedding response count/index mismatch")
        vectors = [r["embedding"] for r in records]
        validate_vectors(vectors, self.dimension)
        return vectors

    async def chat(self, *, model, messages, system, api_key=None, tools=None, request_id=None):
        import asyncio

        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": self.settings.max_output,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
        return await asyncio.to_thread(self.request, "chat", payload, request_id)


def validate_vectors(vectors, dimension):
    for v in vectors:
        if len(v) != dimension or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
            raise ProviderError(f"Expected finite {dimension}-dimensional embeddings")
        if not any(v):
            raise ProviderError("Zero embedding cannot define cosine similarity")


class CachedEmbeddings:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.model, self.dimension = provider.model, provider.dimension
        self.hits = self.misses = 0

    def embed(self, texts, request_id=None):
        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        found = {}
        for h in set(hashes):
            rows = self.store.rows(
                "SELECT vector FROM embedding_cache WHERE model=? AND dimension=? AND content_hash=?",
                (self.model, self.dimension, h),
            )
            if rows:
                found[h] = json.loads(rows[0]["vector"])
                self.hits += 1
        missing = list(dict.fromkeys(h for h in hashes if h not in found))
        if missing:
            self.misses += len(missing)
            vectors = self.provider.embed([texts[hashes.index(h)] for h in missing], request_id)
            validate_vectors(vectors, self.dimension)
            with self.store.connect(write=True) as db:
                for h, v in zip(missing, vectors, strict=True):
                    db.execute(
                        "INSERT OR REPLACE INTO embedding_cache VALUES(?,?,?,?)",
                        (self.model, self.dimension, h, json.dumps(v)),
                    )
                    found[h] = v
        return [found[h] for h in hashes]
