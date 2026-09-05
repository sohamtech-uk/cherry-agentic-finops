from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.cash_application.review import (
    ControllerReviewError,
    ControllerReviewPacket,
    ControllerReviewService,
    ReviewAction,
    ReviewDecisionRequest,
    build_short_pay_packet,
)
from app.cash_application.router import get_controller_review_service

client = TestClient(app)


def decision_request(
    action: ReviewAction = ReviewAction.APPROVE_WRITE_OFF,
    *,
    decision_id: str = "decision-001",
    reviewer_id: str = "controller_uk_01",
    expected_review_version: int = 1,
) -> ReviewDecisionRequest:
    values: dict[str, str | int | ReviewAction] = {
        "decision_id": decision_id,
        "expected_review_version": expected_review_version,
        "reviewer_id": reviewer_id,
        "action": action,
        "rationale": "Reviewed the source evidence and selected the stated accounting treatment.",
    }
    if action in {ReviewAction.APPROVE_WRITE_OFF, ReviewAction.CREATE_DISPUTE}:
        values["reason_code"] = "DAMAGED_GOODS"
    if action == ReviewAction.CREATE_DISPUTE:
        values["dispute_owner"] = "Deductions team"
    if action == ReviewAction.REQUEST_EVIDENCE:
        values["requested_evidence"] = "Customer damage report"
    return ReviewDecisionRequest.model_validate(values)


def test_500_short_pay_packet_is_held_unchanged_decision_ready_and_grounded() -> None:
    packet = build_short_pay_packet()

    assert packet.receipt.receipt_id == "RCPT-1042"
    assert packet.legal_entity_id == "CHERRY-UK-LTD"
    assert packet.receipt.source_system == "SYNTHETIC_BANK"
    assert packet.receipt.source_transaction_id == "TX-1042"
    assert packet.receipt.amount == Decimal("9500.00")
    assert packet.receipt.settlement_status == "BOOKED"
    assert packet.receipt.allocation_status == "HELD"
    assert packet.application_status == "REVIEW_REQUIRED"
    assert packet.control_disposition == "REVIEW_REQUIRED"
    assert packet.customer_invoice_match.customer_id == "CUST-0042"
    assert packet.customer_invoice_match.invoice_id == "INV-2208"
    assert packet.customer_invoice_match.remittance_raw_reason == "DAMAGED_GOODS"
    assert packet.amount_at_risk == Decimal("500.00")
    assert packet.remaining_ar_state.cash_applied == Decimal("0.00")
    assert packet.remaining_ar_state.open_balance == Decimal("10000.00")
    assert packet.proposed_after_valid_decision.cash_applied == Decimal("9500.00")
    assert packet.proposed_after_valid_decision.open_balance == Decimal("500.00")
    assert packet.policy.policy_id == "SHORTPAY-01"
    assert packet.policy.version == 3
    assert [clause.clause for clause in packet.policy.clauses] == ["4.2", "7.1"]
    assert {reason.code for reason in packet.automation_stopped} == {
        "AUTO_LIMIT_EXCEEDED",
        "REASON_NOT_AUTO_APPROVED",
    }
    assert {item.action for item in packet.allowed_actions} == set(ReviewAction)
    assert len(packet.evidence) == 4
    assert all(len(item.source_sha256) == 64 for item in packet.evidence)
    assert all(item.locator for item in packet.evidence)
    assert all(check.passed for check in packet.control_checks)
    assert packet.simulation_only is True
    assert packet.production_write_performed is False


def test_controller_within_authority_can_approve_500_writeoff_after_fresh_controls() -> None:
    service = ControllerReviewService()

    result = service.decide("CA-05-RCPT-1042-500", decision_request())

    assert result.review_status == "write_off_approved"
    assert result.application_status == "POSTED_SIMULATED"
    assert result.recorded_decision is not None
    assert result.recorded_decision.authorised_amount_gbp == Decimal("500.00")
    assert result.recorded_decision.authority_id == "AUTH-CONTROLLER-UK"
    assert result.remaining_ar_state.cash_applied == Decimal("9500.00")
    assert result.remaining_ar_state.authorised_adjustment == Decimal("500.00")
    assert result.remaining_ar_state.open_balance == Decimal("0.00")
    assert result.remaining_ar_state.invoice_state == "CLOSED"
    assert result.receipt.allocation_status == "APPLIED"
    assert all(check.passed for check in service.get_packet(result.case_id).control_checks)


