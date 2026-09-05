from __future__ import annotations

from typing import Any, cast

import httpx

from app.config import Settings


class CherryMoneyConnector:
    """Opt-in connector for the existing Cherry Money Laravel API.

    FundOps uses Cherry Money as a financial system of record only when an API URL and token are
    explicitly configured. Read-only methods target the authenticated WebMCP production bridge.
    The legacy write helper remains available for backwards compatibility but is never called by the
    private-markets workflow.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.cherry_money_api_url or "").rstrip("/")
        self._token = (
            settings.cherry_money_api_token.get_secret_value()
            if settings.cherry_money_api_token
            else None
        )

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._token)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise RuntimeError("Cherry Money API integration is not configured.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        """Support CHERRY_MONEY_API_URL with or without a trailing /api prefix."""

        normalized_path = path if path.startswith("/") else f"/{path}"
        if self._base_url.endswith("/api") and normalized_path.startswith("/api/"):
            normalized_path = normalized_path[4:]
        return f"{self._base_url}{normalized_path}"

    async def status(self) -> dict[str, Any]:
        """Return non-secret Cherry Money bridge capability status."""

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                self._url("/api/webmcp/status"),
                headers=self._headers(),
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

    async def finance_snapshot(self, *, limit: int = 50) -> dict[str, Any]:
        """Read a bounded company-scoped finance projection from Cherry Money.

        The server-to-server request deliberately sends no browser Origin header. Cherry Money's
        bridge permits authenticated server-side verification while retaining its browser-origin
        guard for browser clients.
        """

        safe_limit = max(1, min(100, limit))
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(
                self._url("/api/webmcp/bootstrap"),
                params={"limit": safe_limit},
                headers=self._headers(),
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

    async def create_expense(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Legacy explicit write helper; not used by FundOps/private-markets workflows."""

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                self._url("/api/expenseAdd"),
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
