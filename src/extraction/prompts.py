"""Versioned prompts: prompts/<doc_type>/<version>.yaml with `system`, `user` and `repair`
templates.

Placeholders ({schema}, {document}, {errors}) are filled with str.replace rather than
str.format, so prompts can contain literal JSON braces. A version is frozen once it has
results: change the text in a new version and log it in prompts/CHANGELOG.md. Every result
stores a hash of its prompt file, so an edited version is re-run, not mixed with old outputs.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Prompt:
    doc_type: str
    version: str
    sha: str
    system: str
    user: str
    repair: str

    def render_system(self, schema: dict[str, Any]) -> str:
        return self.system.replace("{schema}", json.dumps(schema, indent=2, ensure_ascii=False))

    def render_user(self, document: str) -> str:
        return self.user.replace("{document}", document.strip())

    def render_repair(self, errors: list[str]) -> str:
        return self.repair.replace("{errors}", "\n".join(f"- {error}" for error in errors))


def load_prompt(prompts_dir: Path, doc_type: str, version: str) -> Prompt:
    path = prompts_dir / doc_type / f"{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"prompt {path} doesn't exist")
    raw = path.read_bytes()
    data = yaml.safe_load(raw) or {}
    missing = [key for key in ("system", "user", "repair") if not data.get(key)]
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)}")
    if str(data.get("version")) != version:
        raise ValueError(f"{path}: `version` is {data.get('version')!r}, expected {version!r}")
    for key, placeholder in (("user", "{document}"), ("repair", "{errors}")):
        if placeholder not in data[key]:
            raise ValueError(f"{path}: `{key}` has no {placeholder} placeholder")
    return Prompt(
        doc_type=doc_type,
        version=version,
        sha=hashlib.sha256(raw).hexdigest()[:12],
        system=data["system"],
        user=data["user"],
        repair=data["repair"],
    )