def test_ca12_escalates_approval_above_authority_without_decision_or_ledger_change() -> None:
    packet = build_short_pay_packet("2500")
    service = ControllerReviewService(packet)

    with pytest.raises(ControllerReviewError) as raised:
        service.decide(packet.case_id, decision_request())

    assert raised.value.code == "AUTHORITY_EXCEEDED"
    assert raised.value.context == {
        "amount_at_risk_gbp": "2500.00",
        "reviewer_limit_gbp": "1000.00",
    }
    unchanged = service.get_packet(packet.case_id)
    assert unchanged.review_status == "escalated"
    assert unchanged.exception_status == "ESCALATED_AUTHORITY"
    assert unchanged.recorded_decision is None
    assert unchanged.receipt.allocation_status == "HELD"
    assert unchanged.remaining_ar_state.cash_applied == Decimal("0.00")
    assert unchanged.remaining_ar_state.open_balance == Decimal("10000.00")
    assert unchanged.review_attempts[-1].code == "AUTHORITY_EXCEEDED"


@pytest.mark.parametrize(
    ("mutate", "failed_code"),
    [
        (
            lambda packet: setattr(packet.receipt, "duplicate_detected", True),
            "NO_DUPLICATE_RECEIPT",
        ),
        (
            lambda packet: setattr(packet.receipt, "settlement_status", "PENDING"),
            "RECEIPT_BOOKED_POSITIVE",
        ),
        (
            lambda packet: setattr(packet.receipt, "settlement_status", "REVERSED"),
            "RECEIPT_BOOKED_POSITIVE",
        ),
        (
            lambda packet: setattr(packet.customer_invoice_match, "invoice_currency", "USD"),
            "CURRENCY_COMPATIBLE",
        ),
        (
            lambda packet: setattr(
                packet.customer_invoice_match, "proposed_cash_application", Decimal("9501.00")
            ),
            "RECEIPT_ALLOCATION_VALID",
        ),
        (
            lambda packet: setattr(
                packet.proposed_after_valid_decision, "invoice_balance_before", Decimal("9999.00")
            ),
            "INVOICE_BALANCE_VALID",
        ),
        (
            lambda packet: setattr(packet.receipt, "version", 3),
            "INPUT_VERSIONS_CURRENT",
        ),
    ],
)
@pytest.mark.parametrize(
    "action", [ReviewAction.APPROVE_WRITE_OFF, ReviewAction.LEAVE_BALANCE_OPEN]
)
def test_hard_block_outranks_review_and_no_action_can_override_it(
    mutate: Callable[[ControllerReviewPacket], None], failed_code: str, action: ReviewAction
) -> None:
    packet = build_short_pay_packet()
    mutate(packet)
    service = ControllerReviewService(packet)

    blocked = service.get_packet(packet.case_id)
    assert blocked.control_disposition == "BLOCK"
    assert blocked.application_status == "CONTROL_BLOCKED"
    assert blocked.exception_status == "BLOCKED"
    assert blocked.allowed_actions == []
    assert blocked.receipt.allocation_status == "UNAPPLIED"
    assert blocked.remaining_ar_state.cash_applied == Decimal("0.00")

    with pytest.raises(ControllerReviewError) as raised:
        service.decide(packet.case_id, decision_request(action=action))

    assert raised.value.code == "HARD_BLOCK"
    assert failed_code in raised.value.context["failed_controls"]
    assert service.get_packet(packet.case_id).recorded_decision is None


def test_stale_review_version_is_denied_without_state_change() -> None:
    service = ControllerReviewService()

    with pytest.raises(ControllerReviewError) as raised:
        service.decide(
            "CA-05-RCPT-1042-500",
            decision_request(
                action=ReviewAction.CREATE_DISPUTE,
                expected_review_version=99,
            ),
        )

    assert raised.value.code == "STALE_REVIEW"
    packet = service.get_packet("CA-05-RCPT-1042-500")
    assert packet.receipt.allocation_status == "HELD"
    assert packet.remaining_ar_state.cash_applied == Decimal("0.00")
    assert packet.remaining_ar_state.open_balance == Decimal("10000.00")
    assert packet.recorded_decision is None
    assert packet.review_attempts[-1].code == "STALE_REVIEW"


