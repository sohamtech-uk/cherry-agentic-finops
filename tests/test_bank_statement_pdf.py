from datetime import date
from decimal import Decimal

import pytest

from app.bank_statement_pdf import (
    BankStatement,
    _parse_header,
    _rows_to_transactions,
    to_fund_cash_transactions,
)

HEADER_TEXT = """| Statement details
Account name NI ABF I SCSP Closing ledger balance brought forward 13,217,773.59
Account number 240-524291-030 From 31 Mar 2026
Bank name Calder Luxembourg Closing available balance brought forward 13,217,773.59
Currency EUR From 31 Mar 2026
Location Luxembourg Current ledger balance 13,217,773.59
BIC CLDRLULL As at Not Available
IBAN LU035210240524291030 Current available balance 13,217,773.59
Account status Active As at Not Available
Account type Current account Specified date range 23 Mar 2026 to 31 Mar 2026

"""

TABLE_HEADER_ROW = [
    "Bank reference",
    "Customer reference",
    "TRN type",
    "Value date",
    "Credit amount",
    "Debit amount",
    "Balance",
    "Time",
    "Post date",
]


def test_parse_header_extracts_all_known_fields() -> None:
    header, warnings = _parse_header(HEADER_TEXT)

    assert warnings == []
    assert header.account_name == "NI ABF I SCSP"
    assert header.account_number == "240-524291-030"
    assert header.bank_name == "Calder Luxembourg"
    assert header.currency == "EUR"
    assert header.location == "Luxembourg"
    assert header.bic == "CLDRLULL"
    assert header.iban == "LU035210240524291030"
    assert header.account_status == "Active"
    assert header.account_type == "Current account"
    assert header.period_from == date(2026, 3, 23)
    assert header.period_to == date(2026, 3, 31)
    assert header.opening_balance == Decimal("13217773.59")
    assert header.current_balance == Decimal("13217773.59")


def test_parse_header_reports_missing_fields_without_raising() -> None:
    header, warnings = _parse_header("| Statement details\nAccount name NI ABF I SCSP\n")

    assert header.account_name is None
    assert any("account_name" in warning for warning in warnings)


def test_rows_to_transactions_pairs_data_and_narrative_rows() -> None:
    rows = [
        TABLE_HEADER_ROW,
        [
            "NONREF",
            "NONREF",
            "TFR-",
            "31 Mar 2026",
            "",
            "-0.44",
            "13,217,773.59",
            "17:46",
            "31 Mar 2026",
        ],
        [
            "Narrative",
            "CHARGES FOR 2, OUTWARD SEPA PAYMENT",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            "10716RS62GWQ",
            "CEPHALUS TRF",
            "TFR+",
            "31 Mar 2026",
            "301,908.70",
            "",
            "13,217,774.03",
            "11:01",
            "31 Mar 2026",
        ],
        ["Narrative", "NORDVIK I.A.B. FUND I, TFR+ PMT", None, None, None, None, None, None, None],
    ]

    transactions, warnings = _rows_to_transactions(rows)

    assert warnings == []
    assert len(transactions) == 2
    debit, credit = transactions
    assert debit.debit_amount == Decimal("-0.44")
    assert debit.credit_amount is None
    assert debit.narrative == "CHARGES FOR 2, OUTWARD SEPA PAYMENT"
    assert credit.credit_amount == Decimal("301908.70")
    assert credit.value_date == date(2026, 3, 31)
    assert credit.balance == Decimal("13217774.03")


def test_rows_to_transactions_skips_balance_checkpoint_rows_without_narrative() -> None:
    rows = [
        TABLE_HEADER_ROW,
        [
            "Balance as at close 31 Mar 2026 103,014.97",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            "TT ABC414K0BGIBU",
            "WILLOWBANK TRF",
            "S+P- CHG",
            "31 Mar 2026",
            "",
            "-5.21",
            "103,014.97",
            "10:45",
            "31 Mar 2026",
        ],
        [
            "Narrative",
            "COMMISSION GBP 5,21, 21398DX37I23",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        [
            "Balance brought forward 30 Mar 2026 46,667.40",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
    ]

    transactions, warnings = _rows_to_transactions(rows)

    assert warnings == []
    assert len(transactions) == 1
    assert transactions[0].debit_amount == Decimal("-5.21")


def test_rows_to_transactions_records_a_warning_for_a_missing_narrative() -> None:
    rows = [
        TABLE_HEADER_ROW,
        ["REF1", "CP", "TFR+", "31 Mar 2026", "10.00", "", "10.00", "09:00", "31 Mar 2026"],
        ["REF2", "CP", "TFR+", "31 Mar 2026", "20.00", "", "30.00", "09:01", "31 Mar 2026"],
    ]

    transactions, warnings = _rows_to_transactions(rows)

    assert len(transactions) == 2
    assert any("no narrative" in warning for warning in warnings)


def test_rows_to_transactions_raises_no_exception_on_bad_date_but_warns() -> None:
    rows = [
        TABLE_HEADER_ROW,
        ["REF1", "CP", "TFR+", "not-a-date", "10.00", "", "10.00", "09:00", "31 Mar 2026"],
        ["Narrative", "text", None, None, None, None, None, None, None],
    ]

    transactions, warnings = _rows_to_transactions(rows)

    assert transactions == []
    assert any("Could not parse transaction row" in warning for warning in warnings)


def test_to_fund_cash_transactions_maps_credit_and_debit_correctly() -> None:
    rows = [
        TABLE_HEADER_ROW,
        ["REF1", "CP", "TFR+", "31 Mar 2026", "100.00", "", "100.00", "09:00", "31 Mar 2026"],
        [
            "Narrative",
            "CAPITAL CALL NCGFIII-CALL-2026-03",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        ["REF2", "CP", "TFR-", "01 Apr 2026", "", "-40.00", "60.00", "09:05", "01 Apr 2026"],
        ["Narrative", "FEE PAYMENT", None, None, None, None, None, None, None],
    ]
    transactions, _ = _rows_to_transactions(rows)
    header, _ = _parse_header(HEADER_TEXT)
    statement = BankStatement(source_file="statement.pdf", header=header, transactions=transactions)

    fund_cash = to_fund_cash_transactions(statement)

    assert len(fund_cash) == 2
    assert fund_cash[0].direction == "credit"
    assert fund_cash[0].amount == Decimal("100.00")
    assert fund_cash[0].currency == "EUR"
    assert "CAPITAL CALL" in fund_cash[0].description
    assert fund_cash[1].direction == "debit"
    assert fund_cash[1].amount == Decimal("40.00")
    # transaction ids must be unique even though bank_reference alone is not
    assert fund_cash[0].transaction_id != fund_cash[1].transaction_id


def test_rows_to_transactions_requires_at_least_one_amount() -> None:
    rows = [
        TABLE_HEADER_ROW,
        ["REF1", "CP", "TFR+", "31 Mar 2026", "", "", "100.00", "09:00", "31 Mar 2026"],
        ["Narrative", "no amount at all", None, None, None, None, None, None, None],
    ]

    transactions, warnings = _rows_to_transactions(rows)

    assert transactions == []
    assert any("neither a credit nor a debit amount" in warning for warning in warnings)


@pytest.mark.parametrize("missing_field", ["account_name", "account_number", "currency"])
def test_parse_header_is_resilient_to_a_single_missing_line(missing_field: str) -> None:
    lines = HEADER_TEXT.splitlines()
    filtered = "\n".join(line for line in lines if missing_field.split("_")[0] not in line.lower())
    header, warnings = _parse_header(filtered)
    assert isinstance(header.currency, str)
    assert isinstance(warnings, list)
