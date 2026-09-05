from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

from app.config import Settings


class FundOpsStudioUnavailable(RuntimeError):
    """Raised when the optional FundOps Agent Studio service cannot be reached."""


class FundOpsStudioConnector:
    """Server-to-server client for the FundOps Agent Studio microservice.

    Production deployments can use Cloud Run IAM by configuring FUNDOPS_STUDIO_AUDIENCE. A static
    bearer token is also supported for local or non-GCP environments. The client never sends Cherry
    Money credentials to Agent Studio.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.fundops_studio_api_url or "").rstrip("/")
        self._audience = (settings.fundops_studio_audience or "").strip() or None
        self._token = (
            settings.fundops_studio_api_token.get_secret_value().strip()
            if settings.fundops_studio_api_token
            else None
        )
        self._timeout = settings.fundops_studio_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def _url(self, path: str) -> str:
        if not self.configured:
            raise FundOpsStudioUnavailable("FundOps Agent Studio URL is not configured.")
        return f"{self._base_url}/{path.lstrip('/')}"

    def _fetch_cloud_run_identity_token(self) -> str:
        if not self._audience:
            raise FundOpsStudioUnavailable("FundOps Agent Studio audience is not configured.")
        try:
            from google.auth.transport.requests import Request  # type: ignore[import-untyped]
            from google.oauth2 import id_token  # type: ignore[import-untyped]

            token = id_token.fetch_id_token(Request(), self._audience)
        except Exception as exc:  # pragma: no cover - requires GCP runtime metadata
            raise FundOpsStudioUnavailable(
                "Unable to obtain a Cloud Run identity token for FundOps Agent Studio."
            ) from exc
        if not token:
            raise FundOpsStudioUnavailable("Cloud Run identity token was empty.")
        return str(token)

    async def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif self._audience:
            token = await asyncio.to_thread(self._fetch_cloud_run_identity_token)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    self._url("/integration/cherry/health"),
                    headers=await self._headers(),
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
        except FundOpsStudioUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise FundOpsStudioUnavailable("FundOps Agent Studio health check failed.") from exc

    async def analyse_capital_call_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url("/integration/cherry/capital-call"),
                    json=payload,
                    headers=await self._headers(),
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
        except FundOpsStudioUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise FundOpsStudioUnavailable("FundOps Agent Studio analysis failed.") from exc
