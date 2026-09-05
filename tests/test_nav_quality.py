from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.nav_exceptions import group_exceptions_by_root_cause
from app.nav_quality import (
    AdministratorNAVSummary,
    NAVAction,
    SideLetterRule,
    parse_administrator_nav_summary,
    parse_investor_level_gl_workbook,
    parse_side_letter_rules,
    review_nav_quality,
)
from app.nav_review_history import get_nav_review_history_store

client = TestClient(app)


def setup_function() -> None:
    get_nav_review_history_store().clear()


def teardown_function() -> None:
    get_nav_review_history_store().clear()


_GL_HEADER = [None] * 43
_GL_HEADER[1] = "Static Date"
_GL_HEADER[2] = "Static Date"
_GL_HEADER[3] = "Legal Entity"
_GL_HEADER[21] = "Account Type"
_GL_HEADER[22] = "Trans Type"
_GL_HEADER[23] = "GL Date"
_GL_HEADER[24] = "GL Date"
_GL_HEADER[30] = "Legal Entity Currency"
_GL_HEADER[31] = "Amount (Entity Currency)"
_GL_HEADER[35] = "Investor"


def _gl_row(
    entity: str,
    account_type: str,
    trans_type: str,
    gl_date: date,
    amount: float,
    investor: str | None = None,
    *,
    period_start: date = date(2026, 4, 1),
    period_end: date = date(2026, 6, 30),
) -> list[object]:
    row: list[object] = [None] * 43
    row[1] = period_start
    row[2] = period_end
    row[3] = entity
    row[21] = account_type
    row[22] = trans_type
    row[23] = gl_date
    row[24] = gl_date
    row[30] = "USD"
    row[31] = amount
    row[35] = investor
    return row


def _build_gl_workbook(rows: list[list[object]], *, sheet_name: str = "Investor-Level GL") -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(_GL_HEADER)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# Fund X: Assets 5,000,000; Liabilities -150,000 (raw) => flipped 150,000; Capital -4,850,000 raw
# => flipped NAV 4,850,000, split Investor A 3,000,000 / Investor B 1,850,000. Balances to zero.
FUND_X_ROWS = [
    _gl_row("Fund X", "Assets", "Cash Received", date(2026, 3, 1), 5_000_000),
    _gl_row("Fund X", "Liabilities", "Payable: Other", date(2026, 3, 1), -150_000),
    _gl_row("Fund X", "Capital", "Contribution", date(2026, 1, 1), -3_000_000, "Investor A"),
    _gl_row("Fund X", "Capital", "Contribution", date(2026, 1, 1), -1_850_000, "Investor B"),
]


def _clean_summary(**overrides: object) -> AdministratorNAVSummary:
    payload = {
        "legal_entity": "Fund X",
        "period_end": "2026-06-30",
        "currency": "USD",
        "total_assets": 5_000_000,
        "total_liabilities": 150_000,
        "reported_equity": 4_850_000,
        "opening_nav": 4_700_000,
        "contributions": 250_000,
        "distributions": 100_000,
        "investment_movement": 0,
        "income": 10_000,
        "expenses": 10_000,
        "fx_movement": 0,
        "closing_nav": 4_850_000,
        "investor_capital": [
            {"investor": "Investor A", "reported_capital": 3_000_000},
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ],
    }
    payload.update(overrides)
    return AdministratorNAVSummary.model_validate(payload)


def _source_backed_rule(investor: str = "Investor A") -> SideLetterRule:
    return SideLetterRule(
        investor=investor,
        rule="management_fee_offsets_called_capital",
        source="Side Letter §4.2, page 1",
        document_id="CTR-DEMO123",
        document_name="side-letter.pdf",
        section_reference="4.2",
        page_number=1,
        source_excerpt="The management fee shall reduce called capital pound-for-pound.",
        source_sha256="a" * 64,
        effective_date=date(2026, 1, 1),
        explicit_override=True,
    )


# --- GL workbook parsing -------------------------------------------------------------------------


