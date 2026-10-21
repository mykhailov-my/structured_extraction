"""OpenRouter: one OpenAI-compatible API in front of many hosted models."""

import os
from typing import Any

import openai

from extraction.providers.base import Completion, Message, ProviderError, TransientError

BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    def __init__(
        self,
        model: str,
        *,
        max_tokens: int,
        timeout_s: float,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        """`extra_body`: more OpenRouter request fields, e.g. {"provider": {"sort": "latency"}}."""
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ProviderError("OPENROUTER_API_KEY is not set - add it to .env")
        # The SDK's own retries are off: the pipeline retries every provider the same way.
        self._client = openai.OpenAI(
            base_url=BASE_URL, api_key=api_key, timeout=timeout_s, max_retries=0
        )
        self._model = model
        self._max_tokens = max_tokens
        body = dict(extra_body or {})
        # Route only to upstreams that support every parameter we send - above all
        # response_format - instead of one that would silently ignore the schema.
        body["provider"] = {"require_parameters": True, **body.get("provider", {})}
        self._extra_body = body

    def warm_up(self) -> None:
        pass

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        sampling: dict[str, Any],
    ) -> Completion:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system}, *messages],
                max_tokens=self._max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "extraction", "strict": True, "schema": schema},
                },
                extra_body=self._extra_body,
                **sampling,
            )
        except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
            raise TransientError(f"OpenRouter: {e}") from e  # timeouts are APIConnectionErrors
        except openai.APIStatusError as e:
            if e.status_code in (408, 409):
                raise TransientError(f"OpenRouter {e.status_code}: {e.message}") from e
            raise ProviderError(f"OpenRouter {e.status_code}: {e.message}") from e
        if not response.choices:  # OpenRouter can answer 200 with an error body and no choices
            raise TransientError(f"OpenRouter sent no choices: {getattr(response, 'error', None)}")
        choice = response.choices[0]
        usage = response.usage
        return Completion(
            text=choice.message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason,
            cost_usd=getattr(usage, "cost", None),
            served_by=getattr(response, "provider", None),
        )
