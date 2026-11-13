"""rag.yaml, checked: the RAG's models, prompt versions, search settings and CI thresholds."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "rag" / "raw"
DATA = ROOT / "data" / "rag"
EVALS = ROOT / "evals"
PROMPTS = ROOT / "prompts" / "rag"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Models(_Strict):
    embeddings: str
    reranker: str
    answer: str
    judge: str
    context: str


class Prompts(_Strict):
    answer: str
    judge: str
    faithfulness: str
    context: str


class Search(_Strict):
    mode: str
    candidates: int
    rerank_top: int
    rrf_k: int
    k: int
    context: bool  # search and show the chunks' contexts (rag/context.py)


class Answer(_Strict):
    context_tokens: int
    min_relevance: float
    temperature: float | None = 0.0  # None: the model's own (reasoning models take no other)
    max_tokens: int = 700  # a reasoning model's thinking counts too


class RagConfig(_Strict):
    models: Models
    prompts: Prompts
    search: Search
    answer: Answer
    thresholds: dict[str, float]


def load(path: Path = ROOT / "rag.yaml") -> RagConfig:
    return RagConfig.model_validate(yaml.safe_load(path.read_text("utf-8")))
