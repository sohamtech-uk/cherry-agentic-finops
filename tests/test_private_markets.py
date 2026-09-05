from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from app.private_markets import (
    CapitalCallExtraction,
    PrivateMarketsAction,
    analyse_private_markets_case,
    parse_cash_csv,
    parse_commitment_workbook,
)


def make_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "LP_Commitments"
    ws.append(
        [
            "LP_ID",
            "LP_Name",
            "Total_Commitment_GBP",
            "Called_To_Date_Before_Current_GBP",
            "Current_Call_GBP",
            "Remaining_After_Current_Call_GBP",
            "Due_Date",
            "Call_Notice_ID",
            "Call_Status",
        ]
    )
    ws.append(
        [
            "LP-001",
            "Oakfield Pension Trust",
            5_000_000,
            2_750_000,
            1_250_000,
            1_000_000,
            date(2026, 9, 6),
            "NCGFIII-CALL-2026-03",
            "PARTIAL_RECEIPT",
        ]
    )
    bank = wb.create_sheet("Approved_Bank_Details")
    bank.append(
        [
            "Fund_ID",
            "Fund_Name",
            "Beneficiary",
            "Approved_Bank_Name",
            "Approved_Sort_Code",
            "Approved_Account_Last4",
            "Approval_Status",
        ]
    )
    bank.append(
        [
            "FUND-001",
            "Cedar Peak Growth Fund III LP",
            "Cedar Peak Growth Fund III LP",
            "Cedar Demo Bank plc",
            "00-00-00",
            "2381",
            "APPROVED",
        ]
    )
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def test_fixture_case_flags_changed_bank_and_short_receipt() -> None:
    dataset = parse_commitment_workbook(make_workbook())
    cash = parse_cash_csv(
        b"transaction_id,booking_date,direction,amount_gbp,currency,counterparty,reference,description,status\n"
        b"TXN-1,2026-09-05,CREDIT,1249500.00,GBP,Oakfield Pension Trust,"
        b"NCGFIII-CALL-2026-03 / LP-001,Capital contribution,BOOKED\n"
    )
    call = CapitalCallExtraction(
        fund_name="Cedar Peak Growth Fund III LP",
        investor_name="Oakfield Pension Trust",
        lp_reference="LP-001",
        notice_id="NCGFIII-CALL-2026-03",
        issue_date=date(2026, 8, 28),
        due_date=date(2026, 9, 6),
        current_call=1_250_000,
        total_commitment=5_000_000,
        called_before_current=2_750_000,
        remaining_after_current=1_000_000,
        bank_name="Harbour Demo Bank plc",
        sort_code="99-99-99",
        account_last4="9437",
        confidence=98,
        source="fixture",
    )

    analysis = analyse_private_markets_case(call, dataset, cash, as_of_date=date(2026, 9, 5))

    assert analysis.action == PrivateMarketsAction.REQUEST_EVIDENCE
    assert analysis.expected_amount == 1_250_000
    assert analysis.received_amount == 1_249_500
    assert analysis.variance_amount == -500
    codes = {finding.code for finding in analysis.findings}
    assert "commitment.call_amount_match" in codes
    assert "commitment.remaining_math_valid" in codes
    assert "bank.instructions_changed" in codes
    assert "cash.short_receipt" in codes
    assert analysis.outstanding_amount == 500
    assert analysis.funding_progress_percent == Decimal("99.96")
    assert {item.code for item in analysis.work_items} == {
        "verify_bank_instructions",
        "resolve_cash_shortfall",
    }


def test_exact_match_can_auto_reconcile_when_bank_details_match() -> None:
    dataset = parse_commitment_workbook(make_workbook())
    cash = parse_cash_csv(
        b"transaction_id,booking_date,direction,amount_gbp,currency,counterparty,reference,description,status\n"
        b"TXN-1,2026-09-05,CREDIT,1250000.00,GBP,Oakfield Pension Trust,"
        b"NCGFIII-CALL-2026-03 / LP-001,Capital contribution,BOOKED\n"
    )
    call = CapitalCallExtraction(
        fund_name="Cedar Peak Growth Fund III LP",
        investor_name="Oakfield Pension Trust",
        lp_reference="LP-001",
        notice_id="NCGFIII-CALL-2026-03",
        due_date=date(2026, 9, 6),
        current_call=1_250_000,
        bank_name="Cedar Demo Bank plc",
        sort_code="00-00-00",
        account_last4="2381",
        confidence=99,
        source="fixture",
    )

    analysis = analyse_private_markets_case(call, dataset, cash)

    assert analysis.action == PrivateMarketsAction.AUTO_RECONCILE
    assert analysis.variance_amount == 0
    assert {finding.code for finding in analysis.findings} >= {
        "bank.instructions_match",
        "cash.exact_match",
    }
    assert analysis.work_items == []


def test_low_confidence_and_incomplete_bank_details_block_automation() -> None:
    dataset = parse_commitment_workbook(make_workbook())
    cash = parse_cash_csv(
        b"transaction_id,booking_date,direction,amount_gbp,currency,counterparty,reference,description,status\n"
        b"TXN-1,2026-09-05,CREDIT,1250000.00,GBP,Oakfield Pension Trust,"
        b"NCGFIII-CALL-2026-03 / LP-001,Capital contribution,BOOKED\n"
    )
    call = CapitalCallExtraction(
        fund_name="Cedar Peak Growth Fund III LP",
        investor_name="Oakfield Pension Trust",
        lp_reference="LP-001",
        notice_id="NCGFIII-CALL-2026-03",
        due_date=date(2026, 9, 6),
        current_call=1_250_000,
        account_last4=None,
        confidence=64,
        source="fixture",
    )

    analysis = analyse_private_markets_case(call, dataset, cash)

    assert analysis.action == PrivateMarketsAction.REQUEST_EVIDENCE
    assert {finding.code for finding in analysis.findings} >= {
        "extraction.low_confidence",
        "bank.instructions_incomplete",
    }