def test_parse_investor_level_gl_workbook_happy_path() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))

    assert ledger.period_start == date(2026, 4, 1)
    assert ledger.period_end == date(2026, 6, 30)
    assert ledger.warnings == []
    assert ledger.balance("Fund X", "Assets", as_of=date(2026, 6, 30)) == 5_000_000
    assert ledger.balance("Fund X", "Liabilities", as_of=date(2026, 6, 30)) == -150_000
    assert ledger.capital_balance("Fund X", as_of=date(2026, 6, 30)) == 4_850_000
    investor_a = ledger.capital_balance("Fund X", as_of=date(2026, 6, 30), investor="Investor A")
    assert investor_a == 3_000_000
    assert set(ledger.investors("Fund X")) == {"Investor A", "Investor B"}


def test_parse_investor_level_gl_workbook_rejects_missing_sheet() -> None:
    with pytest.raises(ValueError, match="Investor-Level GL"):
        parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS, sheet_name="Sheet1"))


def test_parse_investor_level_gl_workbook_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_investor_level_gl_workbook(b"")


def test_parse_investor_level_gl_workbook_rejects_shifted_columns() -> None:
    header = list(_GL_HEADER)
    header[21] = "Something Else"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Investor-Level GL"
    sheet.append(header)
    sheet.append(_gl_row("Fund X", "Assets", "Cash Received", date(2026, 3, 1), 100))
    buffer = io.BytesIO()
    workbook.save(buffer)

    with pytest.raises(ValueError, match="column 21"):
        parse_investor_level_gl_workbook(buffer.getvalue())


def test_parse_investor_level_gl_workbook_warns_on_unclassified_account_type() -> None:
    rows = [*FUND_X_ROWS, _gl_row("Fund X", "Suspense", "Suspense (Credit)", date(2026, 5, 1), 42)]
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(rows))

    assert any("Suspense" in warning for warning in ledger.warnings)


def test_parse_investor_level_gl_workbook_skips_rows_missing_date_or_amount() -> None:
    broken_row = _gl_row("Fund X", "Assets", "Cash Received", date(2026, 3, 1), 100)
    broken_row[23] = None
    broken_row[24] = None
    rows = [*FUND_X_ROWS, broken_row]
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(rows))

    assert any("missing a GL date or amount" in warning for warning in ledger.warnings)
    # the broken row must not have been silently included
    assert ledger.balance("Fund X", "Assets", as_of=date(2026, 6, 30)) == 5_000_000


def test_parse_investor_level_gl_workbook_respects_as_of_date_cutoff() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))

    # Before any posting date (earliest is the 2026-01-01 capital contributions), nothing counts.
    assert ledger.balance("Fund X", "Assets", as_of=date(2025, 12, 31)) == 0
    assert ledger.capital_balance("Fund X", as_of=date(2025, 12, 31)) == 0

    # Between the capital contributions (2026-01-01) and the asset/liability postings
    # (2026-03-01): capital is already booked, assets are not yet.
    assert ledger.balance("Fund X", "Assets", as_of=date(2026, 1, 15)) == 0
    assert ledger.capital_balance("Fund X", as_of=date(2026, 1, 15)) == 4_850_000


# --- Administrator NAV summary / side-letter rule parsing ----------------------------------------


def test_parse_administrator_nav_summary_round_trips_investor_capital() -> None:
    payload = {
        "legal_entity": "Fund X",
        "period_end": "2026-06-30",
        "total_assets": 5_000_000,
        "total_liabilities": 150_000,
        "reported_equity": 4_850_000,
        "opening_nav": 4_700_000,
        "closing_nav": 4_850_000,
        "contributions": 250_000,
        "investor_capital": [
            {"investor": "Investor A", "reported_capital": 3_000_000, "management_fee": 125_000}
        ],
    }
    summary = parse_administrator_nav_summary(json.dumps(payload).encode())

    assert summary.legal_entity == "Fund X"
    assert summary.currency == "USD"
    assert summary.investor_capital[0].management_fee == 125_000


def test_parse_administrator_nav_summary_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_administrator_nav_summary(b"")


