"""Provider adapters (SRS §3.7): credential test / model listing, chat completion with each
provider's native structured-output mechanism (FR-BYOM-07), token streaming and embeddings.

`stream()` yields text deltas as `str` and ends with one `Completion` carrying the full text
and the token usage, so a caller can show progress and still record cost. `embed()` is for
providers that offer an embeddings API; the app's own RAG index uses local fastembed."""
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import settings
from app.core.ssrf import UnsafeDestination, check_destination

TIMEOUT = 10.0
COMPLETE_TIMEOUT = 120.0


class ProviderError(Exception):
    """Safe-to-show failure message; never contains the API key."""


class TransientProviderError(ProviderError):
    """Timeouts, 429 and 5xx: worth retrying / falling back."""


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


@dataclass
class Embeddings:
    vectors: list[list[float]]
    tokens: int


Message = dict[str, str]


class ProviderAdapter(Protocol):
    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]: ...

    async def complete(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> Completion: ...

    def stream(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> AsyncIterator[str | Completion]: ...

    async def embed(
        self, *, base_url: str | None, api_key: str | None, model: str, texts: list[str]
    ) -> Embeddings: ...


_UNSAFE_MESSAGES = {
    "scheme": "The base URL must start with http:// or https://.",
    "resolve": "Could not resolve the provider's host name.",
    "blocked": "That address is not allowed as a provider base URL.",
    "private": (
        "Private and loopback addresses are not allowed as a provider base URL. "
        "Use a publicly reachable URL (for Ollama, a tunnel)."
    ),
}


async def _check_destination(url: str) -> None:
    """SSRF guard for tenant-supplied base URLs (see app.core.ssrf). Redirects are never
    followed (httpx default)."""
    try:
        await check_destination(url, allow_private=settings.allow_private_base_urls)
    except UnsafeDestination as exc:
        raise ProviderError(_UNSAFE_MESSAGES[exc.kind]) from exc


async def _request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = TIMEOUT,
) -> dict[str, Any]:
    await _check_destination(url)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.request(method, url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise TransientProviderError(
            f"Could not reach the provider ({type(exc).__name__})."
        ) from exc
    if resp.status_code in (401, 403):
        raise ProviderError("The provider rejected the credentials.")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientProviderError(f"The provider returned HTTP {resp.status_code}.")
    if resp.status_code >= 400:
        raise ProviderError(f"The provider returned HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderError("The provider returned an unexpected response.") from exc
    return data if isinstance(data, dict) else {}


async def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    return await _request("GET", url, headers)


async def _post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    return await _request("POST", url, headers, body, timeout=COMPLETE_TIMEOUT)


async def _stream_lines(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> AsyncIterator[str]:
    """POST `body` and yield the response line by line, with the same destination guard and
    error mapping as `_request`. Mid-stream network failures surface as transient errors."""
    await _check_destination(url)
    timeout = httpx.Timeout(COMPLETE_TIMEOUT, connect=TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            async with http.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code in (401, 403):
                    raise ProviderError("The provider rejected the credentials.")
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise TransientProviderError(
                        f"The provider returned HTTP {resp.status_code}."
                    )
                if resp.status_code >= 400:
                    raise ProviderError(f"The provider returned HTTP {resp.status_code}.")
                async for line in resp.aiter_lines():
                    if line:
                        yield line
    except httpx.HTTPError as exc:
        raise TransientProviderError(
            f"Could not reach the provider ({type(exc).__name__})."
        ) from exc


def _json_line(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise _bad_shape() from exc
    return data if isinstance(data, dict) else {}


def _bad_shape() -> ProviderError:
    return ProviderError("The provider returned an unexpected response.")


class OpenAIAdapter:
    """OpenAI and any OpenAI-compatible endpoint."""

    default_base = "https://api.openai.com/v1"

    @staticmethod
    def _headers(api_key: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @staticmethod
    def _body(
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {"type": "json_object"}
            # json_object mode requires the word "json" in the prompt.
            body["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": "Reply with JSON matching: " + json.dumps(json_schema),
                },
            ]
        return body

    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or self.default_base).rstrip("/")
        data = await _get_json(f"{base}/models", self._headers(api_key))
        return sorted(m["id"] for m in data.get("data", []) if "id" in m)

    async def complete(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> Completion:
        base = (base_url or self.default_base).rstrip("/")
        headers = self._headers(api_key)
        body = self._body(model, messages, temperature, max_tokens, json_schema)
        data = await _post_json(f"{base}/chat/completions", headers, body)
        try:
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            return Completion(
                text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc

    async def stream(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> AsyncIterator[str | Completion]:
        base = (base_url or self.default_base).rstrip("/")
        body = self._body(model, messages, temperature, max_tokens, json_schema)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        parts: list[str] = []
        tokens_in = tokens_out = 0
        async for line in _stream_lines(
            f"{base}/chat/completions", self._headers(api_key), body
        ):
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            event = _json_line(payload)
            try:
                for choice in event.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        parts.append(delta)
                        yield delta
                usage = event.get("usage") or {}
                tokens_in = int(usage.get("prompt_tokens", tokens_in))
                tokens_out = int(usage.get("completion_tokens", tokens_out))
            except (AttributeError, TypeError, ValueError) as exc:
                raise _bad_shape() from exc
        yield Completion("".join(parts), tokens_in, tokens_out)

    async def embed(
        self, *, base_url: str | None, api_key: str | None, model: str, texts: list[str]
    ) -> Embeddings:
        base = (base_url or self.default_base).rstrip("/")
        data = await _post_json(
            f"{base}/embeddings", self._headers(api_key), {"model": model, "input": texts}
        )
        try:
            rows = sorted(data["data"], key=lambda r: int(r["index"]))
            vectors = [[float(x) for x in r["embedding"]] for r in rows]
            tokens = int((data.get("usage") or {}).get("prompt_tokens", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc
        if len(vectors) != len(texts):
            raise _bad_shape()
        return Embeddings(vectors, tokens)


# Claude models that reject temperature / top_p / top_k (a 400): Fable, Mythos, Opus 5.x and
# 4.7/4.8, Sonnet 5.x, Haiku 5.x. Older models accept temperature up to 1.0.
_NO_SAMPLING_PARAMS = re.compile(r"^claude-(fable|mythos|opus-5|opus-4-[78]|sonnet-5|haiku-5)")
_TOOL_INSTRUCTION = (
    "Give your answer by calling the `respond` tool with the JSON. Do not reply in plain text."
)


class AnthropicAdapter:
    default_base = "https://api.anthropic.com"

    def _headers(self, api_key: str | None) -> dict[str, str]:
        return {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}

    @staticmethod
    def _body(
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [m for m in messages if m["role"] != "system"],
        }
        if not _NO_SAMPLING_PARAMS.match(model):
            body["temperature"] = min(temperature, 1.0)  # Anthropic's range is 0 to 1
        if json_schema is not None:
            # Native structured output: a tool whose input is the JSON. Forcing the call with
            # tool_choice any/tool is rejected by current models, so ask for it instead; a
            # reply in plain text is still checked against the schema (and repaired) upstream.
            body["tools"] = [
                {
                    "name": "respond",
                    "description": "Return the answer.",
                    "input_schema": json_schema,
                }
            ]
            body["tool_choice"] = {"type": "auto"}
            system = f"{system}\n\n{_TOOL_INSTRUCTION}" if system else _TOOL_INSTRUCTION
        if system:
            body["system"] = system
        return body

    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or self.default_base).rstrip("/")
        data = await _get_json(f"{base}/v1/models", self._headers(api_key))
        return sorted(m["id"] for m in data.get("data", []) if "id" in m)

    async def complete(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> Completion:
        base = (base_url or self.default_base).rstrip("/")
        body = self._body(model, messages, temperature, max_tokens, json_schema)
        data = await _post_json(f"{base}/v1/messages", self._headers(api_key), body)
        try:
            blocks = data["content"]
            tool_input = next((b["input"] for b in blocks if b.get("type") == "tool_use"), None)
            if json_schema is not None and tool_input is not None:
                text = json.dumps(tool_input)
            else:
                text = "".join(b["text"] for b in blocks if b.get("type") == "text")
            usage = data.get("usage", {})
            return Completion(
                text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc

    async def stream(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> AsyncIterator[str | Completion]:
        base = (base_url or self.default_base).rstrip("/")
        body = self._body(model, messages, temperature, max_tokens, json_schema)
        body["stream"] = True
        parts: list[str] = []
        tokens_in = tokens_out = 0
        async for line in _stream_lines(f"{base}/v1/messages", self._headers(api_key), body):
            if not line.startswith("data:"):
                continue  # "event: ..." lines repeat the type carried in the data payload
            event = _json_line(line[5:].strip())
            try:
                kind = event.get("type")
                if kind == "message_start":
                    usage = (event.get("message") or {}).get("usage") or {}
                    tokens_in = int(usage.get("input_tokens", 0))
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    # Plain text, or the partial JSON of the structured-output tool call.
                    piece = delta.get("text") or delta.get("partial_json")
                    if piece:
                        parts.append(piece)
                        yield piece
                elif kind == "message_delta":
                    tokens_out = int((event.get("usage") or {}).get("output_tokens", tokens_out))
                elif kind == "error":
                    raise TransientProviderError("The provider reported an error mid-stream.")
            except (AttributeError, TypeError, ValueError) as exc:
                raise _bad_shape() from exc
        yield Completion("".join(parts), tokens_in, tokens_out)

    async def embed(
        self, *, base_url: str | None, api_key: str | None, model: str, texts: list[str]
    ) -> Embeddings:
        raise ProviderError("Anthropic does not offer an embeddings API.")


class OllamaAdapter:
    @staticmethod
    def _body(
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_schema is not None:
            body["format"] = json_schema  # Ollama's native structured output
        return body

    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or "").rstrip("/")
        data = await _get_json(f"{base}/api/tags", {})
        return sorted(m["name"] for m in data.get("models", []) if "name" in m)

    async def complete(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> Completion:
        base = (base_url or "").rstrip("/")
        body = self._body(model, messages, temperature, max_tokens, json_schema, stream=False)
        data = await _post_json(f"{base}/api/chat", {}, body)
        try:
            return Completion(
                data["message"]["content"],
                int(data.get("prompt_eval_count", 0)),
                int(data.get("eval_count", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc

    async def stream(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> AsyncIterator[str | Completion]:
        base = (base_url or "").rstrip("/")
        body = self._body(model, messages, temperature, max_tokens, json_schema, stream=True)
        parts: list[str] = []
        tokens_in = tokens_out = 0
        async for line in _stream_lines(f"{base}/api/chat", {}, body):  # newline-delimited JSON
            event = _json_line(line)
            try:
                piece = (event.get("message") or {}).get("content")
                if piece:
                    parts.append(piece)
                    yield piece
                if event.get("done"):
                    tokens_in = int(event.get("prompt_eval_count", 0))
                    tokens_out = int(event.get("eval_count", 0))
            except (AttributeError, TypeError, ValueError) as exc:
                raise _bad_shape() from exc
        yield Completion("".join(parts), tokens_in, tokens_out)

    async def embed(
        self, *, base_url: str | None, api_key: str | None, model: str, texts: list[str]
    ) -> Embeddings:
        base = (base_url or "").rstrip("/")
        data = await _post_json(f"{base}/api/embed", {}, {"model": model, "input": texts})
        try:
            vectors = [[float(x) for x in v] for v in data["embeddings"]]
            tokens = int(data.get("prompt_eval_count", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc
        if len(vectors) != len(texts):
            raise _bad_shape()
        return Embeddings(vectors, tokens)


ADAPTERS: dict[str, ProviderAdapter] = {
    "openai": OpenAIAdapter(),
    "openai_compatible": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "ollama": OllamaAdapter(),
}
