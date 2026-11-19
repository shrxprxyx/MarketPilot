"""Provider adapters (SRS §3.7): credential test / model listing and chat
completion with each provider's native structured-output mechanism (FR-BYOM-07).
stream() and embed() are added with the RAG work."""
import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

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


async def _request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = TIMEOUT,
) -> dict[str, Any]:
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


def _bad_shape() -> ProviderError:
    return ProviderError("The provider returned an unexpected response.")


class OpenAIAdapter:
    """OpenAI and any OpenAI-compatible endpoint."""

    default_base = "https://api.openai.com/v1"

    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or self.default_base).rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = await _get_json(f"{base}/models", headers)
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
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
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
        data = await _post_json(f"{base}/chat/completions", headers, body)
        try:
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            return Completion(
                text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc


class AnthropicAdapter:
    default_base = "https://api.anthropic.com"

    def _headers(self, api_key: str | None) -> dict[str, str]:
        return {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}

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
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [m for m in messages if m["role"] != "system"],
        }
        if system:
            body["system"] = system
        if json_schema is not None:
            # Native structured output: force a tool call whose input is the JSON.
            body["tools"] = [
                {
                    "name": "respond",
                    "description": "Return the answer.",
                    "input_schema": json_schema,
                }
            ]
            body["tool_choice"] = {"type": "tool", "name": "respond"}
        data = await _post_json(f"{base}/v1/messages", self._headers(api_key), body)
        try:
            blocks = data["content"]
            if json_schema is not None:
                text = json.dumps(next(b["input"] for b in blocks if b.get("type") == "tool_use"))
            else:
                text = "".join(b["text"] for b in blocks if b.get("type") == "text")
            usage = data.get("usage", {})
            return Completion(
                text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            )
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise _bad_shape() from exc


class OllamaAdapter:
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
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_schema is not None:
            body["format"] = json_schema  # Ollama's native structured output
        data = await _post_json(f"{base}/api/chat", {}, body)
        try:
            return Completion(
                data["message"]["content"],
                int(data.get("prompt_eval_count", 0)),
                int(data.get("eval_count", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _bad_shape() from exc


ADAPTERS: dict[str, ProviderAdapter] = {
    "openai": OpenAIAdapter(),
    "openai_compatible": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "ollama": OllamaAdapter(),
}
