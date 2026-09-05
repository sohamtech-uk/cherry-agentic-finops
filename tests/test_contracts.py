from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.contract_tools import (
    extract_clause,
    get_effective_date,
    get_investor_rule,
    search_lpa,
    search_side_letter,
)
from app.contracts import (
    ContractClauseNotFound,
    ContractDocumentType,
    InvestorCapitalCheck,
    NAVCheckStatus,
    RuleStatus,
    get_contract_repository,
)

FUND_NAME = "Cedar Peak Growth Fund III LP"
INVESTOR_NAME = "Oakfield Pension Trust"
LPA_TEXT = b"""LIMITED PARTNERSHIP AGREEMENT
Effective as of 1 January 2025

Section 4.2 Management Fees and Called Capital
Management fees shall not reduce or offset Called Capital for an Investor unless an
investor-specific side letter expressly provides otherwise.

Section 8.1 Investor Reporting
The General Partner shall provide quarterly investor reporting.
"""
SIDE_LETTER_TEXT = b"""OAKFIELD PENSION TRUST SIDE LETTER
Effective as of 1 March 2025

Section 4.2 Management Fee Offset
Notwithstanding Section 4.2 of the Partnership Agreement, solely with respect to Oakfield Pension
Trust, each management fee shall reduce, pound-for-pound, and offset against Called Capital.

Section 7.3 Reporting
Oakfield Pension Trust shall receive quarterly reporting.
"""


