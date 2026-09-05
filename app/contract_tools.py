from __future__ import annotations

from datetime import date
from typing import Any

from app.contracts import ContractDocumentType, get_contract_repository


def search_lpa(
    query: str,
    fund_name: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search ingested LPA clauses and return ranked, page-level citations.

    Args:
        query: Contract concept or phrase to find.
        fund_name: Optional exact fund-name filter.
        limit: Maximum number of cited clauses to return, from 1 to 20.
    """

    result = get_contract_repository().search(
        query=query,
        document_type=ContractDocumentType.LPA,
        fund_name=fund_name,
        limit=limit,
    )
    return result.model_dump(mode="json")


def search_side_letter(
    query: str,
    investor_name: str | None = None,
    fund_name: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search side-letter clauses, optionally scoped to one investor and fund.

    Args:
        query: Contract concept or phrase to find.
        investor_name: Optional exact investor-name filter.
        fund_name: Optional exact fund-name filter.
        limit: Maximum number of cited clauses to return, from 1 to 20.
    """

    result = get_contract_repository().search(
        query=query,
        document_type=ContractDocumentType.SIDE_LETTER,
        fund_name=fund_name,
        investor_name=investor_name,
        limit=limit,
    )
    return result.model_dump(mode="json")


def extract_clause(document_id: str, section_reference: str) -> dict[str, Any]:
    """Return the complete text and citation for one section of an ingested contract."""

    result = get_contract_repository().extract_clause(document_id, section_reference)
    return result.model_dump(mode="json")


def get_effective_date(document_id: str) -> dict[str, Any]:
    """Return the effective date and supporting text for an ingested contract."""

    result = get_contract_repository().get_effective_date(document_id)
    return result.model_dump(mode="json")


def get_investor_rule(
    investor_name: str,
    rule_name: str,
    as_of_date: str | None = None,
    fund_name: str | None = None,
) -> dict[str, Any]:
    """Resolve an effective investor rule using side-letter-over-LPA precedence.

    Args:
        investor_name: Exact investor name attached to the side letter.
        rule_name: Supported structured rule name, such as
            management_fee_offsets_called_capital or management_fee_rate.
        as_of_date: Optional ISO date used to exclude future contract terms.
        fund_name: Optional exact fund-name filter.
    """

    parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
    result = get_contract_repository().get_investor_rule(
        investor_name=investor_name,
        rule_name=rule_name,
        as_of_date=parsed_date,
        fund_name=fund_name,
    )
    return result.model_dump(mode="json")
