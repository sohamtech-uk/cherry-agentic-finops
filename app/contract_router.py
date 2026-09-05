from __future__ import annotations

import hmac
import os
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_settings
from app.contract_demo import ContractDemoResponse, build_synthetic_side_letter_demo
from app.contracts import (
    ContractClauseNotFound,
    ContractDocument,
    ContractDocumentNotFound,
    ContractDocumentType,
    InvestorCapitalCheck,
    get_contract_repository,
)

settings = get_settings()
repository = get_contract_repository()
router = APIRouter(prefix="/api/contracts", tags=["contract-intelligence"])
MAX_CONTRACT_FILES = 20


def require_contract_access(
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Contract access is disabled until CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN "
                "is configured."
            ),
        )
    if not x_cherry_demo_token or not hmac.compare_digest(x_cherry_demo_token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


ContractAccess = Annotated[None, Depends(require_contract_access)]


class ContractSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    fund_name: str | None = Field(default=None, max_length=240)
    investor_name: str | None = Field(default=None, max_length=240)
    limit: int = Field(default=5, ge=1, le=20)


class InvestorRuleRequest(BaseModel):
    investor_name: str = Field(min_length=2, max_length=240)
    rule_name: str = Field(min_length=2, max_length=120)
    as_of_date: date | None = None
    fund_name: str | None = Field(default=None, max_length=240)


def _document_summary(document: ContractDocument) -> dict[str, Any]:
    payload = document.model_dump(mode="json", exclude={"clauses"})
    payload["clause_count"] = len(document.clauses)
    return payload


@router.get("/health")
async def contract_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "workflow": "contract_intelligence",
        "accepted_document_types": ["lpa", "side_letter"],
        "accepted_file_formats": ["pdf", "txt", "md"],
        "tools": [
            "search_lpa",
            "search_side_letter",
            "extract_clause",
            "get_effective_date",
            "get_investor_rule",
        ],
        "supported_rules": [
            "management_fee_offsets_called_capital",
            "management_fee_rate",
            "expense_allocation",
            "reporting_frequency",
            "carry_rate",
            "mfn",
            "excuse_right",
        ],
        "control_boundary": (
            "Contract text is retrieved and structured with citations; deterministic code "
            "performs NAV calculations and unresolved terms require human review."
        ),
        "legal_boundary": "No legal advice or enforceability decision.",
    }


@router.post("/documents")
async def ingest_contract_documents(
    _: ContractAccess,
    files: Annotated[list[UploadFile], File(description="LPA or side-letter PDF/TXT files")],
    document_type: Annotated[ContractDocumentType, Form()],
    fund_name: Annotated[str, Form(min_length=2, max_length=240)],
    investor_name: Annotated[str | None, Form(max_length=240)] = None,
    effective_date: Annotated[date | None, Form()] = None,
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one contract document is required.")
    if len(files) > MAX_CONTRACT_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"A maximum of {MAX_CONTRACT_FILES} contract files can be uploaded at once.",
        )
    if document_type == ContractDocumentType.SIDE_LETTER and not investor_name:
        raise HTTPException(status_code=422, detail="investor_name is required for side letters.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    documents: list[dict[str, Any]] = []
    for upload in files:
        file_name = upload.filename or "contract"
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{file_name!r} exceeds the {settings.max_upload_mb} MB per-file limit.",
            )
        try:
            document = repository.ingest(
                content=content,
                mime_type=upload.content_type or "application/octet-stream",
                file_name=file_name,
                document_type=document_type,
                fund_name=fund_name,
                investor_name=investor_name,
                effective_date=effective_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid {file_name!r}: {exc}") from exc
        documents.append(_document_summary(document))
    return {"status": "ingested", "count": len(documents), "documents": documents}


@router.get("/documents")
async def list_contract_documents(_: ContractAccess) -> dict[str, Any]:
    documents = [document.model_dump(mode="json") for document in repository.list_documents()]
    return {"count": len(documents), "documents": documents}


@router.post("/search/lpa")
async def search_lpa_endpoint(
    request: ContractSearchRequest,
    _: ContractAccess,
) -> dict[str, Any]:
    try:
        result = repository.search(
            query=request.query,
            document_type=ContractDocumentType.LPA,
            fund_name=request.fund_name,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/search/side-letter")
async def search_side_letter_endpoint(
    request: ContractSearchRequest,
    _: ContractAccess,
) -> dict[str, Any]:
    try:
        result = repository.search(
            query=request.query,
            document_type=ContractDocumentType.SIDE_LETTER,
            fund_name=request.fund_name,
            investor_name=request.investor_name,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.get("/documents/{document_id}/clauses/{section_reference}")
async def extract_clause_endpoint(
    document_id: str,
    section_reference: str,
    _: ContractAccess,
) -> dict[str, Any]:
    try:
        result = repository.extract_clause(document_id, section_reference)
    except ContractDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Contract document not found.") from exc
    except ContractClauseNotFound as exc:
        raise HTTPException(status_code=404, detail="Contract clause not found.") from exc
    return result.model_dump(mode="json")


@router.get("/documents/{document_id}/effective-date")
async def get_effective_date_endpoint(
    document_id: str,
    _: ContractAccess,
) -> dict[str, Any]:
    try:
        result = repository.get_effective_date(document_id)
    except ContractDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Contract document not found.") from exc
    return result.model_dump(mode="json")


@router.post("/investor-rules/resolve")
async def get_investor_rule_endpoint(
    request: InvestorRuleRequest,
    _: ContractAccess,
) -> dict[str, Any]:
    try:
        result = repository.get_investor_rule(
            investor_name=request.investor_name,
            rule_name=request.rule_name,
            as_of_date=request.as_of_date,
            fund_name=request.fund_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/nav-checks/investor-capital")
async def check_investor_capital_endpoint(
    request: InvestorCapitalCheck,
    _: ContractAccess,
) -> dict[str, Any]:
    try:
        result = repository.check_investor_capital(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/demo", response_model=ContractDemoResponse, include_in_schema=False)
@router.post("/demo/side-letter-fee", response_model=ContractDemoResponse)
async def contract_demo() -> ContractDemoResponse:
    return build_synthetic_side_letter_demo()
