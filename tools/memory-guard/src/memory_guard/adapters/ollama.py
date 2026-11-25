"""Ollama loaded-model list: `GET /api/ps` on the endpoint from settings."""

from __future__ import annotations

from datetime import datetime

import httpx
from pydantic import BaseModel, ValidationError

from memory_guard.domain.errors import ProbeError
from memory_guard.domain.models import LoadedModel


class _PsModel(BaseModel):
    name: str
    size_vram: int
    expires_at: datetime


class _PsResponse(BaseModel):
    models: list[_PsModel]


class OllamaPsProbe:
    def __init__(self, base_url: str | None, timeout_s: float, client: httpx.Client | None = None) -> None:
        self._url, self._timeout, self._client = base_url, timeout_s, client

    def loaded_models(self) -> list[LoadedModel]:
        if not self._url:
            raise ProbeError("MEMORY_GUARD_OLLAMA_URL is not set")
        endpoint = self._url.rstrip("/") + "/api/ps"
        try:
            if self._client is not None:
                response = self._client.get(endpoint, timeout=self._timeout)
            else:
                response = httpx.get(endpoint, timeout=self._timeout)
            response.raise_for_status()
            parsed = _PsResponse.model_validate_json(response.content)
        except httpx.HTTPError as exc:
            raise ProbeError(f"Ollama /api/ps unreachable: {type(exc).__name__}: {exc}") from exc
        except ValidationError as exc:
            raise ProbeError(
                f"Ollama /api/ps answered an unexpected shape: {exc.error_count()} invalid field(s)"
            ) from exc
        return [LoadedModel(m.name, m.size_vram, m.expires_at) for m in parsed.models]
