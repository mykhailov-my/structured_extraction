"""Search over the chunks. Four modes, so that each step can be measured:

- `bm25`: lexical, BM25 over the chunks' header and text, words lowercased and their
  Ukrainian and English endings cut off;
- `vector`: cosine similarity of bge-m3 embeddings, in a Qdrant collection;
- `hybrid`: both lists fused by reciprocal rank fusion (RRF);
- `rerank`: the fused candidates rescored by a cross-encoder, bge-reranker-v2-m3.

Metadata filters (a document's kind, its date, its company and language, and whether it is
the current version) apply in every mode. Superseded versions are left out by default.
"""

import base64
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from rag.chunking import Chunk
from rag.llm import OpenRouter

MODES = ("bm25", "vector", "hybrid", "rerank")


@dataclass(frozen=True)
class Filters:
    kind: str | None = None  # "posting" or "official"
    since: str | None = None  # the earliest date, YYYY-MM-DD
    company: str | None = None
    language: str | None = None
    current_only: bool = True  # leave out superseded versions

    def allows(self, chunk: Chunk) -> bool:
        return (
            (self.kind is None or chunk.kind == self.kind)
            and (self.since is None or (chunk.date or "") >= self.since)
            and (self.company is None or (chunk.company or "").lower() == self.company.lower())
            and (self.language is None or chunk.language == self.language)
            and (chunk.current or not self.current_only)
        )


@dataclass
class Hit:
    chunk: Chunk
    score: float  # the mode's own: BM25, cosine, RRF, or the cross-encoder's probability
    ranks: dict[str, int] = field(default_factory=dict)  # 1-based rank in each list it was in


# --- lexical ----------------------------------------------------------------------------

# Ukrainian noun, adjective and verb endings, cut longest first.
_UK_ENDINGS = sorted(
    ["ами", "ями", "ові", "еві", "ого", "ому", "ими", "іми", "ою", "ею", "ах", "ях", "ам", "ям",
     "ів", "їв", "ий", "ій", "ої", "ом", "ем", "им", "ім", "их", "іх", "ати", "ити", "ться",
     "ється", "ення", "ання", "ість", "ості", "а", "я", "у", "ю", "і", "ї", "и", "о", "е", "є",
     "ь"],
    key=len,
    reverse=True,
)  # fmt: skip


def tokens(text: str) -> list[str]:
    """Lowercased words with their endings cut off: "розробника" and "розробник" match."""
    words = re.findall(r"[\w+#]+", text.lower())
    return [_stem(word) for word in words if len(word) > 1 or word.isdigit()]


def _stem(word: str) -> str:
    if re.search(r"[а-яіїєґ]", word) and len(word) > 4:
        for ending in _UK_ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                return word[: -len(ending)]
    elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


class BM25:
    def __init__(self, docs: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._tf = [Counter(doc) for doc in docs]
        self._len = [len(doc) for doc in docs]
        self._avg = sum(self._len) / max(1, len(docs))
        df = Counter(word for doc in docs for word in set(doc))
        n = len(docs)
        self._idf = {word: math.log(1 + (n - f + 0.5) / (f + 0.5)) for word, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self._tf))
        for i, (tf, length) in enumerate(zip(self._tf, self._len, strict=True)):
            norm = self._k1 * (1 - self._b + self._b * length / self._avg)
            out[i] = sum(
                self._idf[word] * tf[word] * (self._k1 + 1) / (tf[word] + norm)
                for word in query
                if word in tf
            )
        return out


# --- vectors ----------------------------------------------------------------------------


class Embeddings:
    """Embeddings from OpenRouter, cached in a JSONL file by the text's SHA-256 so that a text
    is embedded once: the cache is committed, and CI embeds only what is new."""

    def __init__(self, model: str, cache: Path, client: OpenRouter | None = None) -> None:
        self.model, self._path, self._client = model, cache, client
        self._known: dict[str, np.ndarray] = {}
        if cache.exists():
            for line in cache.read_text("utf-8").splitlines():
                row = json.loads(line)
                if row["model"] == model:
                    raw = base64.b64decode(row["vector"])
                    self._known[row["sha"]] = np.frombuffer(raw, dtype=np.float16).astype(
                        np.float32
                    )

    def __call__(self, texts: list[str]) -> np.ndarray:
        shas = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        missing = list(dict.fromkeys(sha for sha in shas if sha not in self._known))
        if missing:
            by_sha = dict(zip(shas, texts, strict=True))
            self._add(missing, [by_sha[sha] for sha in missing])
        return np.stack([self._known[sha] for sha in shas])

    def _add(self, shas: list[str], texts: list[str]) -> None:
        if self._client is None:
            self._client = OpenRouter()
        rows = []
        for start in range(0, len(texts), 64):
            vectors = self._client.embed(self.model, texts[start : start + 64])
            for sha, vector in zip(shas[start : start + 64], vectors, strict=True):
                vector = np.asarray(vector, dtype=np.float32)
                vector /= np.linalg.norm(vector) or 1
                self._known[sha] = vector.astype(np.float16).astype(np.float32)
                packed = base64.b64encode(vector.astype(np.float16).tobytes()).decode()
                rows.append(json.dumps({"model": self.model, "sha": sha, "vector": packed}))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write("\n".join(rows) + "\n")


