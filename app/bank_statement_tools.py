"""Deterministic extraction of a bank statement PDF's headline balance into the same
``CashBalance`` shape ``app.fund_reconciliation.reconcile_cash`` already compares an internal
cash-balance export against -- so an actual bank statement can stand in for the "external" side of
cash reconciliation without a new comparison engine.

Text-only, like ``app.statement_tools``: reuses ``app.contracts.read_document_pages`` (plain
``PdfReader.extract_text()``, no table layout), so extraction is limited to whatever labelled
account identifier and closing/available balance a bank places in running text near those labels --
never a transaction-by-transaction ledger. A statement whose account identifier or balance cannot
be located deterministically raises rather than guessing at a figure.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.contracts import read_document_pages
from app.fund_reconciliation import CashBalance

_IBAN_PATTERN = re.compile(r"\bIBAN:?\s*([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b", re.IGNORECASE)
_ACCOUNT_PATTERN = re.compile(
    r"\bAccount\s*(?:Number|No\.?)?:?\s*([A-Za-z0-9][A-Za-z0-9 -]{2,20}[A-Za-z0-9])\b",
    re.IGNORECASE,
)
_CURRENCY_PATTERN = re.compile(r"\bCurrency:?\s*([A-Z]{3})\b", re.IGNORECASE)
_BALANCE_PATTERN = re.compile(
    r"\b(?:Closing|Ending|Current|Available)\s+Balance:?\s*[:\-]?\s*"
    r"([A-Z]{3})?\s*\$?\s*(-?[\d,]+\.\d{2})",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _extract_text(content: bytes, file_name: str) -> str:
    pages = read_document_pages(content, "application/pdf", file_name)
    return "\n".join(text for _, text in pages)


def extract_bank_statement_balances(content: bytes, file_name: str) -> list[CashBalance]:
    """Extract the account identifier, currency and closing/available balance from a bank
    statement's extracted text.

    Raises ``ValueError`` if the balance or the account identifier cannot be located -- this never
    fabricates a figure from an unrecognised statement layout; a failed extraction surfaces as a
    "deterministic control could not execute" exception upstream rather than a silent pass.
    """

    text = _extract_text(content, file_name)

    balance_match = _BALANCE_PATTERN.search(text)
    if not balance_match:
        raise ValueError(
            f"{file_name}: could not locate a closing/ending/current/available balance line in "
            "the statement text."
        )

    account_match = _IBAN_PATTERN.search(text)
    if not account_match:
        candidate = _ACCOUNT_PATTERN.search(text)
        if candidate and any(character.isdigit() for character in candidate.group(1)):
            account_match = candidate
    if not account_match:
        raise ValueError(f"{file_name}: could not locate an account number or IBAN.")

    currency_match = _CURRENCY_PATTERN.search(text)
    currency = balance_match.group(1) or (currency_match.group(1) if currency_match else None)
    date_match = _DATE_PATTERN.search(text)

    return [
        CashBalance(
            fund=Path(file_name).stem,
            account=account_match.group(1).strip(),
            currency=currency or "USD",
            balance=balance_match.group(2).replace(",", ""),
            as_of=date_match.group(1) if date_match else None,
        )
    ]
