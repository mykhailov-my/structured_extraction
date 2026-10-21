"""One document through one model: call -> validate -> at most one repair -> outcome."""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from extraction.config import Retry
from extraction.prompts import Prompt
from extraction.providers import Completion, Message, Provider, TransientError
from extraction.schemas import json_schema

log = logging.getLogger(__name__)

Status = Literal["ok", "repaired", "failed", "error"]
"""ok: valid on the first call. repaired: valid after the one repair call. failed: still
invalid after it. error: the provider kept failing (timeouts, 5xx), so no answer to judge."""


class Attempt(BaseModel):
    """One model call: the first try or the repair."""

    raw_output: str
    errors: list[str]  # validation errors; empty when the answer is valid
    latency_ms: float  # retries and their back-off included
    retries: int  # transient failures before this call went through
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    finish_reason: str | None
    served_by: str | None


@dataclass
class Outcome:
    status: Status
    output: dict[str, Any] | None = None
    attempts: list[Attempt] = field(default_factory=list)
    error: str | None = None


def extract(
    text: str,
    *,
    provider: Provider,
    prompt: Prompt,
    schema_model: type[BaseModel],
    sampling: dict[str, Any],
    retry: Retry,
) -> Outcome:
    """Extract `schema_model` from `text`. An invalid answer gets exactly one repair call that
    shows the model its answer and the validation errors; if that fails too, the document is
    `failed`. ProviderError (bad config, auth) propagates: it would fail every document."""
    schema = json_schema(schema_model)
    system = prompt.render_system(schema)
    messages: list[Message] = [{"role": "user", "content": prompt.render_user(text)}]
    attempts: list[Attempt] = []
    for is_repair in (False, True):
        try:
            completion, latency_ms, retries = _complete(
                provider, retry, system=system, messages=messages, schema=schema, sampling=sampling
            )
        except TransientError as e:
            return Outcome("error", attempts=attempts, error=str(e))
        output, errors = validate(completion.text, schema_model)
        attempts.append(
            Attempt(
                raw_output=completion.text,
                errors=errors,
                latency_ms=round(latency_ms, 1),
                retries=retries,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                cost_usd=completion.cost_usd,
                finish_reason=completion.finish_reason,
                served_by=completion.served_by,
            )
        )
        if output is not None:
            return Outcome("repaired" if is_repair else "ok", output, attempts)
        if completion.finish_reason == "content_filter":
            break  # pointing at schema errors won't undo a refusal
        messages = [
            *messages,
            {"role": "assistant", "content": completion.text or "(empty answer)"},
            {"role": "user", "content": prompt.render_repair(errors)},
        ]
    return Outcome("failed", attempts=attempts)


def validate(text: str, schema_model: type[BaseModel]) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse and validate a raw answer: (output, []) if valid, else (None, errors)."""
    try:
        parsed = schema_model.model_validate_json(text)
    except ValidationError as e:
        return None, [_describe(error) for error in e.errors()]
    return parsed.model_dump(mode="json"), []


def _describe(error: ErrorDetails) -> str:
    location = ".".join(str(part) for part in error["loc"]) or "(root)"
    return f"{location}: {error['msg']}"


def _complete(provider: Provider, retry: Retry, **request: Any) -> tuple[Completion, float, int]:
    """Call the provider, retrying transient failures with exponential back-off and jitter.
    Latency spans the whole call, waits included: that is what a caller would experience."""
    start = time.perf_counter()
    for attempt in range(retry.max_retries + 1):
        try:
            completion = provider.complete(**request)
        except TransientError as e:
            if attempt == retry.max_retries:
                raise
            delay = retry.backoff_s * 2**attempt * random.uniform(0.5, 1.5)
            log.warning("    %s - retry %d/%d in %.1fs", e, attempt + 1, retry.max_retries, delay)
            time.sleep(delay)
        else:
            return completion, (time.perf_counter() - start) * 1000, attempt
    raise AssertionError("unreachable")