def make_text_pdf(lines: list[str]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    operations = ["BT /F1 11 Tf 72 720 Td 15 TL"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        operations.append(f"({escaped}) Tj T*")
    operations.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(operations).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture(autouse=True)
def clean_repository() -> None:
    repository = get_contract_repository()
    repository.clear()
    yield
    repository.clear()


def ingest_contracts() -> tuple[str, str]:
    repository = get_contract_repository()
    lpa = repository.ingest(
        content=LPA_TEXT,
        mime_type="text/plain",
        file_name="fund-lpa.txt",
        document_type=ContractDocumentType.LPA,
        fund_name=FUND_NAME,
    )
    side_letter = repository.ingest(
        content=SIDE_LETTER_TEXT,
        mime_type="text/plain",
        file_name="oakfield-side-letter.txt",
        document_type=ContractDocumentType.SIDE_LETTER,
        fund_name=FUND_NAME,
        investor_name=INVESTOR_NAME,
    )
    return lpa.document_id, side_letter.document_id


def test_five_contract_tools_return_cited_evidence() -> None:
    lpa_id, side_letter_id = ingest_contracts()

    lpa_search = search_lpa("management fee called capital", FUND_NAME)
    side_search = search_side_letter(
        "management fee offset called capital",
        INVESTOR_NAME,
        FUND_NAME,
    )
    clause = extract_clause(side_letter_id, "4.2")
    effective_date = get_effective_date(lpa_id)
    investor_rule = get_investor_rule(
        INVESTOR_NAME,
        "management_fee_offsets_called_capital",
        "2026-06-30",
        FUND_NAME,
    )

    assert lpa_search["hits"][0]["citation"]["section_reference"] == "4.2"
    assert side_search["hits"][0]["citation"]["document_id"] == side_letter_id
    assert "offset against Called Capital" in clause["text"]
    assert effective_date["effective_date"] == "2025-01-01"
    assert investor_rule["status"] == "found"
    assert investor_rule["value"] is True
    assert investor_rule["source_precedence"] == "side_letter"
    assert investor_rule["citations"][0]["section_reference"] == "4.2"


def test_rule_resolution_respects_effective_date_and_lpa_fallback() -> None:
    ingest_contracts()

    result = get_contract_repository().get_investor_rule(
        investor_name=INVESTOR_NAME,
        rule_name="management_fee_offsets_called_capital",
        as_of_date=date(2025, 2, 1),
        fund_name=FUND_NAME,
    )

    assert result.status == RuleStatus.FOUND
    assert result.value is False
    assert result.source_precedence == ContractDocumentType.LPA


def test_side_letter_does_not_apply_to_a_different_investor() -> None:
    ingest_contracts()

    result = get_contract_repository().get_investor_rule(
        investor_name="Orchard Institutional LP",
        rule_name="management_fee_offsets_called_capital",
        as_of_date=date(2026, 6, 30),
        fund_name=FUND_NAME,
    )

    assert result.status == RuleStatus.FOUND
    assert result.value is False
    assert result.source_precedence == ContractDocumentType.LPA


def test_side_letter_without_explicit_override_requires_review() -> None:
    repository = get_contract_repository()
    repository.ingest(
        content=LPA_TEXT,
        mime_type="text/plain",
        file_name="fund-lpa.txt",
        document_type=ContractDocumentType.LPA,
        fund_name=FUND_NAME,
    )
    repository.ingest(
        content=(
            b"Effective as of 1 March 2025\n"
            b"Section 4.2 Management Fee Note\n"
            b"The management fee shall reduce Called Capital."
        ),
        mime_type="text/plain",
        file_name="fee-note-side-letter.txt",
        document_type=ContractDocumentType.SIDE_LETTER,
        fund_name=FUND_NAME,
        investor_name=INVESTOR_NAME,
    )

    result = repository.get_investor_rule(
        investor_name=INVESTOR_NAME,
        rule_name="management_fee_offsets_called_capital",
        as_of_date=date(2026, 6, 30),
        fund_name=FUND_NAME,
    )

    assert result.status == RuleStatus.REVIEW_REQUIRED
    assert "explicit override" in result.explanation


def test_conflicting_active_side_letters_require_review() -> None:
    ingest_contracts()
    get_contract_repository().ingest(
        content=(
            b"Effective as of 1 March 2025\n"
            b"Section 4.2 Management Fee Treatment\n"
            b"Notwithstanding Section 4.2, the management fee shall not reduce or offset "
            b"Called Capital."
        ),
        mime_type="text/plain",
        file_name="conflicting-side-letter.txt",
        document_type=ContractDocumentType.SIDE_LETTER,
        fund_name=FUND_NAME,
        investor_name=INVESTOR_NAME,
    )

    result = get_contract_repository().get_investor_rule(
        investor_name=INVESTOR_NAME,
        rule_name="management_fee_offsets_called_capital",
        as_of_date=date(2026, 6, 30),
        fund_name=FUND_NAME,
    )

    assert result.status == RuleStatus.CONFLICT
    assert result.requires_review is True


def test_investor_capital_check_uses_contract_rule_deterministically() -> None:
    ingest_contracts()

    result = get_contract_repository().check_investor_capital(
        InvestorCapitalCheck(
            investor_name=INVESTOR_NAME,
            fund_name=FUND_NAME,
            gross_called_capital=2_000_000,
            management_fee=125_000,
            administrator_called_capital=2_000_000,
            as_of_date=date(2026, 6, 30),
        )
    )

    assert result.status == NAVCheckStatus.FAIL
    assert result.expected_called_capital == Decimal("1875000.00")
    assert result.variance == Decimal("125000.00")
    assert result.rule.citations[0].section_reference == "4.2"


def test_unstructured_rule_requires_review_instead_of_guessing() -> None:
    repository = get_contract_repository()
    repository.ingest(
        content=b"Section 6.4 Expenses\nExpenses will be treated on terms agreed by the parties.",
        mime_type="text/plain",
        file_name="ambiguous-lpa.txt",
        document_type=ContractDocumentType.LPA,
        fund_name=FUND_NAME,
    )

    result = repository.get_investor_rule(
        investor_name=INVESTOR_NAME,
        rule_name="expense_allocation",
        fund_name=FUND_NAME,
    )

    assert result.status == RuleStatus.REVIEW_REQUIRED
    assert result.requires_review is True
    assert result.value is None


def test_undated_side_letter_blocks_rule_resolution() -> None:
    repository = get_contract_repository()
    repository.ingest(
        content=LPA_TEXT,
        mime_type="text/plain",
        file_name="fund-lpa.txt",
        document_type=ContractDocumentType.LPA,
        fund_name=FUND_NAME,
    )
    repository.ingest(
        content=(
            b"Section 4.2 Management Fee Offset\n"
            b"Notwithstanding Section 4.2, each management fee shall reduce, pound-for-pound, "
            b"Called Capital."
        ),
        mime_type="text/plain",
        file_name="undated-side-letter.txt",
        document_type=ContractDocumentType.SIDE_LETTER,
        fund_name=FUND_NAME,
        investor_name=INVESTOR_NAME,
    )

    result = repository.get_investor_rule(
        investor_name=INVESTOR_NAME,
        rule_name="management_fee_offsets_called_capital",
        as_of_date=date(2026, 6, 30),
        fund_name=FUND_NAME,
    )

    assert result.status == RuleStatus.REVIEW_REQUIRED
    assert result.effective_date is None
    assert "no effective date" in result.explanation


def test_missing_clause_fails_closed() -> None:
    lpa_id, _ = ingest_contracts()

    with pytest.raises(ContractClauseNotFound):
        get_contract_repository().extract_clause(lpa_id, "99.9")


def test_side_letter_requires_investor_scope() -> None:
    with pytest.raises(ValueError, match="investor_name is required"):
        get_contract_repository().ingest(
            content=SIDE_LETTER_TEXT,
            mime_type="text/plain",
            file_name="unscoped-side-letter.txt",
            document_type=ContractDocumentType.SIDE_LETTER,
            fund_name=FUND_NAME,
        )


def test_pdf_ingestion_preserves_page_and_section_citation() -> None:
    document = get_contract_repository().ingest(
        content=make_text_pdf(
            [
                "Effective as of 1 January 2025",
                "Section 4.2 Management Fee Rate",
                "The management fee rate is 1.5% per annum.",
            ]
        ),
        mime_type="application/pdf",
        file_name="fund-lpa.pdf",
        document_type=ContractDocumentType.LPA,
        fund_name=FUND_NAME,
    )

    result = get_contract_repository().search(
        query="management fee rate",
        document_type=ContractDocumentType.LPA,
    )

    assert document.effective_date == date(2025, 1, 1)
    assert result.hits[0].citation.page_number == 1
    assert result.hits[0].citation.section_reference == "4.2"
