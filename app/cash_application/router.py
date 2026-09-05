from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.cash_application.agent import (
    AgentInvestigationError,
    CashApplicationAgent,
)
from app.cash_application.demo import clean_multi_invoice_demo
from app.cash_application.eval_adapter import to_trial_outcome
from app.cash_application.review import (
    ControllerReviewError,
    ControllerReviewService,
    ReviewDecisionRequest,
)

router = APIRouter(prefix="/api/controller-review", tags=["controller-review"])


@lru_cache(maxsize=1)
def get_controller_review_service() -> ControllerReviewService:
    return ControllerReviewService()


@lru_cache(maxsize=1)
def get_cash_application_agent() -> CashApplicationAgent:
    return CashApplicationAgent()


def _raise_http_error(exc: ControllerReviewError) -> None:
    status_code = 404 if exc.code == "CASE_NOT_FOUND" else 409
    raise HTTPException(status_code=status_code, detail=exc.as_detail()) from exc


@router.get("/contract")
async def controller_review_contract() -> dict[str, Any]:
    return {
        "workflow": "AR cash-application exception review",
        "packet_requirements": [
            "receipt",
            "customer_invoice_match",
            "source_evidence_locators_and_hashes",
            "amount_at_risk",
            "policy_id_version_and_clause",
            "automation_stop_reasons",
            "remaining_ar_state",
            "allowed_actions",
        ],
        "allowed_actions": [
            "approve_write_off",
            "leave_balance_open",
            "create_dispute",
            "request_evidence",
            "reject_match",
        ],
        "approval_controls": [
            "reviewer_authority",
            "decision_idempotency",
            "exact_bank_source_identity_unique",
            "receipt_booked_and_positive",
            "input_versions_current",
            "currency_compatible",
            "receipt_allocation_valid",
            "invoice_balance_valid",
        ],
        "boundary": (
            "A material short-pay stays HELD with no ledger mutation until a valid decision. "
            "Duplicate identity, ineligible cash, stale versions, currency mismatch and arithmetic "
            "failures are BLOCK and never approvable. In-memory simulated AR only; no production "
            "writes, payment initiation or policy changes."
        ),
    }


@router.get("/reviewers")
async def list_reviewers() -> list[dict[str, Any]]:
    return [
        reviewer.model_dump(mode="json") for reviewer in get_controller_review_service().reviewers()
    ]


@router.post("/demo/clean-multi-invoice")
async def run_clean_multi_invoice_demo() -> dict[str, Any]:
    """Apply RCPT-1041 to two evidenced invoices in a fresh simulated ledger."""

    return clean_multi_invoice_demo()


@router.get("/cases/{case_id}")
async def get_review_packet(case_id: str) -> dict[str, Any]:
    try:
        packet = get_controller_review_service().get_packet(case_id)
    except ControllerReviewError as exc:
        _raise_http_error(exc)
    return packet.model_dump(mode="json")


@router.get("/cases/{case_id}/outcome")
async def get_review_trial_outcome(
    case_id: str,
    trial_id: str = Query(min_length=1, max_length=100),
) -> dict[str, Any]:
    """Return stable grader fields; this endpoint never derives state from the UI."""

    try:
        packet = get_controller_review_service().get_packet(case_id)
    except ControllerReviewError as exc:
        _raise_http_error(exc)
    return to_trial_outcome(packet, trial_id=trial_id).model_dump(mode="json")


@router.post("/cases/{case_id}/agent-investigation")
async def investigate_review_case(case_id: str) -> dict[str, Any]:
    """Run a read-only model/tool investigation; never record or apply a decision."""

    try:
        packet = get_controller_review_service().get_packet(case_id)
        result = await get_cash_application_agent().investigate(packet)
    except ControllerReviewError as exc:
        _raise_http_error(exc)
    except AgentInvestigationError as exc:
        status_code = (
            409 if exc.code in {"CASE_ALREADY_DECIDED", "FUNDAMENTAL_CONTROL_BLOCK"} else 503
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return result.model_dump(mode="json")


@router.post("/cases/{case_id}/decisions")
async def record_review_decision(case_id: str, request: ReviewDecisionRequest) -> dict[str, Any]:
    try:
        packet = get_controller_review_service().decide(case_id, request)
    except ControllerReviewError as exc:
        _raise_http_error(exc)
    return packet.model_dump(mode="json")


@router.post("/demo/short-pay-500/reset")
async def reset_short_pay_demo() -> dict[str, Any]:
    return get_controller_review_service().reset_demo().model_dump(mode="json")
