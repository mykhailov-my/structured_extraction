"""Contextual chunk headers. A model reads a chunk's whole document and writes where the chunk
sits in it and what it is about: one line in Ukrainian and the same in English. The lines are
searched with the chunk (BM25, the embeddings, the reranker) and shown with it to the answer
model. A piece of an amendment such as "в абзаці третьому цифри “2,5” замінити цифрою “3”"
names neither what it changes nor where; its context does. The second language is for
questions asked in the other one, which BM25 can't match otherwise.

Contexts are cached in data/rag/contexts.jsonl, keyed by the model, the prompt, and the texts
of the chunk and its document, so each is written once: the cache is committed, and CI only
writes the contexts of chunks that are new.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from rag.chunking import Chunk
from rag.ingest import Document
from rag.llm import OpenRouter
from rag.prompts import Prompt

log = logging.getLogger(__name__)
MAX_CHARS = 900  # a reply that ignores the format is cut, not trusted to be short

Contextualize = Callable[[list[Chunk], dict[str, Document]], list[Chunk]]


class Contextualizer:
    def __init__(
        self,
        model: str,
        prompt: Prompt,
        cache: Path,
        client: OpenRouter | None = None,
        *,
        workers: int = 12,
    ) -> None:
        self.model, self.prompt, self._path = model, prompt, cache
        self._client, self._workers = client, workers
        self._known: dict[str, str] = {}
        if cache.exists():
            for line in cache.read_text("utf-8").splitlines():
                row = json.loads(line)
                self._known[row["key"]] = row["context"]

    def __call__(self, chunks: list[Chunk], documents: dict[str, Document]) -> list[Chunk]:
        """The chunks with their contexts, from the cache or written now."""
        keys = [self.key(chunk, documents[chunk.doc_id]) for chunk in chunks]
        missing = {key: chunk for key, chunk in zip(keys, chunks, strict=True)}
        missing = {key: chunk for key, chunk in missing.items() if key not in self._known}
        if missing:
            self._write(missing, documents)
        return [replace(c, context=self._known[k]) for c, k in zip(chunks, keys, strict=True)]

    def key(self, chunk: Chunk, document: Document) -> str:
        parts = [self.model, self.prompt.version, self.prompt.sha, document.sha256]
        raw = json.dumps([*parts, chunk.header, chunk.text], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _write(self, missing: dict[str, Chunk], documents: dict[str, Document]) -> None:
        log.info("writing the contexts of %d chunks with %s", len(missing), self.model)
        client = self._client or OpenRouter()

        def one(chunk: Chunk) -> str:
            user = self.prompt.render(
                document=documents[chunk.doc_id].text, passage=f"{chunk.header}\n\n{chunk.text}"
            )
            # the model's own temperature: a reasoning model takes no other, and each context
            # is written once and cached
            reply = client.chat(
                self.model, self.prompt.system, user, max_tokens=2000, temperature=None
            )
            return cleaned(reply)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with (
            ThreadPoolExecutor(self._workers) as pool,
            self._path.open("a", encoding="utf-8") as file,
        ):
            futures = {pool.submit(one, chunk): (key, chunk) for key, chunk in missing.items()}
            for future in as_completed(futures):  # each is kept as it comes: a crash loses little
                key, chunk = futures[future]
                self._known[key] = future.result()
                row = {"key": key, "chunk_id": chunk.chunk_id, "model": self.model,
                       "prompt": self.prompt.version, "context": self._known[key]}  # fmt: skip
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                file.flush()


def cleaned(reply: str) -> str:
    """The "uk:" and "en:" lines of a reply, each on one line; a reply without them as it
    came, on one line. Either way at most MAX_CHARS."""
    lines = [" ".join(line.split()) for line in reply.strip().splitlines()]
    tagged = [line for line in lines if re.match(r"(?:uk|en):\s", line)]
    text = "\n".join(tagged) if tagged else " ".join(line for line in lines if line)
    return text[:MAX_CHARS].strip()
