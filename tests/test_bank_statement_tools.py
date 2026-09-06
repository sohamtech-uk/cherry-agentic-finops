from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest
from reportlab.pdfgen import canvas

from app.bank_statement_tools import extract_bank_statement_balances


def _pdf_bytes(*lines: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for index, line in enumerate(lines):
        pdf.drawString(100, 750 - index * 20, line)
    pdf.save()
    return buffer.getvalue()


def test_extract_bank_statement_balances_reads_iban_currency_and_closing_balance() -> None:
    statement = _pdf_bytes(
        "Statement of Account",
        "Sort Code 12-34-56",
        "IBAN: GB29NWBK60161331926819",
        "Currency: GBP",
        "Closing Balance: GBP 12,345.67",
        "Statement Date: 2026-06-30",
    )

    balances = extract_bank_statement_balances(statement, "chase_statement.pdf")

    assert len(balances) == 1
    balance = balances[0]
    assert balance.account == "GB29NWBK60161331926819"
    assert balance.currency == "GBP"
    assert balance.balance == Decimal("12345.67")
    assert balance.as_of == date(2026, 6, 30)


def test_extract_bank_statement_balances_without_a_balance_line_raises() -> None:
    statement = _pdf_bytes("Statement of Account", "IBAN: GB29NWBK60161331926819")

    with pytest.raises(ValueError, match="closing/ending/current/available balance"):
        extract_bank_statement_balances(statement, "chase_statement.pdf")


def test_extract_bank_statement_balances_without_an_account_identifier_raises() -> None:
    statement = _pdf_bytes("Statement of Account", "Closing Balance: USD 500.00")

    with pytest.raises(ValueError, match="account number or IBAN"):
        extract_bank_statement_balances(statement, "chase_statement.pdf")
