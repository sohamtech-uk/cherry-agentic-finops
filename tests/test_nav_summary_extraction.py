from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openpyxl import Workbook
from pydantic import SecretStr

from app.config import Settings
from app.document_ai import GeminiUnavailable
from app.nav_summary_extraction import NAVSummaryExtractor, _render_workbook_as_text

_VALID_SUMMARY = {
    "legal_entity": "Fund X",
    "period_end": "2026-06-30",
    "total_assets": 5_000_000,
    "total_liabilities": 150_000,
    "reported_equity": 4_850_000,
    "opening_nav": 4_700_000,
    "contributions": 250_000,
    "distributions": 100_000,
    "income": 10_000,
    "expenses": 10_000,
    "closing_nav": 4_850_000,
}


def _not_configured_settings() -> Settings:
    return Settings(
        google_api_key=None,
        use_vertex_ai=False,
        google_cloud_project=None,
    )


def _configured_settings() -> Settings:
    return Settings(google_api_key=SecretStr("fake-key"), use_vertex_ai=False)


def _mock_genai_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=SimpleNamespace(text=response_text))
    client.aio.aclose = AsyncMock()
    return client


def test_render_workbook_as_text_includes_sheet_name_and_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "NAV Summary"
    sheet.append(["Total Assets", 5_000_000])
    sheet.append(["Total Liabilities", 150_000])
    buffer = io.BytesIO()
    workbook.save(buffer)

    text = _render_workbook_as_text(buffer.getvalue())

    assert "Sheet: NAV Summary" in text
    assert "Total Assets" in text
    assert "5000000" in text


@pytest.mark.asyncio
async def test_extract_raises_gemini_unavailable_when_not_configured() -> None:
    extractor = NAVSummaryExtractor(_not_configured_settings())

    with pytest.raises(GeminiUnavailable):
        await extractor.extract(b"%PDF-1.4 fake", "application/pdf", "nav.pdf")


@pytest.mark.asyncio
async def test_extract_raises_value_error_for_empty_content() -> None:
    extractor = NAVSummaryExtractor(_configured_settings())

    with pytest.raises(ValueError, match="empty"):
        await extractor.extract(b"", "application/pdf", "nav.pdf")


@pytest.mark.asyncio
async def test_extract_pdf_validates_gemini_response_against_schema() -> None:
    extractor = NAVSummaryExtractor(_configured_settings())
    mock_client = _mock_genai_client(json.dumps(_VALID_SUMMARY))

    with patch("google.genai.Client", return_value=mock_client):
        summary = await extractor.extract(b"%PDF-1.4 fake", "application/pdf", "nav.pdf")

    assert summary.legal_entity == "Fund X"
    assert summary.reported_equity == 4_850_000
    mock_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_xlsx_renders_workbook_as_text_before_calling_gemini() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "NAV Summary"
    sheet.append(["Legal Entity", "Fund X"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    extractor = NAVSummaryExtractor(_configured_settings())
    mock_client = _mock_genai_client(json.dumps(_VALID_SUMMARY))

    with patch("google.genai.Client", return_value=mock_client):
        summary = await extractor.extract(
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "nav.xlsx",
        )

    assert summary.legal_entity == "Fund X"
    call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
    sent_text = call_kwargs["contents"][0].text
    assert "Sheet: NAV Summary" in sent_text


@pytest.mark.asyncio
async def test_extract_wraps_invalid_json_as_value_error() -> None:
    extractor = NAVSummaryExtractor(_configured_settings())
    mock_client = _mock_genai_client("not valid json")

    with (
        patch("google.genai.Client", return_value=mock_client),
        pytest.raises(ValueError, match="invalid NAV summary extraction"),
    ):
        await extractor.extract(b"%PDF-1.4 fake", "application/pdf", "nav.pdf")
