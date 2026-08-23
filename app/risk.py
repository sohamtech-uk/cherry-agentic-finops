from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.models import DocumentExtraction, MatchCandidate, RiskAction, RiskDecision


def decide(
    extraction: DocumentExtraction,
    candidates: list[MatchCandidate],
    settings: Settings,
) -> RiskDecision:
    if not candidates:
        return RiskDecision(
            action=RiskAction.REQUEST_EVIDENCE,
            risk_score=95,
            control="No bank candidate",
            reasons=["No candidate bank transactions were supplied for reconciliation."],
        )

    selected = candidates[0]
    transaction = selected.transaction
    reasons: list[str] = []

    if transaction.already_reconciled:
        return RiskDecision(
            action=RiskAction.REQUEST_EVIDENCE,
            risk_score=100,
            control="Duplicate prevention",
            reasons=["The highest-ranked bank transaction is already reconciled."],
            selected_transaction_id=transaction.transaction_id,
        )

    if extraction.currency != transaction.currency:
        return RiskDecision(
            action=RiskAction.REQUEST_EVIDENCE,
            risk_score=100,
            control="Currency integrity",
            reasons=[
                f"Document currency {extraction.currency} does not match bank currency "
                f"{transaction.currency}."
            ],
            selected_transaction_id=transaction.transaction_id,
        )

    tolerance = Decimal(str(settings.amount_tolerance_percent))
    if selected.amount_variance_percent > tolerance:
        return RiskDecision(
            action=RiskAction.REQUEST_EVIDENCE,
            risk_score=min(100, 70 + int(selected.amount_variance_percent)),
            control="Amount variance",
            reasons=[
                f"Amount variance of {selected.amount_variance_percent}% exceeds the "
                f"{tolerance}% tolerance."
            ],
            selected_transaction_id=transaction.transaction_id,
        )

    if selected.score < 65:
        return RiskDecision(
            action=RiskAction.REQUEST_EVIDENCE,
            risk_score=90,
            control="Insufficient match evidence",
            reasons=[f"Best reconciliation score is only {selected.score}/100."],
            selected_transaction_id=transaction.transaction_id,
        )

    if extraction.currency != "GBP":
        reasons.append(
            f"The policy threshold is defined in GBP and no FX conversion was supplied for "
            f"{extraction.currency}; human review is required."
        )

    if extraction.currency == "GBP" and float(extraction.total) >= settings.approval_amount_gbp:
        reasons.append(
            f"Value {extraction.currency} {extraction.total} exceeds the configured approval "
            f"threshold of GBP {settings.approval_amount_gbp:,.2f}."
        )

    if selected.score < settings.auto_reconcile_score:
        reasons.append(
            f"Match score {selected.score}/100 is below the automatic threshold of "
            f"{settings.auto_reconcile_score}/100."
        )

    if extraction.confidence < 80:
        reasons.append(
            f"Document extraction confidence is {extraction.confidence}/100, below 80/100."
        )

    if reasons:
        return RiskDecision(
            action=RiskAction.REQUIRE_APPROVAL,
            risk_score=max(45, 100 - selected.score),
            control="Human-in-the-loop approval",
            reasons=reasons,
            selected_transaction_id=transaction.transaction_id,
        )

    return RiskDecision(
        action=RiskAction.AUTO_RECONCILE,
        risk_score=max(5, 100 - selected.score),
        control="High-confidence bounded automation",
        reasons=[
            "Amount, currency and transaction state passed deterministic controls.",
            f"Match score {selected.score}/100 meets the automatic threshold.",
            "Transaction value remains below the human approval threshold.",
        ],
        selected_transaction_id=transaction.transaction_id,
    )
