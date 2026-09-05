"""Daily fund health check: a portfolio-level view across every fund/period tracked by
app.nav_review_history, answering "which funds need attention today, and why."

Pure aggregation, no new arithmetic and no LLM: each entry is built from the latest recorded round
for its case, including the root causes snapshotted at that round (app.nav_review_history.
NAVReviewRound.root_causes). This never re-runs a review or reinterprets a finding — it only
classifies and ranks what NAV Quality Controller and the exception grouper already produced.

Scheduling this daily is a deployment concern, not something this module does itself: it just
answers the question correctly whenever it's called, whether that's once a day from a scheduler
or once from a chat message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.nav_exceptions import RootCauseGroup
from app.nav_quality import NAVAction
from app.nav_review_history import NAVCaseIterationSummary, NAVReviewHistoryStore
from app.private_markets import FindingSeverity


class FundHealthEntry(BaseModel):
    legal_entity: str
    period_end: str
    status: Literal["ready", "attention_needed"]
    rounds_submitted: int
    latest_action: NAVAction
    critical_root_causes: int
    warning_root_causes: int
    root_causes: list[RootCauseGroup] = Field(default_factory=list)
    last_submitted_at: datetime


class DailyFundHealthCheck(BaseModel):
    generated_at: datetime
    tracked_funds: int
    ready: int
    attention_needed: int
    average_rounds_to_close: float | None
    entries: list[FundHealthEntry]


def _entry(case: NAVCaseIterationSummary) -> FundHealthEntry:
    latest = case.history[-1]
    critical = sum(1 for group in latest.root_causes if group.severity == FindingSeverity.HIGH)
    warning = sum(1 for group in latest.root_causes if group.severity == FindingSeverity.WARNING)
    return FundHealthEntry(
        legal_entity=case.legal_entity,
        period_end=case.period_end,
        status="ready" if latest.action == NAVAction.READY_TO_SUBMIT else "attention_needed",
        rounds_submitted=case.rounds_submitted,
        latest_action=latest.action,
        critical_root_causes=critical,
        warning_root_causes=warning,
        root_causes=latest.root_causes,
        last_submitted_at=latest.submitted_at,
    )


def build_daily_health_check(store: NAVReviewHistoryStore) -> DailyFundHealthCheck:
    entries = [_entry(case) for case in store.all_cases()]
    entries.sort(
        key=lambda entry: (
            entry.status != "attention_needed",
            -entry.critical_root_causes,
            -entry.rounds_submitted,
        )
    )
    attention_needed = sum(1 for entry in entries if entry.status == "attention_needed")
    metrics = store.metrics()

    return DailyFundHealthCheck(
        generated_at=datetime.now(UTC),
        tracked_funds=len(entries),
        ready=len(entries) - attention_needed,
        attention_needed=attention_needed,
        average_rounds_to_close=metrics.average_rounds_to_close,
        entries=entries,
    )
