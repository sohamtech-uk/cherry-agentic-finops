from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from app.models import BankTransaction, DocumentExtraction, MatchCandidate, MatchFactor


def _normalise_text(value: str | None) -> str:
    text = (value or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _similarity(left: str | None, right: str | None) -> float:
    left_normalised = _normalise_text(left)
    right_normalised = _normalise_text(right)
    if not left_normalised or not right_normalised:
        return 0.0
    if left_normalised in right_normalised or right_normalised in left_normalised:
        return 1.0
    return SequenceMatcher(None, left_normalised, right_normalised).ratio()


def _days_between(left: date | None, right: date | None) -> int | None:
    if left is None or right is None:
        return None
    return abs((left - right).days)


def _variance(invoice_total: Decimal, transaction_amount: Decimal) -> Decimal:
    if invoice_total == 0:
        return Decimal("100")
    return (abs(transaction_amount - invoice_total) / invoice_total * 100).quantize(Decimal("0.01"))


def score_transaction(
    extraction: DocumentExtraction, transaction: BankTransaction
) -> MatchCandidate:
    factors: list[MatchFactor] = []
    score = 0
    variance = _variance(extraction.total, transaction.amount)

    if variance == 0:
        amount_score = 45
        amount_explanation = "Invoice total and bank amount match exactly."
    elif variance <= Decimal("0.5"):
        amount_score = 40
        amount_explanation = f"Amount is within {variance}% of the document total."
    elif variance <= Decimal("2"):
        amount_score = 28
        amount_explanation = f"Amount is within the configured 2% review tolerance ({variance}%)."
    elif variance <= Decimal("5"):
        amount_score = 12
        amount_explanation = f"Amount differs by {variance}%; human review is likely required."
    else:
        amount_score = 0
        amount_explanation = f"Amount differs materially by {variance}%."
    factors.append(
        MatchFactor(
            name="Amount",
            score=amount_score,
            maximum=45,
            explanation=amount_explanation,
        )
    )
    score += amount_score

    target_date = extraction.due_date or extraction.issue_date
    distance = _days_between(target_date, transaction.booking_date)
    if distance is None:
        date_score = 5
        date_explanation = (
            "Document date was unavailable, so only a neutral date score was applied."
        )
    elif distance <= 2:
        date_score = 20
        date_explanation = f"Bank booking is {distance} day(s) from the expected date."
    elif distance <= 7:
        date_score = 15
        date_explanation = f"Bank booking is within one week ({distance} days)."
    elif distance <= 30:
        date_score = 8
        date_explanation = f"Bank booking is within 30 days ({distance} days)."
    else:
        date_score = 0
        date_explanation = f"Bank booking is {distance} days away from the document date."
    factors.append(
        MatchFactor(
            name="Date",
            score=date_score,
            maximum=20,
            explanation=date_explanation,
        )
    )
    score += date_score

    reference_haystack = " ".join(
        part for part in [transaction.reference, transaction.description] if part
    )
    reference_similarity = max(
        _similarity(extraction.invoice_number, reference_haystack),
        _similarity(extraction.payment_reference, reference_haystack),
    )
    if reference_similarity >= 0.95:
        reference_score = 20
        reference_explanation = "Invoice or payment reference is an exact/contained match."
    elif reference_similarity >= 0.7:
        reference_score = 14
        reference_explanation = "Bank reference strongly resembles the invoice reference."
    elif reference_similarity >= 0.45:
        reference_score = 6
        reference_explanation = "Bank reference has a weak similarity to the document reference."
    else:
        reference_score = 0
        reference_explanation = "No useful invoice reference match was found."
    factors.append(
        MatchFactor(
            name="Reference",
            score=reference_score,
            maximum=20,
            explanation=reference_explanation,
        )
    )
    score += reference_score

    merchant_text = " ".join(
        part for part in [transaction.merchant_name, transaction.description] if part
    )
    supplier_similarity = _similarity(extraction.supplier_name, merchant_text)
    if supplier_similarity >= 0.9:
        supplier_score = 10
        supplier_explanation = "Supplier and merchant names match."
    elif supplier_similarity >= 0.65:
        supplier_score = 7
        supplier_explanation = "Supplier and merchant names are strongly similar."
    elif supplier_similarity >= 0.4:
        supplier_score = 3
        supplier_explanation = "Supplier name similarity is weak."
    else:
        supplier_score = 0
        supplier_explanation = "No supplier-name match was found."
    factors.append(
        MatchFactor(
            name="Supplier",
            score=supplier_score,
            maximum=10,
            explanation=supplier_explanation,
        )
    )
    score += supplier_score

    currency_score = 5 if extraction.currency == transaction.currency else 0
    factors.append(
        MatchFactor(
            name="Currency",
            score=currency_score,
            maximum=5,
            explanation=(
                f"Currency matches ({extraction.currency})."
                if currency_score
                else (
                    f"Currency mismatch: document {extraction.currency}, "
                    f"bank {transaction.currency}."
                )
            ),
        )
    )
    score += currency_score

    if transaction.already_reconciled:
        score = min(score, 20)
        factors.append(
            MatchFactor(
                name="Existing reconciliation",
                score=-80,
                maximum=0,
                explanation="This transaction is already reconciled and cannot be reused.",
            )
        )

    return MatchCandidate(
        transaction=transaction,
        score=max(0, min(100, score)),
        amount_variance_percent=variance,
        date_distance_days=distance,
        factors=factors,
    )


def rank_candidates(
    extraction: DocumentExtraction, transactions: list[BankTransaction]
) -> list[MatchCandidate]:
    return sorted(
        (score_transaction(extraction, transaction) for transaction in transactions),
        key=lambda candidate: (candidate.score, -candidate.amount_variance_percent),
        reverse=True,
    )
