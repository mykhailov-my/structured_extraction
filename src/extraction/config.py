"""config.yaml -> typed settings. Unknown keys and names that point nowhere fail at load time,
so a typo can't silently change an experiment."""

import re
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator

from extraction.schemas import SCHEMAS

_FILE_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # names end up in result file names


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(BaseModel):
    """One model behind a provider. Keys not declared here are provider options
    (e.g. `num_ctx` for Ollama) and go to the provider's constructor."""

    model_config = ConfigDict(extra="allow")

    provider: Literal["openrouter", "ollama"]
    model: str
    max_tokens: int = 4096
    timeout_s: float = 120

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Sampling(_Strict):
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None

    def params(self) -> dict[str, Any]:
        """Only what is set; the provider's defaults apply to the rest."""
        return self.model_dump(exclude_none=True)


class Experiment(_Strict):
    """What `python main.py run` executes: every combination of these four lists."""

    doc_types: list[str]
    models: list[str]
    prompts: list[str]
    sampling: list[str]


class Retry(_Strict):
    max_retries: int = 3
    backoff_s: float = 2.0


class Config(_Strict):
    experiment: Experiment
    models: dict[str, ModelConfig]
    sampling: dict[str, Sampling]
    retry: Retry = Retry()

    _root: Path = PrivateAttr(default_factory=Path)

    @model_validator(mode="after")
    def _check_names(self) -> Self:
        experiment = self.experiment
        problems = [
            f"{name!r} can't be part of a file name"
            for name in [*self.models, *self.sampling]
            if not _FILE_SAFE.match(name)
        ]
        problems += [
            f"experiment.doc_types: unknown {name!r} (known: {', '.join(SCHEMAS)})"
            for name in experiment.doc_types
            if name not in SCHEMAS
        ]
        problems += [
            f"experiment.models: {name!r} is not defined under models"
            for name in experiment.models
            if name not in self.models
        ]
        problems += [
            f"experiment.sampling: {name!r} is not defined under sampling"
            for name in experiment.sampling
            if name not in self.sampling
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def data_dir(self) -> Path:
        return self._root / "data"

    @property
    def prompts_dir(self) -> Path:
        return self._root / "prompts"

    @property
    def results_dir(self) -> Path:
        return self._root / "results"


def load_config(path: Path) -> Config:
    config = Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    config._root = path.resolve().parent
    return config
