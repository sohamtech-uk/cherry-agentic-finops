from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class CherryMoneyConnector:
    """Narrow, opt-in connector for the existing Cherry Money Laravel API.

    The hackathon service never writes to production Cherry Money automatically. A caller must
    explicitly invoke a connector method and provide a configured token.
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

    async def create_expense(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Cherry Money API integration is not configured.")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self._base_url}/expenseAdd", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
