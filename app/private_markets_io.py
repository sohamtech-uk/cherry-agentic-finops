from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from app.private_markets import FundCashTransaction


def _rows(payload: Any) -> list[dict[str, Any]]:
    rows: Any
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("transactions")
            or payload.get("cash_transactions")
            or payload.get("fund_cash_transactions")
        )
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValueError(
            "JSON must be an array of transactions or an object containing transactions, "
            "cash_transactions, or fund_cash_transactions."
        )
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Every JSON transaction must be an object.")
    return rows


def _direction(row: dict[str, Any], amount: Any) -> str:
    explicit = str(row.get("direction") or row.get("type") or "").strip().lower()
    if explicit in {"credit", "debit"}:
        return explicit
    try:
        numeric = Decimal(str(amount).replace(",", ""))
    except (InvalidOperation, ValueError):
        return "credit"
    return "debit" if numeric < 0 else "credit"


def parse_cash_json(content: bytes) -> list[FundCashTransaction]:
    """Parse flexible JSON cash exports into Cherry's strict transaction model.

    Accepted shapes are either a top-level array or an object with `transactions`,
    `cash_transactions`, or `fund_cash_transactions`. Common field aliases are normalised, but
    financial validation remains in the Pydantic model and downstream deterministic controls.
    """

    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Fund cash JSON must be valid UTF-8 JSON.") from exc

    transactions: list[FundCashTransaction] = []
    for index, row in enumerate(_rows(payload), start=1):
        raw_amount = row.get("amount_gbp", row.get("amount"))
        transaction_id = row.get("transaction_id") or row.get("id")
        booking_date = row.get("booking_date") or row.get("value_date") or row.get("date")
        if raw_amount in (None, ""):
            raise ValueError(f"JSON transaction {index} is missing amount.")
        if booking_date in (None, ""):
            raise ValueError(f"JSON transaction {index} is missing booking_date/date.")
        if not transaction_id:
            transaction_id = f"json-{index:04d}"

        candidate = {
            "transaction_id": str(transaction_id),
            "booking_date": booking_date,
            "direction": _direction(row, raw_amount),
            "amount": raw_amount,
            "currency": row.get("currency") or "GBP",
            "counterparty": row.get("counterparty") or row.get("merchant_name") or row.get("name"),
            "reference": row.get("reference") or row.get("payment_reference"),
            "description": row.get("description") or row.get("narrative") or "",
            "status": row.get("status") or "BOOKED",
        }
        try:
            transactions.append(FundCashTransaction.model_validate(candidate))
        except ValidationError as exc:
            raise ValueError(f"Invalid JSON transaction {index}: {exc}") from exc
    return transactions
