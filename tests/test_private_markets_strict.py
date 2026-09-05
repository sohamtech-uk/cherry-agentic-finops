from datetime import date

from app.private_markets import (
    ApprovedBankDetails,
    CapitalCallExtraction,
    FundCashTransaction,
    LPCommitment,
    PrivateMarketsAction,
    PrivateMarketsDataset,
)
from app.private_markets_strict import analyse_private_markets_case_strict


def make_call() -> CapitalCallExtraction:
    return CapitalCallExtraction(
        fund_name="Cedar Peak Growth Fund III LP",
        investor_name="Oakfield Pension Trust",
        lp_reference="LP-001",
        notice_id="NCGFIII-CALL-2026-03",
        issue_date=date(2026, 8, 28),
        due_date=date(2026, 9, 6),
        currency="GBP",
        total_commitment=5_000_000,
        called_before_current=2_750_000,
        current_call=1_250_000,
        remaining_after_current=1_000_000,
        beneficiary="Cedar Peak Growth Fund III LP",
        bank_name="Cedar Demo Bank plc",
        sort_code="00-00-00",
        account_last4="2381",
        payment_reference="NCGFIII-CALL-2026-03 / LP-001",
        confidence=98,
        source="fixture",
    )


def make_dataset(*, approval_status: str | None = "APPROVED") -> PrivateMarketsDataset:
    return PrivateMarketsDataset(
        commitments=[
            LPCommitment(
                lp_id="LP-001",
                lp_name="Oakfield Pension Trust",
                total_commitment=5_000_000,
                called_before_current=2_750_000,
                current_call=1_250_000,
                remaining_after_current=1_000_000,
                due_date=date(2026, 9, 6),
                call_notice_id="NCGFIII-CALL-2026-03",
            )
        ],
        approved_bank_details=[
            ApprovedBankDetails(
                fund_id="FUND-001",
                fund_name="Cedar Peak Growth Fund III LP",
                beneficiary="Cedar Peak Growth Fund III LP",
                bank_name="Cedar Demo Bank plc",
                sort_code="00-00-00",
                account_last4="2381",
                approval_status=approval_status,
            )
        ],
    )


def strong_cash(amount: int = 1_250_000) -> list[FundCashTransaction]:
    return [
        FundCashTransaction(
            transaction_id="TXN-STRONG-1",
            booking_date=date(2026, 9, 5),
            direction="credit",
            amount=amount,
            currency="GBP",
            counterparty="Oakfield Pension Trust",
            reference="NCGFIII-CALL-2026-03 / LP-001",
            description="Capital contribution",
            status="BOOKED",
        )
    ]


def test_blank_bank_approval_status_fails_closed() -> None:
    analysis = analyse_private_markets_case_strict(
        make_call(),
        make_dataset(approval_status=None),
        strong_cash(),
        as_of_date=date(2026, 9, 5),
    )

    assert analysis.action == PrivateMarketsAction.REQUEST_EVIDENCE
    assert "bank.record_not_approved" in {finding.code for finding in analysis.findings}
    assert any(item.owner == "Treasury control" for item in analysis.work_items)


def test_capital_call_cannot_exceed_remaining_commitment() -> None:
    dataset = make_dataset()
    dataset.commitments[0].called_before_current = 4_500_000
    dataset.commitments[0].current_call = 1_250_000
    dataset.commitments[0].remaining_after_current = -750_000

    analysis = analyse_private_markets_case_strict(
        make_call(),
        dataset,
        strong_cash(),
        as_of_date=date(2026, 9, 5),
    )

    assert analysis.action == PrivateMarketsAction.REQUEST_EVIDENCE
    assert "commitment.call_exceeds_remaining" in {
        finding.code for finding in analysis.findings
    }
    assert any(item.code == "review_commitment_ledger" for item in analysis.work_items)


def test_investor_name_only_cash_never_auto_reconciles() -> None:
    weak_cash = [
        FundCashTransaction(
            transaction_id="TXN-WEAK-1",
            booking_date=date(2026, 9, 5),
            direction="credit",
            amount=1_250_000,
            currency="GBP",
            counterparty="Oakfield Pension Trust",
            reference="UNRELATED-REFERENCE",
            description="Capital contribution",
            status="BOOKED",
        )
    ]

    analysis = analyse_private_markets_case_strict(
        make_call(),
        make_dataset(),
        weak_cash,
        as_of_date=date(2026, 9, 5),
    )

    assert analysis.action == PrivateMarketsAction.REQUEST_EVIDENCE
    assert analysis.received_amount == 0
    codes = {finding.code for finding in analysis.findings}
    assert "cash.weak_match_only" in codes
    assert "cash.missing" in codes


def test_strong_reference_exact_cash_can_close() -> None:
    analysis = analyse_private_markets_case_strict(
        make_call(),
        make_dataset(),
        strong_cash(),
        as_of_date=date(2026, 9, 5),
    )

    assert analysis.action == PrivateMarketsAction.AUTO_RECONCILE
    assert analysis.received_amount == 1_250_000
    assert analysis.outstanding_amount == 0
    assert analysis.work_items == []
