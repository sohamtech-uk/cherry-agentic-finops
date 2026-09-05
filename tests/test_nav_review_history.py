from __future__ import annotations

from app.nav_quality import NAVAction
from app.nav_review_history import NAVReviewHistoryStore, compute_iteration_metrics


def _record(
    store: NAVReviewHistoryStore,
    legal_entity: str,
    period_end: str,
    action: NAVAction,
    case_id: str = "CASE",
) -> None:
    store.record_round(
        legal_entity=legal_entity,
        period_end=period_end,
        action=action,
        controls_passed=1,
        exceptions_open=0,
        case_id=case_id,
    )


def test_record_round_increments_per_case() -> None:
    store = NAVReviewHistoryStore()

    first = store.record_round(
        legal_entity="Fund X",
        period_end="2026-06-30",
        action=NAVAction.RETURN_TO_ADMINISTRATOR,
        controls_passed=2,
        exceptions_open=1,
        case_id="CASE-1",
    )
    second = store.record_round(
        legal_entity="Fund X",
        period_end="2026-06-30",
        action=NAVAction.READY_TO_SUBMIT,
        controls_passed=3,
        exceptions_open=0,
        case_id="CASE-2",
    )

    assert first.round_number == 1
    assert second.round_number == 2


def test_record_round_is_case_insensitive_on_legal_entity() -> None:
    store = NAVReviewHistoryStore()
    _record(store, "Fund X", "2026-06-30", NAVAction.NEEDS_REVIEW)
    _record(store, "fund x", "2026-06-30", NAVAction.READY_TO_SUBMIT)

    summary = store.case_history("FUND X", "2026-06-30")

    assert summary is not None
    assert summary.rounds_submitted == 2


def test_different_periods_are_different_cases() -> None:
    store = NAVReviewHistoryStore()
    _record(store, "Fund X", "2026-03-31", NAVAction.READY_TO_SUBMIT)
    _record(store, "Fund X", "2026-06-30", NAVAction.RETURN_TO_ADMINISTRATOR)

    march = store.case_history("Fund X", "2026-03-31")
    june = store.case_history("Fund X", "2026-06-30")

    assert march is not None and march.rounds_submitted == 1
    assert june is not None and june.rounds_submitted == 1


def test_case_history_reports_rounds_to_close() -> None:
    store = NAVReviewHistoryStore()
    _record(store, "Fund X", "2026-06-30", NAVAction.RETURN_TO_ADMINISTRATOR)
    _record(store, "Fund X", "2026-06-30", NAVAction.NEEDS_REVIEW)
    _record(store, "Fund X", "2026-06-30", NAVAction.READY_TO_SUBMIT)

    summary = store.case_history("Fund X", "2026-06-30")

    assert summary is not None
    assert summary.closed is True
    assert summary.rounds_to_close == 3
    assert summary.rounds_submitted == 3


def test_case_history_open_case_has_no_rounds_to_close() -> None:
    store = NAVReviewHistoryStore()
    _record(store, "Fund X", "2026-06-30", NAVAction.RETURN_TO_ADMINISTRATOR)

    summary = store.case_history("Fund X", "2026-06-30")

    assert summary is not None
    assert summary.closed is False
    assert summary.rounds_to_close is None


def test_case_history_missing_case_returns_none() -> None:
    store = NAVReviewHistoryStore()

    assert store.case_history("Nonexistent Fund", "2026-06-30") is None


def test_clear_removes_all_rounds_and_reports_count() -> None:
    store = NAVReviewHistoryStore()
    _record(store, "Fund X", "2026-06-30", NAVAction.READY_TO_SUBMIT)
    _record(store, "Fund Y", "2026-06-30", NAVAction.READY_TO_SUBMIT)

    removed = store.clear()

    assert removed == 2
    assert store.case_history("Fund X", "2026-06-30") is None
    assert store.all_cases() == []


def test_compute_iteration_metrics_averages_closed_and_open_cases() -> None:
    store = NAVReviewHistoryStore()
    _record(store, "Fund A", "2026-06-30", NAVAction.RETURN_TO_ADMINISTRATOR)
    _record(store, "Fund A", "2026-06-30", NAVAction.READY_TO_SUBMIT)
    _record(store, "Fund B", "2026-06-30", NAVAction.READY_TO_SUBMIT)
    _record(store, "Fund C", "2026-06-30", NAVAction.NEEDS_REVIEW)
    _record(store, "Fund C", "2026-06-30", NAVAction.NEEDS_REVIEW)

    metrics = compute_iteration_metrics(store.all_cases())

    assert metrics.tracked_cases == 3
    assert metrics.closed_cases == 2
    assert metrics.open_cases == 1
    assert metrics.average_rounds_to_close == 1.5
    assert metrics.rounds_to_close_distribution == {2: 1, 1: 1}
    assert metrics.average_rounds_open_so_far == 2.0


def test_compute_iteration_metrics_empty_store() -> None:
    metrics = compute_iteration_metrics([])

    assert metrics.tracked_cases == 0
    assert metrics.average_rounds_to_close is None
    assert metrics.average_rounds_open_so_far is None
