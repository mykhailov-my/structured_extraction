"""The RAG's prompts: prompts/rag/<name>_<version>.yaml, versioned. A version with results is
frozen; a change is a new version with an entry in prompts/CHANGELOG.md."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from rag.config import PROMPTS


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    sha: str  # of the file: a cache keyed by it is invalidated by any edit
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
