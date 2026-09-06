from __future__ import annotations

from decimal import Decimal

from app.nav_exceptions import RootCauseGroup
from app.nav_health_check import build_daily_health_check
from app.nav_quality import NAVAction
from app.nav_review_history import NAVReviewHistoryStore
from app.private_markets import FindingSeverity


def _root_cause(
    severity: FindingSeverity, code: str = "balance_sheet.footing_mismatch"
) -> RootCauseGroup:
    return RootCauseGroup(
        code=code,
        category="balance_sheet",
        title="Balance sheet does not reconcile",
        summary="Assets less liabilities does not equal reported equity.",
        severity=severity,
        impact_amount=Decimal("125000.00"),
        related_finding_codes=[code],
        recommended_owner="Fund controller",
        recommended_action="Resolve the balance sheet break",
    )


def test_ready_case_has_no_open_root_causes() -> None:
    store = NAVReviewHistoryStore()
    store.record_round(
        legal_entity="Fund A",
        period_end="2026-06-30",
        action=NAVAction.READY_TO_SUBMIT,
        controls_passed=3,
        exceptions_open=0,
        case_id="CASE-A",
    )

    report = build_daily_health_check(store)

    assert report.tracked_funds == 1
    assert report.ready == 1
    assert report.attention_needed == 0
    entry = report.entries[0]
    assert entry.status == "ready"
    assert entry.critical_root_causes == 0
    assert entry.root_causes == []


def test_attention_needed_case_counts_root_causes_by_severity() -> None:
    store = NAVReviewHistoryStore()
    store.record_round(
        legal_entity="Fund B",
        period_end="2026-06-30",
        action=NAVAction.RETURN_TO_ADMINISTRATOR,
        controls_passed=1,
        exceptions_open=2,
        case_id="CASE-B",
        root_causes=[
            _root_cause(FindingSeverity.HIGH),
            _root_cause(FindingSeverity.WARNING, code="side_letter.missing_management_fee"),
        ],
    )

    report = build_daily_health_check(store)

    entry = report.entries[0]
    assert entry.status == "attention_needed"
    assert entry.critical_root_causes == 1
    assert entry.warning_root_causes == 1
    assert len(entry.root_causes) == 2


def test_only_the_latest_round_is_used_for_root_causes() -> None:
    store = NAVReviewHistoryStore()
    store.record_round(
        legal_entity="Fund C",
        period_end="2026-06-30",
        action=NAVAction.RETURN_TO_ADMINISTRATOR,
        controls_passed=1,
        exceptions_open=1,
        case_id="CASE-C-1",
        root_causes=[_root_cause(FindingSeverity.HIGH)],
    )
    store.record_round(
        legal_entity="Fund C",
        period_end="2026-06-30",
        action=NAVAction.READY_TO_SUBMIT,
        controls_passed=3,
        exceptions_open=0,
        case_id="CASE-C-2",
        root_causes=[],
    )

    report = build_daily_health_check(store)

    entry = report.entries[0]
    assert entry.status == "ready"
    assert entry.rounds_submitted == 2
    assert entry.critical_root_causes == 0


def test_attention_needed_cases_are_ranked_before_ready_cases() -> None:
    store = NAVReviewHistoryStore()
    store.record_round(
        legal_entity="Fund Ready",
        period_end="2026-06-30",
        action=NAVAction.READY_TO_SUBMIT,
        controls_passed=3,
        exceptions_open=0,
        case_id="CASE-READY",
    )
    store.record_round(
        legal_entity="Fund Broken",
        period_end="2026-06-30",
        action=NAVAction.RETURN_TO_ADMINISTRATOR,
        controls_passed=1,
        exceptions_open=1,
        case_id="CASE-BROKEN",
        root_causes=[_root_cause(FindingSeverity.HIGH)],
    )

    report = build_daily_health_check(store)

    assert [entry.legal_entity for entry in report.entries] == ["Fund Broken", "Fund Ready"]


def test_more_critical_root_causes_rank_higher_within_attention_needed() -> None:
    store = NAVReviewHistoryStore()
    store.record_round(
        legal_entity="Fund One Break",
        period_end="2026-06-30",
        action=NAVAction.RETURN_TO_ADMINISTRATOR,
        controls_passed=1,
        exceptions_open=1,
        case_id="CASE-ONE",
        root_causes=[_root_cause(FindingSeverity.HIGH)],
    )
    store.record_round(
        legal_entity="Fund Two Breaks",
        period_end="2026-06-30",
        action=NAVAction.RETURN_TO_ADMINISTRATOR,
        controls_passed=1,
        exceptions_open=2,
        case_id="CASE-TWO",
        root_causes=[
            _root_cause(FindingSeverity.HIGH, code="balance_sheet.footing_mismatch"),
            _root_cause(FindingSeverity.HIGH, code="nav_bridge.does_not_foot"),
        ],
    )

    report = build_daily_health_check(store)

    assert [entry.legal_entity for entry in report.entries] == [
        "Fund Two Breaks",
        "Fund One Break",
    ]


def test_empty_store_reports_zero_tracked_funds() -> None:
    report = build_daily_health_check(NAVReviewHistoryStore())

    assert report.tracked_funds == 0
    assert report.entries == []
    assert report.average_rounds_to_close is None
