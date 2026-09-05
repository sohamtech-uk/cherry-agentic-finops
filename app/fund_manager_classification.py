"""File classification for the Cherry Fund Manager front door: multiple mixed files in, one
classified source inventory out -- the "canonical data room" a control planner would consume.

This is deliberately the first, narrow slice of the target pipeline:

    multiple files -> classification -> canonical data room -> data quality
    -> agent determines required controls -> position/cash/trade/NAV recon
    -> deterministic exception engine -> agentic investigation -> fund-manager dashboard

Only classification and the source inventory are implemented here. Nothing here decides which
controls to run, and nothing here performs any control itself -- app.nav_quality,
app.fund_reconciliation, app.contracts and app.statement_tools remain the only places that do.

Classification reuses each domain's own detector rather than re-implementing it:
- app.ylookup_datasets.inspect_workbook for XLSX sheet-name/header detection, extended here with a
  NAV-workbook heuristic that module doesn't need for its own (Ylookup-specific) purpose.
- app.contracts.read_document_pages for PDF text, then keyword sniffing -- the same
  extract-text-before-any-classification boundary used everywhere else in this codebase.
- simple top-level key sniffing for JSON/CSV.

An unrecognised file is classified "unknown_*" and flagged for review rather than guessed at:
never fabricate a financial interpretation to avoid returning unknown.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any, Literal

from app.contracts import read_document_pages
from app.ylookup_datasets import inspect_workbook

SourceStatus = Literal["processed", "unknown", "unreadable"]

_WORKBOOK_KIND_MAP = {
    "lp_commitments": "lp_commitments",
    "bank_statement_working": "bank_statement_working_file",
    "investor_gl": "investor_gl",
    "loader_sample": "loader_template",
    "loader_workbook": "loader_template",
}

_NAV_SHEET_SIGNALS = (
    "nav",
    "balance sheet",
    "nav bridge",
    "nav summary",
    "statement of net assets",
)

_PDF_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("capital_call_notice", ("capital call", "drawdown notice", "notice of drawdown")),
    ("lpa", ("limited partnership agreement", "agreement of limited partnership")),
    ("side_letter", ("side letter",)),
    (
        "bank_statement",
        ("statement of account", "sort code", "iban", "account statement", "swift"),
    ),
    (
        "financial_statement",
        ("balance sheet", "statement of operations", "subsequent events", "notes to financial"),
    ),
    ("investor_report", ("investor report", "quarterly report", "capital account statement")),
)

_JSON_KEY_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    ("positions", frozenset({"security_id", "quantity"})),
    ("trades", frozenset({"trade_id", "side"})),
    ("bank_transactions", frozenset({"transaction_id", "booking_date"})),
    ("cash_transactions", frozenset({"account", "currency", "balance"})),
)


class ClassifiedSource(dict[str, Any]):
    """A structured source record; kept as a plain dict subtype for easy JSON serialisation."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _classify_workbook(content: bytes, file_name: str) -> tuple[str, list[str]]:
    try:
        profile = inspect_workbook(content, file_name)
    except ValueError as exc:
        return "unknown_workbook", [str(exc)]

    kind = profile["kind"]
    if kind in _WORKBOOK_KIND_MAP:
        return _WORKBOOK_KIND_MAP[kind], []

    sheet_names = {name.strip().casefold() for name in profile.get("sheet_names", [])}
    if any(signal in name for name in sheet_names for signal in _NAV_SHEET_SIGNALS):
        return "nav_workbook", []

    return "unknown_workbook", []


def _classify_pdf(content: bytes, file_name: str) -> tuple[str, list[str]]:
    try:
        pages = read_document_pages(content, "application/pdf", file_name)
    except ValueError as exc:
        return "unknown_pdf", [str(exc)]

    haystack = " ".join(text for _, text in pages).casefold()
    for detected_type, keywords in _PDF_KEYWORD_RULES:
        if any(keyword in haystack for keyword in keywords):
            return detected_type, []
    return "unknown_pdf", []


def _classify_json(content: bytes, file_name: str) -> tuple[str, list[str]]:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return "unknown_json", [f"{file_name}: invalid JSON ({exc})."]

    if isinstance(payload, list):
        rows: Any = payload
    elif isinstance(payload, dict):
        rows = next(iter(payload.values()), None)
    else:
        rows = None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return "unknown_json", []

    keys = {str(key) for key in rows[0]}
    for detected_type, required_keys in _JSON_KEY_RULES:
        if required_keys.issubset(keys):
            return detected_type, []
    return "unknown_json", []


def _classify_csv(content: bytes, file_name: str) -> tuple[str, list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return "unknown_csv", [f"{file_name}: not valid UTF-8 ({exc})."]

    reader = csv.DictReader(io.StringIO(text))
    keys = {str(key) for key in (reader.fieldnames or [])}
    for detected_type, required_keys in _JSON_KEY_RULES:
        if required_keys.issubset(keys):
            return detected_type, []
    return "unknown_csv", []


def classify_source(content: bytes, file_name: str, content_type: str | None) -> ClassifiedSource:
    """Classify one uploaded file into the target source-type taxonomy.

    Args:
        content: Raw file bytes.
        file_name: Original file name (used for extension-based dispatch).
        content_type: The client-supplied MIME type, kept as metadata only -- never trusted alone.
    """

    lowered = file_name.casefold()
    warnings: list[str] = []
    if not content:
        detected_type, status = "unknown", "unreadable"
        warnings.append(f"{file_name}: file is empty.")
    elif lowered.endswith((".xlsx", ".xls")):
        detected_type, warnings = _classify_workbook(content, file_name)
        status = "processed" if not detected_type.startswith("unknown") else "unknown"
    elif lowered.endswith(".pdf"):
        detected_type, warnings = _classify_pdf(content, file_name)
        status = "processed" if not detected_type.startswith("unknown") else "unknown"
    elif lowered.endswith(".json"):
        detected_type, warnings = _classify_json(content, file_name)
        status = "processed" if not detected_type.startswith("unknown") else "unknown"
    elif lowered.endswith(".csv"):
        detected_type, warnings = _classify_csv(content, file_name)
        status = "processed" if not detected_type.startswith("unknown") else "unknown"
    else:
        detected_type, status = "unknown", "unknown"
        warnings.append(f"{file_name}: unsupported file extension.")

    return ClassifiedSource(
        filename=file_name,
        content_type=content_type,
        detected_type=detected_type,
        status=status,
        sha256=_sha256(content) if content else None,
        warnings=warnings,
    )


def classify_sources(
    files: list[tuple[str, bytes, str | None]],
) -> list[ClassifiedSource]:
    """Classify a batch of uploaded files, assigning each a stable source id.

    Args:
        files: (file_name, content, content_type) tuples in upload order.
    """

    sources = []
    for index, (file_name, content, content_type) in enumerate(files, start=1):
        source = classify_source(content, file_name, content_type)
        source["id"] = f"SRC-{index:02d}"
        sources.append(source)
    return sources
