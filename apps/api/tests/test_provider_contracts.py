"""Provider contract tests (SRS §13): each adapter's stream() and embed() against recorded-style
HTTP bodies, run through the real httpx request path (only the network is replaced, using
httpx.MockTransport). Covers the wire formats, token accounting and error mapping."""
import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import app.ai.providers as providers
from app.ai.providers import Completion, ProviderError, TransientProviderError

_RealClient = httpx.AsyncClient

MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]
KW: dict[str, Any] = {
    "base_url": None,
    "api_key": "sk-test",
    "model": "m",
    "messages": MSGS,
    "temperature": 0.2,
    "max_tokens": 64,
    "json_schema": None,
}

OPENAI_SSE = "\n".join(
    [
        'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "",
        'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":2}}',
        "",
        "data: [DONE]",
        "",
    ]
)

ANTHROPIC_SSE = "\n".join(
    [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":21,"output_tokens":1}}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}',
        "",
        "event: message_delta",
        'data: {"type":"message_delta","usage":{"output_tokens":7}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ]
)

ANTHROPIC_TOOL_SSE = "\n".join(
    [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":5}}}',
        'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"a\\":"}}',  # noqa: E501
        'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"1}"}}',  # noqa: E501
        'data: {"type":"message_delta","usage":{"output_tokens":3}}',
    ]
)

OLLAMA_NDJSON = "\n".join(
    [
        '{"message":{"role":"assistant","content":"Hel"},"done":false}',
        '{"message":{"role":"assistant","content":"lo"},"done":false}',
        '{"message":{"role":"assistant","content":""},"done":true,"prompt_eval_count":9,"eval_count":4}',
    ]
)


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[httpx.Request], httpx.Response]], list[httpx.Request]]:  # noqa: E501
    """Route every provider HTTP call to `handler`; returns the list of requests seen."""

    async def allow(url: str) -> None:
        return None

    monkeypatch.setattr(providers, "_check_destination", allow)

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(wrapped)
            return _RealClient(*args, **kwargs)

        monkeypatch.setattr(providers.httpx, "AsyncClient", factory)
        return seen

    return install


async def _collect(adapter: Any, **kw: Any) -> tuple[list[str], Completion]:
    deltas: list[str] = []
    final: Completion | None = None
    async for item in adapter.stream(**kw):
        if isinstance(item, Completion):
            final = item
        else:
            deltas.append(item)
    assert final is not None, "stream must end with a Completion"
    return deltas, final


def _sse(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_openai_stream(network: Any) -> None:
    seen = network(lambda r: _sse(OPENAI_SSE))
    deltas, final = asyncio.run(_collect(providers.OpenAIAdapter(), **KW))
    assert deltas == ["Hel", "lo"]
    assert (final.text, final.tokens_in, final.tokens_out) == ("Hello", 11, 2)
    req = seen[0]
    assert req.url == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}


def test_openai_stream_structured_output_asks_for_json(network: Any) -> None:
    seen = network(lambda r: _sse(OPENAI_SSE))
    kw = {**KW, "json_schema": {"type": "object"}}
    asyncio.run(_collect(providers.OpenAIAdapter(), **kw))
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}


def test_anthropic_stream(network: Any) -> None:
    seen = network(lambda r: _sse(ANTHROPIC_SSE))
    deltas, final = asyncio.run(_collect(providers.AnthropicAdapter(), **KW))
    assert deltas == ["Hel", "lo"]
    assert (final.text, final.tokens_in, final.tokens_out) == ("Hello", 21, 7)
    req = seen[0]
    assert req.url == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-test"
    body = json.loads(req.content)
    assert body["stream"] is True and body["system"] == "Be brief."
    assert all(m["role"] != "system" for m in body["messages"])


def test_anthropic_stream_collects_tool_json(network: Any) -> None:
    network(lambda r: _sse(ANTHROPIC_TOOL_SSE))
    kw = {**KW, "json_schema": {"type": "object"}}
    _, final = asyncio.run(_collect(providers.AnthropicAdapter(), **kw))
    assert json.loads(final.text) == {"a": 1}
    assert (final.tokens_in, final.tokens_out) == (5, 3)