def test_identical_retry_is_idempotent_and_conflicting_retry_is_rejected() -> None:
    service = ControllerReviewService()
    request = decision_request(action=ReviewAction.LEAVE_BALANCE_OPEN)
    first = service.decide("CA-05-RCPT-1042-500", request)
    replay = service.decide("CA-05-RCPT-1042-500", request)

    assert first.recorded_decision is not None
    assert first.recorded_decision.idempotent_replay is False
    assert replay.recorded_decision is not None
    assert replay.recorded_decision.idempotent_replay is True
    assert replay.remaining_ar_state == first.remaining_ar_state

    conflicting = request.model_copy(update={"action": ReviewAction.REJECT_MATCH})
    with pytest.raises(ControllerReviewError) as raised:
        service.decide("CA-05-RCPT-1042-500", conflicting)
    assert raised.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("action", list(ReviewAction))
def test_all_contract_actions_produce_an_explicit_simulated_ar_state(
    action: ReviewAction,
) -> None:
    service = ControllerReviewService()

    result = service.decide(
        "CA-05-RCPT-1042-500",
        decision_request(action=action, decision_id=f"decision-{action}"),
    )

    assert result.recorded_decision is not None
    assert result.recorded_decision.action == action
    assert result.recorded_decision.simulated_only is True
    if action == ReviewAction.REJECT_MATCH:
        assert result.remaining_ar_state.open_balance == Decimal("10000.00")
        assert result.receipt.allocation_status == "UNAPPLIED"
    elif action == ReviewAction.REQUEST_EVIDENCE:
        assert result.remaining_ar_state.open_balance == Decimal("10000.00")
        assert result.receipt.allocation_status == "HELD"
    elif action == ReviewAction.APPROVE_WRITE_OFF:
        assert result.remaining_ar_state.open_balance == Decimal("0.00")
        assert result.remaining_ar_state.cash_applied == Decimal("9500.00")
    else:
        assert result.remaining_ar_state.open_balance == Decimal("500.00")
        assert result.remaining_ar_state.cash_applied == Decimal("9500.00")


def test_api_exposes_packet_contract_and_records_simulated_decision() -> None:
    get_controller_review_service().reset_demo()
    contract = client.get("/api/controller-review/contract")
    packet_response = client.get("/api/controller-review/cases/CA-05-RCPT-1042-500")

    assert contract.status_code == 200
    assert "reviewer_authority" in contract.json()["approval_controls"]
    assert "stays HELD" in contract.json()["boundary"]
    assert packet_response.status_code == 200
    assert packet_response.json()["amount_at_risk"] == "500.00"
    assert packet_response.json()["remaining_ar_state"]["cash_applied"] == "0.00"

    response = client.post(
        "/api/controller-review/cases/CA-05-RCPT-1042-500/decisions",
        json=decision_request(
            action=ReviewAction.CREATE_DISPUTE, decision_id="api-decision-001"
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "dispute_created"
    assert body["application_status"] == "POSTED_SIMULATED"
    assert body["remaining_ar_state"]["invoice_state"] == "DISPUTED"
    assert body["remaining_ar_state"]["cash_applied"] == "9500.00"
    assert body["remaining_ar_state"]["open_balance"] == "500.00"
    assert body["production_write_performed"] is False


def test_api_rejects_client_supplied_authority() -> None:
    get_controller_review_service().reset_demo()
    payload = decision_request().model_dump(mode="json")
    payload["approval_limit_gbp"] = "999999.00"

    response = client.post(
        "/api/controller-review/cases/CA-05-RCPT-1042-500/decisions",
        json=payload,
    )

    assert response.status_code == 422
    packet = client.get("/api/controller-review/cases/CA-05-RCPT-1042-500").json()
    assert packet["review_status"] == "awaiting_controller"
    assert packet["remaining_ar_state"]["cash_applied"] == "0.00"


def test_controller_review_page_is_served() -> None:
    response = client.get("/controller-review")

    assert response.status_code == 200
    assert "A decision, not a confidence score." in response.text
    assert "NO PRODUCTION WRITES" in response.text