def test_parse_administrator_nav_summary_rejects_missing_required_field() -> None:
    payload = {"legal_entity": "Fund X", "period_end": "2026-06-30"}
    with pytest.raises(ValueError, match="total_assets"):
        parse_administrator_nav_summary(json.dumps(payload).encode())


def test_parse_side_letter_rules_accepts_object_shape() -> None:
    payload = {"rules": [{"investor": "Investor A", "rule": "x", "source": "Side Letter"}]}
    rules = parse_side_letter_rules(json.dumps(payload).encode())
    assert rules == [SideLetterRule(investor="Investor A", rule="x", source="Side Letter")]


def test_parse_side_letter_rules_accepts_bare_array() -> None:
    payload = [{"investor": "Investor A", "rule": "x"}]
    rules = parse_side_letter_rules(json.dumps(payload).encode())
    assert len(rules) == 1


def test_parse_side_letter_rules_empty_content_returns_no_rules() -> None:
    assert parse_side_letter_rules(b"") == []


# --- review_nav_quality: summary alone (no ledger, no rules) -------------------------------------


def test_review_nav_quality_clean_summary_is_ready_to_submit() -> None:
    report = review_nav_quality(_clean_summary())

    assert report.action == NAVAction.READY_TO_SUBMIT
    assert report.exceptions_open == 0
    codes = {finding.code for finding in report.findings}
    assert "balance_sheet.footing_valid" in codes
    assert "nav_bridge.foots" in codes


def test_review_nav_quality_flags_balance_sheet_footing_mismatch() -> None:
    summary = _clean_summary(reported_equity=4_800_000)
    report = review_nav_quality(summary)

    assert report.action == NAVAction.RETURN_TO_ADMINISTRATOR
    codes = {finding.code for finding in report.findings}
    assert "balance_sheet.footing_mismatch" in codes
    assert any(item.code == "resolve_balance_sheet" for item in report.work_items)


def test_review_nav_quality_flags_nav_bridge_that_does_not_foot() -> None:
    summary = _clean_summary(closing_nav=4_900_000)
    report = review_nav_quality(summary)

    assert report.action == NAVAction.RETURN_TO_ADMINISTRATOR
    codes = {finding.code for finding in report.findings}
    assert "nav_bridge.does_not_foot" in codes
    assert any(item.code == "resolve_nav_bridge" for item in report.work_items)


# --- review_nav_quality: with an independent source ledger ---------------------------------------


def test_review_nav_quality_matches_ledger_when_reported_figures_are_correct() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    report = review_nav_quality(_clean_summary(), ledger=ledger)

    codes = {finding.code for finding in report.findings}
    assert "balance_sheet.matches_ledger" in codes
    assert "nav.independent_recalculation_valid" in codes
    assert "investor_capital.matches_ledger" in codes  # Investor B, no side-letter rule
    assert report.action == NAVAction.READY_TO_SUBMIT
    assert report.balance_sheet.ledger_assets == 5_000_000
    assert report.nav_bridge.ledger_closing_nav == 4_850_000


def test_review_nav_quality_flags_balance_sheet_ledger_mismatch() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    summary = _clean_summary(total_liabilities=100_000, reported_equity=4_900_000)
    report = review_nav_quality(summary, ledger=ledger)

    codes = {finding.code for finding in report.findings}
    assert "balance_sheet.footing_valid" in codes  # internally consistent...
    assert "balance_sheet.ledger_mismatch" in codes  # ...but wrong vs. the ledger
    assert report.action == NAVAction.RETURN_TO_ADMINISTRATOR


def test_review_nav_quality_flags_independent_recalculation_mismatch() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    # Bridge foots internally (4,955,000) but disagrees with the ledger-derived NAV (4,850,000).
    summary = _clean_summary(closing_nav=4_955_000, contributions=355_000)
    report = review_nav_quality(summary, ledger=ledger)

    codes = {finding.code for finding in report.findings}
    assert "nav_bridge.foots" in codes
    assert "nav.independent_recalculation_mismatch" in codes