class CrossEncoder:
    """bge-reranker-v2-m3 (INT8 ONNX) through fastembed, on the CPU: the model downloads once
    into .cache/fastembed/. Scores are probabilities that the passage answers the query."""

    def __init__(self, model: str, cache_dir: Path = Path(".cache/fastembed")) -> None:
        self.model, self._cache_dir = model, cache_dir

    @cached_property
    def _encoder(self):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return TextCrossEncoder(model_name=self.model, cache_dir=str(self._cache_dir))

    def __call__(self, query: str, texts: list[str]) -> list[float]:
        logits = list(self._encoder.rerank(query, texts, batch_size=16))
        return [1 / (1 + math.exp(-logit)) for logit in logits]


# --- the retriever ----------------------------------------------------------------------


class Retriever:
    def __init__(
        self,
        chunks: list[Chunk],
        embeddings: Embeddings | None,
        reranker: CrossEncoder | None = None,
        *,
        candidates: int = 30,
        rerank_top: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.chunks = chunks
        self._embeddings, self._reranker = embeddings, reranker
        self._candidates, self._rerank_top, self._rrf_k = candidates, rerank_top, rrf_k
        self._bm25 = BM25([tokens(chunk.indexed) for chunk in chunks])
        self._qdrant = None
        if embeddings is None:  # BM25 only: no key needed
            return
        vectors = embeddings([chunk.indexed for chunk in chunks])
        self._qdrant = QdrantClient(location=":memory:")
        self._qdrant.create_collection(
            "chunks",
            vectors_config=qm.VectorParams(size=vectors.shape[1], distance=qm.Distance.COSINE),
        )
        self._qdrant.upsert(
            "chunks",
            points=[
                qm.PointStruct(id=i, vector=vector.tolist(), payload=_payload(chunk))
                for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
            ],
        )

    def search(
        self, query: str, *, mode: str = "rerank", k: int = 5, filters: Filters | None = None
    ) -> list[Hit]:
        filters = filters or Filters()
        if mode == "bm25":
            return self._bm25_hits(query, filters)[:k]
        if mode == "vector":
            return self._vector_hits(query, filters)[:k]
        fused = self._fused(query, filters)
        if mode == "hybrid":
            return fused[:k]
        if mode != "rerank" or self._reranker is None:
            raise ValueError(f"unknown search mode {mode!r}, or no reranker")
        top = fused[: self._rerank_top]
        scores = self._reranker(query, [hit.chunk.indexed for hit in top])
        for hit, score in zip(top, scores, strict=True):
            hit.score = score
        top.sort(key=lambda hit: hit.score, reverse=True)
        for rank, hit in enumerate(top, 1):
            hit.ranks["rerank"] = rank
        return top[:k]

    def _bm25_hits(self, query: str, filters: Filters) -> list[Hit]:
        scores = self._bm25.scores(tokens(query))
        order = [i for i in np.argsort(-scores) if scores[i] > 0 and filters.allows(self.chunks[i])]
        return [
            Hit(self.chunks[i], float(scores[i]), {"bm25": rank})
            for rank, i in enumerate(order[: self._candidates], 1)
        ]

    def _vector_hits(self, query: str, filters: Filters) -> list[Hit]:
        if self._qdrant is None:
            raise ValueError("vector search needs embeddings")
        vector = self._embeddings([query])[0]
        points = self._qdrant.query_points(
            "chunks",
            query=vector.tolist(),
            query_filter=_qdrant_filter(filters),
            limit=self._candidates,
        ).points
        return [
            Hit(self.chunks[p.id], p.score, {"vector": rank}) for rank, p in enumerate(points, 1)
        ]

    def _fused(self, query: str, filters: Filters) -> list[Hit]:
        fused: dict[str, Hit] = {}
        for hits in (self._bm25_hits(query, filters), self._vector_hits(query, filters)):
            for hit in hits:
                [(name, rank)] = hit.ranks.items()
                entry = fused.setdefault(hit.chunk.chunk_id, Hit(hit.chunk, 0.0))
                entry.score += 1 / (self._rrf_k + rank)
                entry.ranks[name] = rank
        return sorted(fused.values(), key=lambda hit: hit.score, reverse=True)


def _payload(chunk: Chunk) -> dict:
    return {
        "kind": chunk.kind,
        "day": _day(chunk.date),
        "company": (chunk.company or "").lower(),
        "language": chunk.language,
        "current": chunk.current,
    }


def _day(date: str | None) -> int:
    """2025-01-27 as 20250127: Qdrant's ranges are numeric."""
    return int(date.replace("-", "")) if date else 0


def _qdrant_filter(filters: Filters) -> qm.Filter | None:
    def match(key: str, value: object) -> qm.FieldCondition:
        return qm.FieldCondition(key=key, match=qm.MatchValue(value=value))

    must: list[qm.Condition] = []
    if filters.kind:
        must.append(match("kind", filters.kind))
    if filters.company:
        must.append(match("company", filters.company.lower()))
    if filters.language:
        must.append(match("language", filters.language))
    if filters.current_only:
        must.append(match("current", True))
    if filters.since:
        must.append(qm.FieldCondition(key="day", range=qm.Range(gte=_day(filters.since))))
    return qm.Filter(must=must) if must else None
