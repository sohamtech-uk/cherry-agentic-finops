from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

CaseStage = Literal[
    "classified",
    "planned",
    "executed",
    "investigated",
    "decided",
]


@dataclass
class FundManagerCase:
    case_id: str
    files: list[tuple[str, bytes, str | None]]
    fund_name: str | None
    reporting_period: str | None
    as_of_date: str | None
    created_at: str
    updated_at: str
    stage: CaseStage = "classified"
    classification: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    investigation: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    nav_readiness: dict[str, Any] | None = None
    nav_reconciliation: dict[str, Any] | None = None
    nav_review: dict[str, Any] | None = None
    nav_decision: dict[str, Any] | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()

    def public_view(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "fund_name": self.fund_name,
            "reporting_period": self.reporting_period,
            "as_of_date": self.as_of_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stage": self.stage,
            "classification": self.classification,
            "plan": self.plan,
            "execution": self.execution,
            "investigation": self.investigation,
            "decision": self.decision,
            "workflows": {
                "general_control_review": {
                    "stage": self.stage,
                    "plan": self.plan,
                    "execution": self.execution,
                    "investigation": self.investigation,
                    "decision": self.decision,
                },
                "nav_quality_controller": {
                    "readiness": self.nav_readiness,
                    "reconciliation": self.nav_reconciliation,
                    "review": self.nav_review,
                    "decision": self.nav_decision,
                },
            },
        }


class FundManagerCaseStore:
    """Small process-local case store for staged Fund Manager workflows.

    Uploaded bytes never return to the browser after case creation. Production deployments that
    require cross-instance or restart durability should replace this store with a shared database
    or object store while keeping the same case API.
    """

    def __init__(self) -> None:
        self._cases: dict[str, FundManagerCase] = {}
        self._lock = RLock()

    def create(
        self,
        files: list[tuple[str, bytes, str | None]],
        *,
        classification: dict[str, Any],
        fund_name: str | None = None,
        reporting_period: str | None = None,
        as_of_date: str | None = None,
    ) -> FundManagerCase:
        now = datetime.now(UTC).isoformat()
        case = FundManagerCase(
            case_id=f"FM-{uuid4().hex[:12].upper()}",
            files=files,
            fund_name=fund_name,
            reporting_period=reporting_period,
            as_of_date=as_of_date,
            created_at=now,
            updated_at=now,
            classification=classification,
        )
        with self._lock:
            self._cases[case.case_id] = case
        return case

    def get(self, case_id: str) -> FundManagerCase | None:
        with self._lock:
            return self._cases.get(case_id)

    def clear(self) -> None:
        with self._lock:
            self._cases.clear()


case_store = FundManagerCaseStore()