def test_review_nav_quality_flags_investor_capital_ledger_mismatch() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    summary = _clean_summary(
        investor_capital=[
            {"investor": "Investor A", "reported_capital": 2_500_000},
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ]
    )
    report = review_nav_quality(summary, ledger=ledger)

    codes = {finding.code for finding in report.findings}
    assert "investor_capital.ledger_mismatch" in codes
    assert any(item.code == "resolve_investor_capital" for item in report.work_items)
    investor_a = next(c for c in report.investor_reconciliation if c.investor == "Investor A")
    assert investor_a.ledger_capital == 3_000_000


# --- review_nav_quality: side-letter rules --------------------------------------------------------


def test_review_nav_quality_side_letter_rule_correctly_applied() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    summary = _clean_summary(
        investor_capital=[
            {
                "investor": "Investor A",
                "reported_capital": 2_875_000,  # 3,000,000 ledger - 125,000 management fee
                "management_fee": 125_000,
            },
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ]
    )
    rules = [_source_backed_rule()]
    report = review_nav_quality(summary, ledger=ledger, side_letter_rules=rules)

    codes = {finding.code for finding in report.findings}
    assert "side_letter.rule_applied" in codes
    assert report.action == NAVAction.READY_TO_SUBMIT
    investor_a = next(c for c in report.investor_reconciliation if c.investor == "Investor A")
    assert investor_a.rule_adjusted_expected == 2_875_000


def test_review_nav_quality_side_letter_rule_violation() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    summary = _clean_summary(
        investor_capital=[
            {
                "investor": "Investor A",
                "reported_capital": 3_000_000,  # forgot to apply the management-fee offset
                "management_fee": 125_000,
            },
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ]
    )
    rules = [_source_backed_rule()]
    report = review_nav_quality(summary, ledger=ledger, side_letter_rules=rules)

    codes = {finding.code for finding in report.findings}
    assert "side_letter.rule_violation" in codes
    assert report.action == NAVAction.RETURN_TO_ADMINISTRATOR
    violation = next(f for f in report.findings if f.code == "side_letter.rule_violation")
    assert violation.expected == "2875000.00"


def test_review_nav_quality_warns_when_management_fee_missing_for_rule() -> None:
    summary = _clean_summary(
        investor_capital=[
            {"investor": "Investor A", "reported_capital": 3_000_000},
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ]
    )
    rules = [_source_backed_rule()]
    report = review_nav_quality(summary, side_letter_rules=rules)

    codes = {finding.code for finding in report.findings}
    assert "side_letter.missing_management_fee" in codes
    assert report.action == NAVAction.NEEDS_REVIEW
    assert any(item.code == "obtain_management_fee" for item in report.work_items)


def test_review_nav_quality_does_not_apply_rule_without_source_locator() -> None:
    summary = _clean_summary(
        investor_capital=[
            {
                "investor": "Investor A",
                "reported_capital": 3_000_000,
                "management_fee": 125_000,
            }
        ]
    )
    rules = [
        SideLetterRule(
            investor="Investor A",
            rule="management_fee_offsets_called_capital",
            source="Side Letter §4.2",
            effective_date=date(2026, 1, 1),
            explicit_override=True,
        )
    ]

    report = review_nav_quality(summary, side_letter_rules=rules)

    assert report.action == NAVAction.NEEDS_REVIEW
    assert any(finding.code == "side_letter.evidence_incomplete" for finding in report.findings)
    assert not any(finding.code == "side_letter.rule_applied" for finding in report.findings)


def test_review_nav_quality_does_not_apply_future_rule() -> None:
    summary = _clean_summary(
        investor_capital=[
            {
                "investor": "Investor A",
                "reported_capital": 3_000_000,
                "management_fee": 125_000,
            }
        ]
    )
    rule = _source_backed_rule()
    rule.effective_date = date(2027, 1, 1)

    report = review_nav_quality(summary, side_letter_rules=[rule])

    assert report.action == NAVAction.NEEDS_REVIEW
    finding = next(
        item for item in report.findings if item.code == "side_letter.evidence_incomplete"
    )
    assert "not yet effective" in finding.detail


