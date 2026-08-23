from decimal import Decimal

from app.config import Settings
from app.demo_data import approval_scenario, autonomous_scenario, exception_scenario
from app.matching import rank_candidates
from app.models import RiskAction
from app.risk import decide


def test_exact_reference_and_amount_ranks_first() -> None:
    extraction, transactions = autonomous_scenario()
    candidates = rank_candidates(extraction, transactions)

    assert candidates[0].transaction.transaction_id == "bank_tx_98214"
    assert candidates[0].score >= 95
    assert candidates[0].amount_variance_percent == Decimal("0.00")


def test_low_risk_exact_match_can_auto_reconcile() -> None:
    extraction, transactions = autonomous_scenario()
    decision = decide(extraction, rank_candidates(extraction, transactions), Settings())

    assert decision.action == RiskAction.AUTO_RECONCILE
    assert decision.selected_transaction_id == "bank_tx_98214"


def test_high_value_match_requires_human_approval() -> None:
    extraction, transactions = approval_scenario()
    decision = decide(extraction, rank_candidates(extraction, transactions), Settings())

    assert decision.action == RiskAction.REQUIRE_APPROVAL
    assert "approval threshold" in " ".join(decision.reasons)


def test_material_amount_mismatch_requests_evidence() -> None:
    extraction, transactions = exception_scenario()
    decision = decide(extraction, rank_candidates(extraction, transactions), Settings())

    assert decision.action == RiskAction.REQUEST_EVIDENCE
    assert decision.control == "Amount variance"
