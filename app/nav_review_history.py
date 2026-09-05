"""NAV review iteration tracking.

The sponsor call transcripts named a concrete KPI directly: "NAV comes back with errors and takes
3-7 iterations to reach an acceptable version." That number is a claim about real usage, not
something a review engine can assert about itself. This module is how the claim gets measured
instead of asserted: every submission to /api/nav-quality/review (or the equivalent agent tool
call) is recorded as one round for its (legal_entity, period_end) case, so this NAV Guardian
instance can report, honestly, how many rounds each case has actually taken so far, and — once a
case reaches ready_to_submit — how many rounds it took to close.

In-memory only, matching app.contracts.ContractRepository's scope: this is demo/session state, not
a system of record. A production deployment reviewing real funds would back this with the same
persistence backend as app.repository.WorkflowRepository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, Field

from app.nav_quality import NAVAction


def _case_key(legal_entity: str, period_end: str) -> str:
    return f"{legal_entity.strip().casefold()}|{period_end.strip()}"


class NAVReviewRound(BaseModel):
    legal_entity: str
    period_end: str
    round_number: int
    action: NAVAction
    controls_passed: int
    exceptions_open: int
    case_id: str
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NAVCaseIterationSummary(BaseModel):
    legal_entity: str
    period_end: str
    rounds_submitted: int
    closed: bool
    rounds_to_close: int | None
    latest_action: NAVAction
    history: list[NAVReviewRound]


class NAVIterationMetrics(BaseModel):
    tracked_cases: int
    closed_cases: int
    open_cases: int
    average_rounds_to_close: float | None
    rounds_to_close_distribution: dict[int, int]
    average_rounds_open_so_far: float | None


def _summarise(history: list[NAVReviewRound]) -> NAVCaseIterationSummary:
    first, last = history[0], history[-1]
    closed_round = next(
        (round_ for round_ in history if round_.action == NAVAction.READY_TO_SUBMIT), None
    )
    return NAVCaseIterationSummary(
        legal_entity=first.legal_entity,
        period_end=first.period_end,
        rounds_submitted=len(history),
        closed=closed_round is not None,
        rounds_to_close=closed_round.round_number if closed_round else None,
        latest_action=last.action,
        history=history,
    )


def compute_iteration_metrics(cases: list[NAVCaseIterationSummary]) -> NAVIterationMetrics:
    closed_round_counts: list[int] = []
    for case in cases:
        if case.rounds_to_close is not None:
            closed_round_counts.append(case.rounds_to_close)
    open_cases = [case for case in cases if not case.closed]
    distribution: dict[int, int] = {}
    for rounds in closed_round_counts:
        distribution[rounds] = distribution.get(rounds, 0) + 1

    return NAVIterationMetrics(
        tracked_cases=len(cases),
        closed_cases=len(closed_round_counts),
        open_cases=len(open_cases),
        average_rounds_to_close=(
            sum(closed_round_counts) / len(closed_round_counts) if closed_round_counts else None
        ),
        rounds_to_close_distribution=distribution,
        average_rounds_open_so_far=(
            sum(case.rounds_submitted for case in open_cases) / len(open_cases)
            if open_cases
            else None
        ),
    )


class NAVReviewHistoryStore:
    def __init__(self) -> None:
        self._rounds: dict[str, list[NAVReviewRound]] = {}
        self._lock = RLock()

    def clear(self) -> int:
        with self._lock:
            count = sum(len(rounds) for rounds in self._rounds.values())
            self._rounds.clear()
            return count

    def record_round(
        self,
        legal_entity: str,
        period_end: str,
        action: NAVAction,
        controls_passed: int,
        exceptions_open: int,
        case_id: str,
    ) -> NAVReviewRound:
        key = _case_key(legal_entity, period_end)
        with self._lock:
            history = self._rounds.setdefault(key, [])
            round_ = NAVReviewRound(
                legal_entity=legal_entity,
                period_end=period_end,
                round_number=len(history) + 1,
                action=action,
                controls_passed=controls_passed,
                exceptions_open=exceptions_open,
                case_id=case_id,
            )
            history.append(round_)
            return round_

    def case_history(self, legal_entity: str, period_end: str) -> NAVCaseIterationSummary | None:
        key = _case_key(legal_entity, period_end)
        with self._lock:
            history = self._rounds.get(key)
            if not history:
                return None
            history = list(history)
        return _summarise(history)

    def all_cases(self) -> list[NAVCaseIterationSummary]:
        with self._lock:
            histories = [list(rounds) for rounds in self._rounds.values()]
        return [_summarise(history) for history in histories if history]

    def metrics(self) -> NAVIterationMetrics:
        return compute_iteration_metrics(self.all_cases())


_store = NAVReviewHistoryStore()


def get_nav_review_history_store() -> NAVReviewHistoryStore:
    return _store
