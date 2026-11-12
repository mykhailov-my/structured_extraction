"""The files ingestion writes under data/rag/: documents.jsonl, chunks.jsonl (structural),
chunks_fixed.jsonl (the baseline) and manifest.json, and reading them back."""

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from extraction.collect import write_file
from rag.chunking import Chunk, fixed, structural
from rag.config import DATA, RAW
from rag.ingest import Document, ingest, read_documents, write_documents


def build(raw_dir: Path = RAW, out_dir: Path = DATA) -> dict:
    """Ingest and chunk the corpus; returns the manifest."""
    documents = ingest(raw_dir)
    kept = [doc for doc in documents if doc.status == "kept"]
    chunked = {"structural": [], "fixed": []}
    counts: dict[str, Counter] = {name: Counter() for name in chunked}
    for doc in kept:
        for name, cut in (("structural", structural), ("fixed", fixed)):
            chunks = cut(doc)
            chunked[name] += chunks
            counts[name][doc.doc_id] = len(chunks)
    write_documents(documents, out_dir / "documents.jsonl")
    for name, file in (("structural", "chunks.jsonl"), ("fixed", "chunks_fixed.jsonl")):
        lines = (json.dumps(asdict(chunk), ensure_ascii=False) for chunk in chunked[name])
        write_file(out_dir / file, "\n".join(lines) + "\n")
    manifest = _manifest(raw_dir, documents, counts)
    write_file(out_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def read_chunks(strategy: str = "structural", out_dir: Path = DATA) -> list[Chunk]:
    file = out_dir / ("chunks.jsonl" if strategy == "structural" else "chunks_fixed.jsonl")
    return [Chunk(**json.loads(line)) for line in file.read_text("utf-8").splitlines()]


def documents(out_dir: Path = DATA) -> list[Document]:
    return read_documents(out_dir / "documents.jsonl")


def _manifest(raw_dir: Path, documents: list[Document], counts: dict[str, Counter]) -> dict:
    files = [
        {
            "raw_file": doc.raw_file,
            "format": doc.format,
            "bytes": (raw_dir / doc.raw_file).stat().st_size,
            "raw_sha256": doc.raw_sha256,
            "doc_id": doc.doc_id,
            "kind": doc.kind,
            "title": doc.title,
            "date": doc.date,
            "language": doc.language,
            "source": doc.source,
            "sha256": doc.sha256,
            "chars": len(doc.text),
            "status": doc.status,
            "duplicate_of": doc.duplicate_of,
            "superseded_by": doc.superseded_by,
            "chunks": {name: counts[name][doc.doc_id] for name in counts},
        }
        for doc in sorted(documents, key=lambda doc: doc.raw_file)
    ]
    return {
        "files": len(files),
        "formats": dict(Counter(doc.format for doc in documents)),
        "kinds": dict(Counter(doc.kind for doc in documents)),
        "indexed": sum(doc.status == "kept" for doc in documents),
        "duplicates": sum(doc.status == "duplicate" for doc in documents),
        "superseded": sum(doc.superseded_by is not None for doc in documents),
        "chunks": {name: sum(c.values()) for name, c in counts.items()},
        "documents": files,
    }