def test_anthropic_midstream_error_is_transient(network: Any) -> None:
    network(lambda r: _sse('data: {"type":"error","error":{"type":"overloaded_error"}}'))
    with pytest.raises(TransientProviderError):
        asyncio.run(_collect(providers.AnthropicAdapter(), **KW))


def test_ollama_stream(network: Any) -> None:
    seen = network(lambda r: httpx.Response(200, text=OLLAMA_NDJSON))
    kw = {**KW, "base_url": "http://ollama.example:11434", "api_key": None}
    deltas, final = asyncio.run(_collect(providers.OllamaAdapter(), **kw))
    assert deltas == ["Hel", "lo"]
    assert (final.text, final.tokens_in, final.tokens_out) == ("Hello", 9, 4)
    assert seen[0].url == "http://ollama.example:11434/api/chat"
    assert json.loads(seen[0].content)["stream"] is True


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ProviderError), (403, ProviderError), (400, ProviderError),
     (429, TransientProviderError), (503, TransientProviderError)],
)
def test_stream_maps_http_errors(network: Any, status: int, error: type[Exception]) -> None:
    network(lambda r: httpx.Response(status, json={"error": "nope"}))
    with pytest.raises(error) as exc:
        asyncio.run(_collect(providers.OpenAIAdapter(), **KW))
    assert "sk-test" not in str(exc.value)  # the key must never leak into an error


def test_stream_garbled_payload_is_a_provider_error(network: Any) -> None:
    network(lambda r: _sse("data: {not json"))
    with pytest.raises(ProviderError):
        asyncio.run(_collect(providers.OpenAIAdapter(), **KW))


def test_stream_network_failure_is_transient(network: Any) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    network(boom)
    with pytest.raises(TransientProviderError):
        asyncio.run(_collect(providers.OpenAIAdapter(), **KW))


def test_stream_still_enforces_the_ssrf_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `network` fixture here: the real destination check must run before any request."""
    kw = {**KW, "base_url": "http://169.254.169.254/latest"}
    with pytest.raises(ProviderError):
        asyncio.run(_collect(providers.OpenAIAdapter(), **kw))


def test_openai_embed(network: Any) -> None:
    seen = network(
        lambda r: httpx.Response(
            200,
            json={
                # returned out of order on purpose: results must follow the input order
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"prompt_tokens": 6},
            },
        )
    )
    out = asyncio.run(
        providers.OpenAIAdapter().embed(
            base_url=None, api_key="sk-test", model="text-embedding-3-small", texts=["a", "b"]
        )
    )
    assert out.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert out.tokens == 6
    assert json.loads(seen[0].content) == {"model": "text-embedding-3-small", "input": ["a", "b"]}


def test_ollama_embed(network: Any) -> None:
    seen = network(
        lambda r: httpx.Response(
            200, json={"embeddings": [[1.0, 2.0], [3.0, 4.0]], "prompt_eval_count": 5}
        )
    )
    out = asyncio.run(
        providers.OllamaAdapter().embed(
            base_url="http://ollama.example:11434", api_key=None, model="nomic", texts=["a", "b"]
        )
    )
    assert out.vectors == [[1.0, 2.0], [3.0, 4.0]] and out.tokens == 5
    assert seen[0].url == "http://ollama.example:11434/api/embed"


def test_embed_count_mismatch_is_rejected(network: Any) -> None:
    network(lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]}))
    with pytest.raises(ProviderError):
        asyncio.run(
            providers.OpenAIAdapter().embed(base_url=None, api_key="k", model="m", texts=["a", "b"])
        )


def test_anthropic_has_no_embeddings() -> None:
    with pytest.raises(ProviderError, match="embeddings"):
        asyncio.run(
            providers.AnthropicAdapter().embed(base_url=None, api_key="k", model="m", texts=["a"])
        )
