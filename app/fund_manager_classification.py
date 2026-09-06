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
from app.fund_reconciliation import parse_cash_balances, parse_positions, parse_trades
from app.nav_quality import parse_administrator_nav_summary, parse_side_letter_rules
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
    ("side_letter_rules", frozenset({"investor", "rule"})),
)

# The administrator NAV summary is a single JSON object (not an array of row records like the
# _JSON_KEY_RULES shapes above), so it needs its own top-level-key check rather than the
# array-of-records path _classify_json otherwise follows. Mirrors
# app.nav_quality._REQUIRED_SUMMARY_FIELDS -- kept as a separate literal here (rather than
# importing that private constant) since classification only needs to *recognise* the shape; the
# real strict validator below is what actually accepts or rejects it.
_NAV_SUMMARY_REQUIRED_KEYS = frozenset(
    {
        "legal_entity",
        "period_end",
        "total_assets",
        "total_liabilities",
        "reported_equity",
        "opening_nav",
        "closing_nav",
    }
)


class ClassifiedSource(dict[str, Any]):
    """A structured source record; kept as a plain dict subtype for easy JSON serialisation."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _classify_workbook(content: bytes, file_name: str) -> tuple[str, list[str]]:
    try:
        profile = inspect_workbook(content, file_name)
    except Exception as exc:
        # Corrupt/truncated xlsx members surface as zipfile/XML/KeyError variants from openpyxl,
        # not just ValueError -- this is a classification boundary for untrusted uploads, so any
        # failure here becomes "unknown" rather than a crash.
        return "unknown_workbook", [f"{file_name}: could not read workbook ({exc})."]

    kind = profile["kind"]
    if kind in _WORKBOOK_KIND_MAP:
        return _WORKBOOK_KIND_MAP[kind], []

    sheet_names = {name.strip().casefold() for name in profile.get("sheet_names", [])}
    if any(signal in name for name in sheet_names for signal in _NAV_SHEET_SIGNALS):
        return "nav_workbook", []

    return "unknown_workbook", []


def _classify_document(content: bytes, file_name: str, unknown_type: str) -> tuple[str, list[str]]:
    """Keyword-sniff a PDF, TXT or Markdown document's extracted text. Named unknown_pdf even for
    TXT/MD sources for continuity with the existing recognised-type list; text and markdown
    fixtures/documents are read the same way app.contracts and app.statement_tools already do."""

    mime_type = "application/pdf" if file_name.casefold().endswith(".pdf") else "text/plain"
    try:
        pages = read_document_pages(content, mime_type, file_name)
    except Exception as exc:
        # A malformed PDF can raise pypdf-internal exceptions beyond ValueError; treat any
        # extraction failure as "unreadable" rather than letting it crash the batch.
        return unknown_type, [f"{file_name}: could not read document ({exc})."]

    haystack = " ".join(text for _, text in pages).casefold()
    for detected_type, keywords in _PDF_KEYWORD_RULES:
        if any(keyword in haystack for keyword in keywords):
            return detected_type, []
    return unknown_type, []


def _classify_json(content: bytes, file_name: str) -> tuple[str, list[str]]:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return "unknown_json", [f"{file_name}: invalid JSON ({exc})."]

    if isinstance(payload, dict) and _NAV_SUMMARY_REQUIRED_KEYS.issubset(payload):
        return "nav_summary", []

    if isinstance(payload, list):
        rows: Any = payload
    elif isinstance(payload, dict):
        rows = payload["rules"] if "rules" in payload else next(iter(payload.values()), None)
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
        reader = csv.DictReader(io.StringIO(text))
        keys = {str(key) for key in (reader.fieldnames or [])}
    except UnicodeDecodeError as exc:
        return "unknown_csv", [f"{file_name}: not valid UTF-8 ({exc})."]
    except csv.Error as exc:
        return "unknown_csv", [f"{file_name}: could not parse CSV ({exc})."]

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
    elif lowered.endswith((".pdf", ".txt", ".md")):
        detected_type, warnings = _classify_document(content, file_name, "unknown_pdf")
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


_STRICT_JSON_VALIDATORS = {
    "positions": parse_positions,
    "trades": parse_trades,
    "cash_transactions": parse_cash_balances,
    "side_letter_rules": parse_side_letter_rules,
    # parse_administrator_nav_summary returns a single object, not a list; wrap it so the shared
    # "if not records" empty-check below stays meaningful for every registered validator.
    "nav_summary": lambda content: [parse_administrator_nav_summary(content)],
}


def classify_and_validate_sources(
    files: list[tuple[str, bytes, str | None]],
) -> list[ClassifiedSource]:
    """Classify evidence and accept only sources that pass their input contract.

    Rejected sources remain in the evidence manifest for lineage, but the control-planning agent
    cannot select them. This is the shared agent tool behind both the classification endpoint and
    the integrated analysis flow.
    """

    sources = classify_sources(files)
    for source, (_, content, _) in zip(sources, files, strict=True):
        errors: list[str] = []
        if source["status"] != "processed":
            errors.extend(source["warnings"] or ["No supported evidence type was identified."])
        else:
            validator = _STRICT_JSON_VALIDATORS.get(source["detected_type"])
            if validator is not None and source["filename"].casefold().endswith(".json"):
                try:
                    records = validator(content)
                    if not records:
                        errors.append("The document contains no financial records.")
                except (ValueError, TypeError) as exc:
                    errors.append(f"Schema validation failed: {exc}")

        accepted = not errors
        source["validation_status"] = "accepted" if accepted else "rejected"
        source["validation_errors"] = errors
        source["agent_decision"] = {
            "action": "accept" if accepted else "reject",
            "reason": (
                "Recognised evidence passed its registered deterministic input contract."
                if accepted
                else "Evidence was excluded from control planning because validation failed."
            ),
            "classifier": "fund-manager-classifier-v1",
        }
    return sources
