from __future__ import annotations

import io
import json

from openpyxl import Workbook
from reportlab.pdfgen import canvas

from app.fund_manager_classification import classify_source, classify_sources


def _xlsx_bytes(sheet_titles: list[str]) -> bytes:
    workbook = Workbook()
    workbook.active.title = sheet_titles[0]
    for title in sheet_titles[1:]:
        workbook.create_sheet(title)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(*lines: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for index, line in enumerate(lines):
        pdf.drawString(100, 750 - index * 20, line)
    pdf.save()
    return buffer.getvalue()


def test_classify_source_detects_nav_workbook_by_sheet_name() -> None:
    source = classify_source(_xlsx_bytes(["NAV Summary"]), "Q2_NAV.xlsx", "application/xlsx")

    assert source["detected_type"] == "nav_workbook"
    assert source["status"] == "processed"


def test_classify_source_detects_investor_gl_workbook() -> None:
    source = classify_source(_xlsx_bytes(["Investor-Level GL"]), "gl.xlsx", None)

    assert source["detected_type"] == "investor_gl"


def test_classify_source_falls_back_to_unknown_workbook() -> None:
    source = classify_source(_xlsx_bytes(["Sheet1"]), "mystery.xlsx", None)

    assert source["detected_type"] == "unknown_workbook"
    assert source["status"] == "unknown"


def test_classify_source_detects_capital_call_pdf() -> None:
    source = classify_source(
        _pdf_bytes("Capital Call Notice", "Drawdown Notice for Fund X"), "call.pdf", None
    )

    assert source["detected_type"] == "capital_call_notice"


def test_classify_source_detects_side_letter_pdf() -> None:
    source = classify_source(
        _pdf_bytes("Side Letter Agreement", "Investor: Acme LP"), "sl.pdf", None
    )

    assert source["detected_type"] == "side_letter"


def test_classify_source_falls_back_to_unknown_pdf() -> None:
    source = classify_source(_pdf_bytes("Just some unrelated text"), "mystery.pdf", None)

    assert source["detected_type"] == "unknown_pdf"
    assert source["status"] == "unknown"


def test_classify_source_detects_positions_json() -> None:
    payload = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    source = classify_source(payload, "positions.json", "application/json")

    assert source["detected_type"] == "positions"


def test_classify_source_detects_trades_json_wrapped_in_object() -> None:
    payload = json.dumps({"trades": [{"trade_id": "T1", "side": "buy"}]}).encode()

    source = classify_source(payload, "trades.json", "application/json")

    assert source["detected_type"] == "trades"


def test_classify_source_rejects_invalid_json() -> None:
    source = classify_source(b"{not json", "broken.json", "application/json")

    assert source["detected_type"] == "unknown_json"
    assert source["warnings"]


def test_classify_source_detects_cash_transactions_csv() -> None:
    payload = b"account,currency,balance\nACC-1,USD,1000\n"

    source = classify_source(payload, "cash.csv", "text/csv")

    assert source["detected_type"] == "cash_transactions"


def test_classify_source_empty_file_is_unreadable() -> None:
    source = classify_source(b"", "empty.xlsx", None)

    assert source["status"] == "unreadable"
    assert source["sha256"] is None


def test_classify_source_unsupported_extension_is_unknown() -> None:
    source = classify_source(b"hello", "notes.docx", None)

    assert source["detected_type"] == "unknown"
    assert source["status"] == "unknown"


def test_classify_sources_assigns_sequential_ids() -> None:
    sources = classify_sources(
        [
            ("a.json", json.dumps([{"security_id": "1", "quantity": 1}]).encode(), None),
            ("b.json", json.dumps([{"trade_id": "1", "side": "buy"}]).encode(), None),
        ]
    )

    assert [source["id"] for source in sources] == ["SRC-01", "SRC-02"]
