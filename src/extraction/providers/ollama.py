"""Ollama: open-weight models running on this machine."""

import logging
from typing import Any

import httpx
import ollama

from extraction.providers.base import Completion, Message, ProviderError, TransientError

log = logging.getLogger(__name__)

KEEP_ALIVE = "15m"  # keep the model in memory between documents


class OllamaProvider:
    def __init__(
        self,
        model: str,
        *,
        max_tokens: int,
        timeout_s: float,
        num_ctx: int = 8192,
        think: bool | None = None,
        host: str | None = None,
    ) -> None:
        """`num_ctx`: context window. Ollama's default is small, and a prompt that doesn't fit
        is cut silently. `think`: switch a reasoning model's thinking on or off (None keeps
        the model's default). `host`: default is $OLLAMA_HOST or http://localhost:11434."""
        self._client = ollama.Client(host=host, timeout=timeout_s)
        self._model = model
        self._max_tokens = max_tokens
        self._num_ctx = num_ctx
        self._think = think

    def warm_up(self) -> None:
        """Load the model now, so the first document's latency doesn't include loading it."""
        try:
            self._client.generate(model=self._model, prompt="", keep_alive=KEEP_ALIVE)
        except ollama.ResponseError as e:
            hint = f" - run `ollama pull {self._model}`" if e.status_code == 404 else ""
            raise ProviderError(f"Ollama: {e.error}{hint}") from e
        except ConnectionError as e:
            raise ProviderError(f"{e} (start the Ollama app or `ollama serve`)") from e

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, Any],
        sampling: dict[str, Any],
    ) -> Completion:
        try:
            response = self._client.chat(
                model=self._model,
                messages=[{"role": "system", "content": system}, *messages],
                format=schema,
                options={"num_ctx": self._num_ctx, "num_predict": self._max_tokens, **sampling},
                think=self._think,
                keep_alive=KEEP_ALIVE,
            )
        except ollama.ResponseError as e:
            if e.status_code >= 500:
                raise TransientError(f"Ollama {e.status_code}: {e.error}") from e
            raise ProviderError(f"Ollama {e.status_code}: {e.error}") from e
        except (httpx.TimeoutException, ConnectionError) as e:
            raise TransientError(f"Ollama: {e!r}") from e
        input_tokens = response.prompt_eval_count or 0
        output_tokens = response.eval_count or 0
        if input_tokens + output_tokens >= self._num_ctx:
            log.warning("prompt + answer filled num_ctx=%d; raise num_ctx", self._num_ctx)
        return Completion(
            text=response.message.content or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=response.done_reason,
            cost_usd=0.0,
            served_by="local",
        )
