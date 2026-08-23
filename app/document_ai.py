from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.models import DocumentExtraction

logger = logging.getLogger(__name__)


class GeminiUnavailable(RuntimeError):
    pass


EXTRACTION_INSTRUCTION = """
You are the document-understanding specialist inside Cherry Agent, an autonomous finance-operations
system for UK small businesses and community organisations.

Extract only information that is visible in the supplied invoice, receipt or credit note. Never
invent a supplier, reference, date, amount, VAT value or currency. Use null for unavailable optional
fields and add a concise warning when data is ambiguous. All money fields must be numeric and must
use the document currency. Suggest a conservative UK bookkeeping category and VAT treatment, but do
not claim tax advice. Confidence is an integer from 0 to 100 reflecting the reliability of the
extraction, not the visual quality alone.
""".strip()


class GeminiDocumentExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def extract(self, content: bytes, mime_type: str, filename: str) -> DocumentExtraction:
        if not self._settings.google_ready:
            raise GeminiUnavailable(
                "Gemini is not configured. Set GOOGLE_CLOUD_PROJECT for Vertex AI "
                "or GOOGLE_API_KEY."
            )
        if not content:
            raise ValueError("The uploaded document is empty.")

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - exercised only in a reduced install
            raise GeminiUnavailable("Install google-genai to process real documents.") from exc

        self._settings.configure_google_environment()
        client = genai.Client()
        async_client = client.aio
        try:
            response = await async_client.models.generate_content(
                model=self._settings.gemini_model,
                contents=[
                    types.Part.from_text(
                        text=(
                            f"Extract the finance data from {filename!r}. Return only "
                            "the structured response required by the schema."
                        )
                    ),
                    types.Part.from_bytes(data=content, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=EXTRACTION_INSTRUCTION,
                    response_mime_type="application/json",
                    response_json_schema=DocumentExtraction.model_json_schema(),
                ),
            )
        finally:
            await async_client.aclose()

        if not response.text:
            raise ValueError("Gemini returned no document extraction.")
        try:
            payload: dict[str, Any] = json.loads(response.text)
            payload["source"] = "gemini"
            return DocumentExtraction.model_validate(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.exception("Gemini returned an invalid structured extraction")
            raise ValueError("Gemini returned an invalid structured extraction.") from exc
