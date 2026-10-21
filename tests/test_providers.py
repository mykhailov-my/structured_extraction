import ollama
import pytest
from openai.types.chat import ChatCompletion

from extraction.config import ModelConfig
from extraction.providers import ProviderError, create_provider
from extraction.providers.ollama import OllamaProvider
from extraction.providers.openrouter import OpenRouterProvider

MESSAGES = [{"role": "user", "content": "a posting"}]
SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def test_openrouter_sends_the_schema_and_sampling_and_reads_the_cost(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    provider = OpenRouterProvider("vendor/model", max_tokens=500, timeout_s=5)
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return ChatCompletion.model_validate(
            {
                "id": "gen-1",
                "object": "chat.completion",
                "created": 0,
                "model": "vendor/model",
                "provider": "SomeHost",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "{}"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "cost": 0.00004,
                },
            }
        )

    monkeypatch.setattr(provider._client.chat.completions, "create", create)
    completion = provider.complete(
        system="rules", messages=MESSAGES, schema=SCHEMA, sampling={"temperature": 0.0}
    )

    assert sent["messages"][0] == {"role": "system", "content": "rules"}
    assert sent["response_format"]["json_schema"] == {
        "name": "extraction",
        "strict": True,
        "schema": SCHEMA,
    }
    assert sent["extra_body"]["provider"]["require_parameters"] is True
    assert (sent["temperature"], sent["max_tokens"]) == (0.0, 500)
    assert (completion.input_tokens, completion.output_tokens) == (120, 30)
    assert (completion.cost_usd, completion.served_by) == (0.00004, "SomeHost")


def test_openrouter_needs_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider("vendor/model", max_tokens=500, timeout_s=5)


def test_ollama_sends_the_schema_options_and_think(monkeypatch):
    provider = OllamaProvider("qwen3.5:4b", max_tokens=500, timeout_s=5, num_ctx=4096, think=False)
    sent = {}

    def chat(**kwargs):
        sent.update(kwargs)
        return ollama.ChatResponse(
            model="qwen3.5:4b",
            done=True,
            done_reason="stop",
            prompt_eval_count=120,
            eval_count=30,
            message=ollama.Message(role="assistant", content="{}"),
        )

    monkeypatch.setattr(provider._client, "chat", chat)
    sampling = {"temperature": 0.7, "top_p": 0.9}
    completion = provider.complete(
        system="rules", messages=MESSAGES, schema=SCHEMA, sampling=sampling
    )

    assert sent["format"] == SCHEMA
    assert sent["options"] == {"num_ctx": 4096, "num_predict": 500, **sampling}
    assert sent["think"] is False
    assert (completion.input_tokens, completion.output_tokens) == (120, 30)
    assert completion.cost_usd == 0.0


def test_an_unknown_provider_option_is_rejected():
    with pytest.raises(ProviderError, match="num_ctxx"):
        create_provider(ModelConfig(provider="ollama", model="qwen3.5:4b", num_ctxx=4096))
