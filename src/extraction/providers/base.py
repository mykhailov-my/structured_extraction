"""The contract between the pipeline and a model backend; provider SDKs stay behind it."""

from dataclasses import dataclass
from typing import Any, Protocol

Message = dict[str, str]
"""A chat turn: {"role": "user" | "assistant", "content": "..."}."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None = None  # "stop", "length" (hit max_tokens), ...
    cost_usd: float | None = None  # as billed; None if the provider doesn't report it
    served_by: str | None = None  # which upstream answered (OpenRouter picks per request)


class ProviderError(Exception):
    """A failure that retrying won't fix: bad request, auth, unknown model, no credits."""


class TransientError(Exception):
    """A failure worth retrying: timeout, rate limit, 5xx, dropped connection."""


class Provider(Protocol):
    def warm_up(self) -> None:
        """Get ready before the first measured call, e.g. load a local model into memory."""

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        sampling: dict[str, Any],
    ) -> Completion:
        """One chat completion whose answer is constrained to `schema`."""
