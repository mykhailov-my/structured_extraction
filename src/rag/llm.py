"""OpenRouter for the RAG: chat completions, as text or as JSON matching a schema, and
embeddings. Timeouts, rate limits and server errors are retried with exponential back-off,
and so, once, is JSON that doesn't parse (a reply cut short); other errors (a bad key, an
unknown model) stop the run. Tokens and dollars are counted per model, for the cost per 1,000
questions. One client can be shared by threads."""

import json
import os
import random
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import openai

BASE_URL = "https://openrouter.ai/api/v1"
_TRANSIENT = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class OpenRouter:
    def __init__(self, *, timeout_s: float = 90, max_retries: int = 4) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set: add it to .env")
        self._client = openai.OpenAI(
            base_url=BASE_URL, api_key=api_key, timeout=timeout_s, max_retries=0
        )
        self._max_retries = max_retries
        self.usage: dict[str, Usage] = defaultdict(Usage)
        self._lock = threading.Lock()

    def chat(
        self,
        model: str,
        system: str,
        user: str,
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1500,
        temperature: float | None = 0.0,
    ) -> Any:
        """The answer's text, or with `schema` the JSON object it parses to. `temperature`
        None leaves it out, for models that don't take one."""
        kwargs: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": schema},
            }
            kwargs["extra_body"] = {"provider": {"require_parameters": True}}
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(2):
            response = self._retry(
                lambda: self._client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens, **kwargs
                )
            )
            if not response.choices:
                raise RuntimeError(f"{model} sent no answer: {getattr(response, 'error', None)}")
            self._count(model, response.usage)
            text = response.choices[0].message.content or ""
            if schema is None:
                return text
            try:
                return json.loads(_without_fences(text))
            except json.JSONDecodeError:
                if attempt == 1:
                    raise
        raise AssertionError("unreachable")

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        response = self._retry(lambda: self._client.embeddings.create(model=model, input=texts))
        self._count(model, response.usage)
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    def _retry(self, call):
        for attempt in range(self._max_retries + 1):
            try:
                return call()
            except _TRANSIENT:
                if attempt == self._max_retries:
                    raise
            except openai.APIStatusError as e:
                if e.status_code not in (408, 409) or attempt == self._max_retries:
                    raise
            time.sleep(2 * 2**attempt * random.uniform(0.5, 1.5))
        raise AssertionError("unreachable")

    def _count(self, model: str, usage: Any) -> None:
        with self._lock:
            total = self.usage[model]
            total.calls += 1
            if usage is not None:
                total.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
                total.output_tokens += getattr(usage, "completion_tokens", 0) or 0
                total.cost_usd += getattr(usage, "cost", 0) or 0


def _without_fences(text: str) -> str:
    """Some upstreams wrap JSON in ``` fences although a schema was asked for."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text
