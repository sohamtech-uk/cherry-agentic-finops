"""Deterministic (non-LLM) table extraction for fund bank-statement PDFs.

Unlike the capital-call notice (free-form text, handled by ``GeminiCapitalCallExtractor``), a bank
statement is a machine-generated tabular document with a consistent per-bank layout. Its data can
be lifted with a table-extraction library and validated field-by-field, the same way
``parse_commitment_workbook`` reads Excel with ``openpyxl`` instead of asking an LLM to interpret
it.

This parser targets the two-column "Statement details" header block followed by a
``Bank reference / Customer reference / TRN type / Value date / Credit amount / Debit amount /
Balance / Time / Post date`` transaction table, each transaction row followed by a ``Narrative``
row, with occasional ``Balance as at close`` / ``Balance brought forward`` day-boundary rows on
multi-day statements. It was calibrated against seven real (anonymised) fund bank statements.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.private_markets import FundCashTransaction, money

_TABLE_HEADER_ROW = [
    "Bank reference",
    "Customer reference",
    "TRN type",
    "Value date",
    "Credit amount",
    "Debit amount",
    "Balance",
    "Time",
    "Post date",
]
_BALANCE_MARKER = re.compile(r"^Balance (as at close|brought forward)\b", re.IGNORECASE)
_STATEMENT_DATE_FORMAT = "%d %b %Y"

_HEADER_PATTERNS: dict[str, re.Pattern[str]] = {
    "account_name": re.compile(r"Account name (.+?) Closing ledger balance brought forward"),
    "opening_balance": re.compile(
        r"Closing ledger balance brought forward ([\d,]+\.\d{2}|\d+)"
    ),
    "account_number": re.compile(r"Account number (\S+) From"),
    "bank_name": re.compile(r"Bank name (.+?) Closing available balance brought forward"),
    "currency": re.compile(r"Currency (\S+) From"),
    "location": re.compile(r"Location (.+?) Current ledger balance"),
    "current_balance": re.compile(r"Current ledger balance ([\d,]+\.\d{2}|\d+)"),
    "bic": re.compile(r"BIC (\S+) As at"),
    "iban": re.compile(r"IBAN (\S+) Current available balance"),
    "account_status": re.compile(r"Account status (.+?) As at"),
    "account_type": re.compile(r"Account type (.+?) Specified date range"),
    "period": re.compile(r"Specified date range (.+?) to (.+)"),
}


class BankStatementHeader(BaseModel):
    account_name: str | None = None
    account_number: str | None = None
    bank_name: str | None = None
    currency: str = "GBP"
    location: str | None = None
    bic: str | None = None
    iban: str | None = None
    account_status: str | None = None
    account_type: str | None = None
    period_from: date | None = None
    period_to: date | None = None
    opening_balance: Decimal | None = None
    current_balance: Decimal | None = None


class BankStatementTransaction(BaseModel):
    bank_reference: str | None = None
    customer_reference: str | None = None
    trn_type: str | None = None
    value_date: date
    post_date: date | None = None
    time: str | None = None
    credit_amount: Decimal | None = None
    debit_amount: Decimal | None = None
    balance: Decimal
    narrative: str = ""

    @model_validator(mode="after")
    def _require_one_amount(self) -> BankStatementTransaction:
        if self.credit_amount is None and self.debit_amount is None:
            raise ValueError("Transaction row has neither a credit nor a debit amount.")
        return self


class BankStatement(BaseModel):
    source_file: str
    header: BankStatementHeader
    transactions: list[BankStatementTransaction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _statement_date(raw: Any) -> date | None:
    text = _clean_text(raw)
    if not text:
        return None
    try:
        return datetime.strptime(text, _STATEMENT_DATE_FORMAT).date()
    except ValueError:
        return None


def _clean_amount(raw: Any) -> Decimal | None:
    text = _clean_text(raw)
    if not text:
        return None
    return money(text.replace(",", ""))


def _parse_header(header_text: str) -> tuple[BankStatementHeader, list[str]]:
    warnings: list[str] = []
    values: dict[str, Any] = {}
    for field, pattern in _HEADER_PATTERNS.items():
        match = pattern.search(header_text)
        if not match:
            warnings.append(f"Statement header field {field!r} was not found.")
            continue
        if field == "period":
            values["period_from"] = _statement_date(match.group(1))
            values["period_to"] = _statement_date(match.group(2))
        elif field in {"opening_balance", "current_balance"}:
            values[field] = _clean_amount(match.group(1))
        else:
            values[field] = _clean_text(match.group(1))

    header = BankStatementHeader(
        account_name=values.get("account_name"),
        account_number=values.get("account_number"),
        bank_name=values.get("bank_name"),
        currency=(values.get("currency") or "GBP").upper(),
        location=values.get("location"),
        bic=values.get("bic"),
        iban=values.get("iban"),
        account_status=values.get("account_status"),
        account_type=values.get("account_type"),
        period_from=values.get("period_from"),
        period_to=values.get("period_to"),
        opening_balance=values.get("opening_balance"),
        current_balance=values.get("current_balance"),
    )
    return header, warnings


def _row_to_transaction(row: list[Any]) -> BankStatementTransaction:
    cells = (list(row) + [None] * (9 - len(row)))[:9]
    (
        bank_reference,
        customer_reference,
        trn_type,
        value_date,
        credit,
        debit,
        balance,
        time_,
        post_date,
    ) = cells
    parsed_value_date = _statement_date(value_date)
    if parsed_value_date is None:
        raise ValueError(f"could not parse value date {value_date!r}")
    return BankStatementTransaction(
        bank_reference=_clean_text(bank_reference) or None,
        customer_reference=_clean_text(customer_reference) or None,
        trn_type=_clean_text(trn_type) or None,
        value_date=parsed_value_date,
        post_date=_statement_date(post_date),
        time=_clean_text(time_) or None,
        credit_amount=_clean_amount(credit),
        debit_amount=_clean_amount(debit),
        balance=_clean_amount(balance) or Decimal("0"),
    )


def _rows_to_transactions(
    rows: list[list[Any]],
) -> tuple[list[BankStatementTransaction], list[str]]:
    """Turn a pdfplumber-style transaction table into typed rows.

    ``rows`` alternates a data row with a following ``Narrative`` row, is missing narratives for
    nothing else, repeats the column header once per page, and occasionally inserts a
    ``Balance as at close`` / ``Balance brought forward`` marker row with no narrative on multi-day
    statements. All three shapes must be handled, not just the common case.
    """

    transactions: list[BankStatementTransaction] = []
    warnings: list[str] = []
    index = 0
    total = len(rows)
    while index < total:
        row = rows[index]
        first_cell = _clean_text(row[0] if row else None)

        if row == _TABLE_HEADER_ROW:
            index += 1
            continue
        if _BALANCE_MARKER.match(first_cell):
            index += 1
            continue
        if first_cell == "Narrative":
            warnings.append(f"Unexpected narrative row at {index} with no preceding data row.")
            index += 1
            continue

        narrative = ""
        consumed = 1
        next_row = rows[index + 1] if index + 1 < total else None
        next_first_cell = _clean_text(next_row[0]) if next_row else ""
        if next_first_cell == "Narrative":
            narrative = _clean_text(next_row[1]) if next_row and len(next_row) > 1 else ""
            consumed = 2
        else:
            warnings.append(f"Transaction row {index} has no narrative line.")

        try:
            transaction = _row_to_transaction(row)
            transaction.narrative = narrative
            transactions.append(transaction)
        except ValueError as exc:
            warnings.append(f"Could not parse transaction row {index}: {exc}")

        index += consumed

    return transactions, warnings


def parse_bank_statement_pdf(content: bytes, filename: str = "statement.pdf") -> BankStatement:
    """Deterministically parse a bank-statement PDF's header and transaction table.

    Args:
        content: Raw PDF bytes.
        filename: Original filename, carried through for warnings and evidence.
    """

    if not content:
        raise ValueError("The uploaded bank statement is empty.")
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install pdfplumber to process bank statement PDFs.") from exc

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        if not pdf.pages:
            raise ValueError(f"{filename!r} has no pages.")
        header_text = (pdf.pages[0].extract_text() or "").split("Bank reference")[0]
        rows: list[list[Any]] = []
        for page in pdf.pages:
            for table in page.extract_tables():
                rows.extend(table)

    if not rows:
        raise ValueError(
            f"{filename!r} contains no transaction table. It may be a scanned image with no text "
            "layer."
        )

    header, header_warnings = _parse_header(header_text)
    transactions, row_warnings = _rows_to_transactions(rows)
    if not transactions:
        raise ValueError(f"{filename!r} produced no parsable transaction rows.")

    return BankStatement(
        source_file=filename,
        header=header,
        transactions=transactions,
        warnings=[*header_warnings, *row_warnings],
    )


def to_fund_cash_transactions(statement: BankStatement) -> list[FundCashTransaction]:
    """Map parsed statement rows onto Cherry's existing cash-transaction model.

    Reuses ``FundCashTransaction`` so bank-statement-derived cash slots into the same deterministic
    matching logic (``app.private_markets_strict``) as JSON-fed cash, without a separate code path.
    """

    account_key = statement.header.account_number or statement.header.account_name or "account"
    currency = statement.header.currency or "GBP"
    results: list[FundCashTransaction] = []
    for position, transaction in enumerate(statement.transactions, start=1):
        is_credit = (transaction.credit_amount or Decimal("0")) > 0
        amount = transaction.credit_amount if is_credit else transaction.debit_amount
        results.append(
            FundCashTransaction(
                transaction_id=f"{account_key}-{transaction.value_date.isoformat()}-{position:04d}",
                booking_date=transaction.value_date,
                direction="credit" if is_credit else "debit",
                amount=amount if amount is not None else Decimal("0"),
                currency=currency,
                counterparty=transaction.customer_reference,
                reference=transaction.bank_reference,
                description=transaction.narrative,
                status="BOOKED",
            )
        )
    return results