def test_review_nav_quality_routes_duplicate_investor_rules_to_review() -> None:
    summary = _clean_summary(
        investor_capital=[
            {
                "investor": "Investor A",
                "reported_capital": 3_000_000,
                "management_fee": 125_000,
            }
        ]
    )

    report = review_nav_quality(
        summary,
        side_letter_rules=[_source_backed_rule(), _source_backed_rule()],
    )

    assert report.action == NAVAction.NEEDS_REVIEW
    finding = next(
        item for item in report.findings if item.code == "side_letter.evidence_incomplete"
    )
    assert "Multiple investor-specific rules" in finding.detail


# --- router -----------------------------------------------------------------------------------


def test_nav_quality_health_declares_the_contract() -> None:
    response = client.get("/api/nav-quality/health")

    assert response.status_code == 200
    body = response.json()
    assert body["input_required"] == {
        "nav_summary": True,
        "source_ledger": False,
        "side_letter_rules": False,
        "use_contract_documents": False,
    }
    assert "balance_sheet_footing" in body["checks"]


def test_review_endpoint_accepts_summary_only() -> None:
    summary_bytes = json.dumps(
        {
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
    ).encode()

    response = client.post(
        "/api/nav-quality/review",
        files={"nav_summary": ("nav-summary.json", summary_bytes, "application/json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["legal_entity"] == "Fund X"
    assert body["ledger_supplied"] is False
    assert body["review"]["action"] == "ready_to_submit"
    assert body["evidence"]["input_sha256"]["source_ledger"] is None


def test_review_endpoint_accepts_summary_and_ledger_and_rules() -> None:
    summary_bytes = json.dumps(
        {
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
            "investor_capital": [
                {
                    "investor": "Investor A",
                    "reported_capital": 2_875_000,
                    "management_fee": 125_000,
                },
                {"investor": "Investor B", "reported_capital": 1_850_000},
            ],
        }
    ).encode()
    ledger_bytes = _build_gl_workbook(FUND_X_ROWS)
    rules_bytes = json.dumps(
        [
            {
                "investor": "Investor A",
                "rule": "management_fee_offsets_called_capital",
                "source": "Side Letter §4.2, page 1",
                "document_id": "CTR-DEMO123",
                "document_name": "side-letter.pdf",
                "section_reference": "4.2",
                "page_number": 1,
                "source_excerpt": "The fee shall reduce called capital pound-for-pound.",
                "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "effective_date": "2026-01-01",
                "explicit_override": True,
            }
        ]
    ).encode()

    response = client.post(
        "/api/nav-quality/review",
        files={
            "nav_summary": ("nav-summary.json", summary_bytes, "application/json"),
            "source_ledger": (
                "source-ledger.xlsx",
                ledger_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "side_letter_rules": ("rules.json", rules_bytes, "application/json"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ledger_supplied"] is True
    assert body["side_letter_rules_supplied"] is True
    assert body["review"]["action"] == "ready_to_submit"
    finding_codes = {f["code"] for f in body["review"]["findings"]}
    assert "side_letter.rule_applied" in finding_codes


def test_review_endpoint_rejects_non_json_summary_extension() -> None:
    response = client.post(
        "/api/nav-quality/review",
        files={"nav_summary": ("nav-summary.txt", b"{}", "text/plain")},
    )
    assert response.status_code == 415


def test_review_endpoint_rejects_invalid_summary_json() -> None:
    response = client.post(
        "/api/nav-quality/review",
        files={"nav_summary": ("nav-summary.json", b"not json", "application/json")},
    )
    assert response.status_code == 422


def test_review_endpoint_rejects_corrupt_source_ledger_with_422_not_500() -> None:
    """Regression test: openpyxl raises zipfile.BadZipFile (not ValueError) for a corrupt or
    non-XLSX file. parse_investor_level_gl_workbook must normalise that to ValueError so this
    returns a clean 422 instead of an unhandled 500."""

    summary_bytes = json.dumps(
        {
            "legal_entity": "Fund X",
            "period_end": "2026-06-30",
            "total_assets": 5_000_000,
            "total_liabilities": 150_000,
            "reported_equity": 4_850_000,
            "opening_nav": 4_700_000,
            "closing_nav": 4_850_000,
        }
    ).encode()

    response = client.post(
        "/api/nav-quality/review",
        files={
            "nav_summary": ("nav-summary.json", summary_bytes, "application/json"),
            "source_ledger": (
                "source-ledger.xlsx",
                b"not a real xlsx file",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 422
    assert "source ledger" in response.json()["detail"]


def test_parse_investor_level_gl_workbook_rejects_corrupt_file_with_value_error() -> None:
    with pytest.raises(ValueError, match="could not be opened"):
        parse_investor_level_gl_workbook(b"not a real xlsx file")


# --- tolerance -------------------------------------------------------------------------------


def test_review_nav_quality_treats_one_cent_difference_as_a_pass() -> None:
    """nav_reconciliation.py's quick checks tolerate a 1-cent rounding difference (DEFAULT_TOLERANCE
    = "0.01"); review_nav_quality must apply the same tolerance so the two entry points to
    conceptually the same check cannot disagree at the boundary."""

    summary = _clean_summary(reported_equity=Decimal("4850000.01"))
    report = review_nav_quality(summary)

    codes = {finding.code for finding in report.findings}
    assert "balance_sheet.footing_valid" in codes
    assert "balance_sheet.footing_mismatch" not in codes
    assert report.action == NAVAction.READY_TO_SUBMIT


def test_review_nav_quality_still_flags_a_two_cent_difference() -> None:
    summary = _clean_summary(reported_equity=Decimal("4850000.02"))
    report = review_nav_quality(summary)

    codes = {finding.code for finding in report.findings}
    assert "balance_sheet.footing_mismatch" in codes


# --- NAVFinding.investor ------------------------------------------------------------------------


def test_investor_scoped_findings_carry_the_investor_field() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    summary = _clean_summary(
        investor_capital=[
            {"investor": "Investor A", "reported_capital": 2_500_000},
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ]
    )
    report = review_nav_quality(summary, ledger=ledger)

    mismatch = next(f for f in report.findings if f.code == "investor_capital.ledger_mismatch")
    match = next(f for f in report.findings if f.code == "investor_capital.matches_ledger")
    assert mismatch.investor == "Investor A"
    assert match.investor == "Investor B"
    # non-investor-scoped findings are untouched
    footing = next(f for f in report.findings if f.code == "balance_sheet.footing_valid")
    assert footing.investor is None


# --- group_exceptions_by_root_cause ---------------------------------------------------------------


def test_group_exceptions_by_root_cause_empty_when_report_is_clean() -> None:
    report = review_nav_quality(_clean_summary())
    assert group_exceptions_by_root_cause(report) == []


def test_group_exceptions_by_root_cause_groups_balance_sheet_break() -> None:
    summary = _clean_summary(reported_equity=4_800_000)
    report = review_nav_quality(summary)

    groups = group_exceptions_by_root_cause(report)

    assert len(groups) == 1
    group = groups[0]
    assert group.category == "balance_sheet"
    assert group.impact_amount == Decimal("50000.00")
    assert group.related_finding_codes == ["balance_sheet.footing_mismatch"]


def test_group_exceptions_by_root_cause_groups_nav_bridge_break() -> None:
    summary = _clean_summary(closing_nav=4_900_000)
    report = review_nav_quality(summary)

    groups = group_exceptions_by_root_cause(report)

    assert len(groups) == 1
    assert groups[0].category == "nav_bridge"
    assert groups[0].impact_amount == Decimal("50000.00")


def test_group_exceptions_by_root_cause_groups_per_investor_and_ranks_by_impact() -> None:
    ledger = parse_investor_level_gl_workbook(_build_gl_workbook(FUND_X_ROWS))
    summary = _clean_summary(
        reported_equity=4_800_000,  # balance-sheet break: impact 50,000
        investor_capital=[
            {"investor": "Investor A", "reported_capital": 2_000_000},  # impact 1,000,000
            {"investor": "Investor B", "reported_capital": 1_800_000},  # impact 50,000
        ],
    )
    report = review_nav_quality(summary, ledger=ledger)

    groups = group_exceptions_by_root_cause(report)

    assert [group.category for group in groups] == [
        "investor_capital",
        "balance_sheet",
        "investor_capital",
    ]
    assert groups[0].investor == "Investor A"
    assert groups[0].impact_amount == Decimal("1000000.00")
    assert groups[-1].investor == "Investor B"
    assert groups[-1].impact_amount == Decimal("50000.00")
    assert all(group.severity == "high" for group in groups)


def test_group_exceptions_by_root_cause_bundles_multiple_findings_for_one_investor() -> None:
    summary = _clean_summary(
        investor_capital=[
            {
                "investor": "Investor A",
                "reported_capital": 3_000_000,  # forgot the management-fee offset
                "management_fee": 125_000,
            }
        ]
    )
    rules = [_source_backed_rule()]
    report = review_nav_quality(summary, side_letter_rules=rules)

    groups = group_exceptions_by_root_cause(report)

    assert len(groups) == 1
    group = groups[0]
    assert group.investor == "Investor A"
    assert group.related_finding_codes == ["side_letter.rule_violation"]
    assert group.recommended_owner == "Investor relations"


def test_group_exceptions_by_root_cause_warning_only_group_stays_warning() -> None:
    summary = _clean_summary(
        investor_capital=[{"investor": "Investor A", "reported_capital": 3_000_000}]
    )
    rules = [_source_backed_rule()]
    report = review_nav_quality(summary, side_letter_rules=rules)

    groups = group_exceptions_by_root_cause(report)

    assert len(groups) == 1
    assert groups[0].severity == "warning"


def _submit_review(summary_bytes: bytes) -> dict[str, object]:
    response = client.post(
        "/api/nav-quality/review",
        files={"nav_summary": ("nav-summary.json", summary_bytes, "application/json")},
    )
    assert response.status_code == 200
    return response.json()


def test_review_endpoint_records_the_first_round() -> None:
    summary_bytes = json.dumps(
        {
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
    ).encode()

    body = _submit_review(summary_bytes)

    assert body["iteration"] == {
        "round_number": 1,
        "prior_rounds": 0,
        "note": body["iteration"]["note"],
    }


def test_resubmitting_the_same_case_increments_the_round() -> None:
    clean_bytes = json.dumps(
        {
            "legal_entity": "Fund Y",
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
    ).encode()
    broken_bytes = json.dumps(
        {
            "legal_entity": "Fund Y",
            "period_end": "2026-06-30",
            "total_assets": 5_000_000,
            "total_liabilities": 150_000,
            "reported_equity": 4_000_000,
            "opening_nav": 4_700_000,
            "contributions": 250_000,
            "distributions": 100_000,
            "income": 10_000,
            "expenses": 10_000,
            "closing_nav": 4_850_000,
        }
    ).encode()

    first = _submit_review(broken_bytes)
    second = _submit_review(clean_bytes)

    assert first["iteration"]["round_number"] == 1
    assert second["iteration"]["round_number"] == 2
    assert second["iteration"]["prior_rounds"] == 1


def test_case_iterations_endpoint_reports_full_history() -> None:
    summary_bytes = json.dumps(
        {
            "legal_entity": "Fund Z",
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
    ).encode()
    _submit_review(summary_bytes)

    response = client.get("/api/nav-quality/cases/Fund Z/2026-06-30")

    assert response.status_code == 200
    body = response.json()
    assert body["rounds_submitted"] == 1
    assert body["closed"] is True
    assert body["rounds_to_close"] == 1


def test_case_iterations_endpoint_404s_for_unknown_case() -> None:
    response = client.get("/api/nav-quality/cases/Unknown Fund/2026-06-30")

    assert response.status_code == 404


def test_metrics_endpoint_aggregates_tracked_cases() -> None:
    summary_bytes = json.dumps(
        {
            "legal_entity": "Fund M",
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
    ).encode()
    _submit_review(summary_bytes)

    response = client.get("/api/nav-quality/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["tracked_cases"] >= 1
    assert body["closed_cases"] >= 1
    assert body["average_rounds_to_close"] is not None
