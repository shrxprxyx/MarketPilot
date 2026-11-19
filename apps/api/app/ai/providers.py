"""Provider adapters (SRS §3.7). Slice 2a only needs credential validation and
model listing; complete/stream/embed are added with the gateway."""
from typing import Any, Protocol

import httpx

TIMEOUT = 10.0


class ProviderError(Exception):
    """Safe-to-show failure message; never contains the API key."""


class ProviderAdapter(Protocol):
    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]: ...


async def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach the provider ({type(exc).__name__}).") from exc
    if resp.status_code in (401, 403):
        raise ProviderError("The provider rejected the credentials.")
    if resp.status_code >= 400:
        raise ProviderError(f"The provider returned HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderError("The provider returned an unexpected response.") from exc
    return data if isinstance(data, dict) else {}


class OpenAIAdapter:
    """OpenAI and any OpenAI-compatible endpoint (GET {base}/models)."""

    default_base = "https://api.openai.com/v1"

    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or self.default_base).rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = await _get_json(f"{base}/models", headers)
        return sorted(m["id"] for m in data.get("data", []) if "id" in m)


class AnthropicAdapter:
    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or "https://api.anthropic.com").rstrip("/")
        headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        data = await _get_json(f"{base}/v1/models", headers)
        return sorted(m["id"] for m in data.get("data", []) if "id" in m)


class OllamaAdapter:
    async def list_models(self, base_url: str | None, api_key: str | None) -> list[str]:
        base = (base_url or "").rstrip("/")
        data = await _get_json(f"{base}/api/tags", {})
        return sorted(m["name"] for m in data.get("models", []) if "name" in m)


ADAPTERS: dict[str, ProviderAdapter] = {
    "openai": OpenAIAdapter(),
    "openai_compatible": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "ollama": OllamaAdapter(),
}
