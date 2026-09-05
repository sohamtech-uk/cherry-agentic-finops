from __future__ import annotations

from app.contracts import (
    ContractDocumentType,
    ContractRepository,
    RuleStatus,
    get_contract_repository,
)
from app.nav_quality import AdministratorNAVSummary, SideLetterRule


def resolve_contract_rules_for_nav(
    summary: AdministratorNAVSummary,
    repository: ContractRepository | None = None,
) -> list[SideLetterRule]:
    """Resolve source-backed contract terms for the NAV controller.

    The Contract Agent determines identity, precedence, effective date and source evidence. The NAV
    controller receives a rule only when the side letter explicitly overrides the LPA. Unresolved
    investor-specific evidence is also passed through, but marked so it can only trigger review.
    """

    store = repository or get_contract_repository()
    rules: list[SideLetterRule] = []
    for investor_line in summary.investor_capital:
        result = store.get_investor_rule(
            investor_name=investor_line.investor,
            rule_name="management_fee_offsets_called_capital",
            as_of_date=summary.period_end,
            fund_name=summary.legal_entity,
        )
        if result.source_precedence != ContractDocumentType.SIDE_LETTER:
            continue
        citation = result.citations[0] if result.citations else None
        document = store.get(citation.document_id) if citation else None
        if result.status == RuleStatus.FOUND and result.value is not True:
            continue
        rules.append(
            SideLetterRule(
                investor=investor_line.investor,
                rule=(
                    "management_fee_offsets_called_capital"
                    if result.status == RuleStatus.FOUND
                    else "unresolved_contract_rule"
                ),
                source=(
                    f"{citation.file_name} §{citation.section_reference}, page "
                    f"{citation.page_number}"
                    if citation
                    else None
                ),
                document_id=citation.document_id if citation else None,
                document_name=citation.file_name if citation else None,
                section_reference=citation.section_reference if citation else None,
                page_number=citation.page_number if citation else None,
                source_excerpt=citation.quote if citation else None,
                source_sha256=document.sha256 if document else None,
                effective_date=result.effective_date,
                explicit_override=result.status == RuleStatus.FOUND,
                resolution_status=result.status.value,
                resolution_explanation=result.explanation,
            )
        )
    return rules
