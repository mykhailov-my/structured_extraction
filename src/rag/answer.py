"""Answers with their sources.

The question goes to the retriever; when even the best passage scores under `min_relevance`
the answer is that the documents don't have it, without asking the model. Otherwise the best
passages that fit in `context_tokens` go into the prompt numbered, and the model cites them as
[n] after every sentence. The citations are mapped back to documents and sections; a reply
with no citation that says the documents don't have it is an abstention.
"""

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from rag.chunking import Chunk, count_tokens
from rag.config import PROMPTS, RagConfig
from rag.llm import OpenRouter
from rag.search import Filters, Hit, Retriever

REFUSALS = {"uk": "У документах цього немає.", "en": "The documents don't say."}
_REFUSAL = re.compile(
    r"у документах (?:цього|про це) немає"
    r"|в документах (?:этого|об этом) нет"
    r"|the documents don.t say",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    sha: str
    system: str
    user: str

    def render(self, **values: str) -> str:
        text = self.user
        for key, value in values.items():
            text = text.replace(f"{{{key}}}", value)
        return text


def load_prompt(name: str, version: str, folder: Path = PROMPTS) -> Prompt:
    path = folder / f"{name}_{version}.yaml"
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if str(data.get("version")) != version:
        raise ValueError(f"{path}: `version` is {data.get('version')!r}, expected {version!r}")
    sha = hashlib.sha256(raw).hexdigest()[:12]
    return Prompt(name, version, sha, data["system"], data["user"])


@dataclass
class Passage:
    number: int
    chunk: Chunk
    score: float


@dataclass
class Answer:
    question: str
    text: str
    abstained: bool
    reason: str  # "answered", "model abstained" or "nothing relevant found"
    passages: list[Passage]  # what the model saw
    cited: list[Passage] = field(default_factory=list)
    best_score: float | None = None
    latency_s: float = 0.0

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(p.chunk.doc_id for p in self.cited))


class Rag:
    def __init__(self, config: RagConfig, retriever: Retriever, client: OpenRouter | None = None):
        self.config, self.retriever = config, retriever
        self.client = client or OpenRouter()
        self.prompt = load_prompt("answer", config.prompts.answer)

    def ask(self, question: str, filters: Filters | None = None) -> Answer:
        started = time.monotonic()
        filters = filters or Filters()
        search = self.config.search
        hits = self.retriever.search(question, mode=search.mode, k=search.k, filters=filters)
        best = hits[0].score if hits else None
        refusal = REFUSALS[question_language(question)]
        if not hits or (search.mode == "rerank" and best < self.config.answer.min_relevance):
            return Answer(question, refusal, True, "nothing relevant found", [], best_score=best,
                          latency_s=time.monotonic() - started)  # fmt: skip
        passages = within_budget(hits, self.config.answer.context_tokens)
        user = self.prompt.render(passages=render(passages), question=question)
        text = self.client.chat(self.config.models.answer, self.prompt.system, user, max_tokens=700)
        cited = cited_passages(text, passages)
        abstained = not cited and bool(_REFUSAL.search(text))
        return Answer(
            question,
            text.strip(),
            abstained,
            "model abstained" if abstained else "answered",
            passages,
            cited,
            best,
            time.monotonic() - started,
        )


def within_budget(hits: list[Hit], max_tokens: int) -> list[Passage]:
    """The best passages, in order, while they fit in `max_tokens`; the best one is cut to fit
    if it alone is too long."""
    passages, used = [], 0
    for hit in hits:
        size = count_tokens(f"[{len(passages) + 1}] {hit.chunk.indexed}")
        if used + size > max_tokens:
            if passages:
                break
            hit = Hit(_truncated(hit.chunk, max_tokens), hit.score, hit.ranks)
            size = max_tokens
        passages.append(Passage(len(passages) + 1, hit.chunk, hit.score))
        used += size
    return passages


def _truncated(chunk: Chunk, max_tokens: int) -> Chunk:
    from dataclasses import replace

    from rag.chunking import _encoding

    budget = max(50, max_tokens - count_tokens(chunk.header) - 10)
    text = _encoding().decode(_encoding().encode(chunk.text)[:budget])
    return replace(chunk, text=text)


def render(passages: list[Passage]) -> str:
    return "\n\n".join(f"[{p.number}] {p.chunk.header}\n{p.chunk.text}" for p in passages)


def cited_passages(text: str, passages: list[Passage]) -> list[Passage]:
    numbers = {
        int(n) for group in re.findall(r"\[([\d,\s]+)\]", text) for n in re.findall(r"\d+", group)
    }
    return [p for p in passages if p.number in numbers]


def question_language(question: str) -> str:
    letters = [char for char in question if char.isalpha()]
    cyrillic = sum("Ѐ" <= char <= "ӿ" for char in letters)
    return "uk" if cyrillic > 0.3 * max(1, len(letters)) else "en"
