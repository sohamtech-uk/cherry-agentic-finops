from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from app.cash_application.router import router as controller_review_router
from app.config import get_settings
from app.container import get_engine
from app.contract_router import router as contract_router
from app.document_ai import GeminiDocumentExtractor, GeminiUnavailable
from app.models import ApprovalRequest, BankTransaction, RejectionRequest
from app.nav_quality_router import router as nav_quality_router
from app.private_markets_integration_router import router as private_markets_integration_router
from app.private_markets_router import router as private_markets_router
from app.session_router import router as session_router
from app.statement_review_router import router as statement_review_router
from app.workflow import InvalidWorkflowAction, WorkflowNotFound
from app.ylookup_router import router as ylookup_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
settings = get_settings()
engine = get_engine()
extractor = GeminiDocumentExtractor(settings)
transaction_adapter = TypeAdapter(list[BankTransaction])

app = FastAPI(
    title="Cherry Agent API",
    version="0.1.0",
    description=(
        "Autonomous, human-governed finance operations using Gemini, Google ADK and "
        "deterministic financial controls."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment != "production" else [settings.public_base_url],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(private_markets_router)
app.include_router(private_markets_integration_router)
app.include_router(ylookup_router)
app.include_router(session_router)
app.include_router(nav_quality_router)
app.include_router(contract_router)
app.include_router(statement_review_router)
app.include_router(controller_review_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.exception_handler(WorkflowNotFound)
async def workflow_not_found_handler(_: Request, exc: WorkflowNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"detail": f"Workflow {exc.args[0]} was not found."}
    )


@app.exception_handler(InvalidWorkflowAction)
async def invalid_workflow_action_handler(_: Request, exc: InvalidWorkflowAction) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/controller-review", include_in_schema=False)
async def controller_review_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "controller_review.html")


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Return service health on a Cloud Run-safe URL.

    Cloud Run reserves some paths ending in ``z``. In particular, ``/healthz``
    can be intercepted by the platform before the request reaches FastAPI, so
    the production health endpoint deliberately uses ``/health``.
    """

    return {"status": "ok", "service": "cherry-agent", "version": "0.1.0"}


@app.get("/api/config", tags=["operations"])
async def public_config() -> dict[str, object]:
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "gemini_model": settings.gemini_model,
        "google_ready": settings.google_ready,
        "persistence_backend": settings.persistence_backend,
        "auto_reconcile_score": settings.auto_reconcile_score,
        "approval_amount_gbp": settings.approval_amount_gbp,
        "amount_tolerance_percent": settings.amount_tolerance_percent,
        "fundops_studio_configured": bool(settings.fundops_studio_api_url),
        "financial_boundary": "Accounting reconciliation only; no payment initiation.",
    }


@app.get("/api/workflows", tags=["workflows"])
async def list_workflows() -> list[dict[str, object]]:
    return [workflow.model_dump(mode="json") for workflow in engine.list()]


@app.get("/api/workflows/{workflow_id}", tags=["workflows"])
async def get_workflow(workflow_id: str) -> dict[str, object]:
    return engine.get(workflow_id).model_dump(mode="json")


@app.post("/api/demo/{scenario}", tags=["demo"])
async def run_demo(scenario: str) -> dict[str, object]:
    try:
        return engine.run_demo(scenario).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/workflows", tags=["workflows"])
async def create_workflow(
    document: Annotated[UploadFile, File(description="Invoice or receipt PDF/image")],
    transactions_json: Annotated[
        str,
        Form(
            description=(
                "JSON array of candidate bank transactions. Each requires transaction_id, "
                "booking_date, amount and description."
            )
        ),
    ],
) -> dict[str, object]:
    content = await document.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Document exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    mime_type = document.content_type or "application/octet-stream"
    if mime_type not in {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/heic",
    }:
        raise HTTPException(status_code=415, detail=f"Unsupported document type: {mime_type}")

    try:
        raw_transactions = json.loads(transactions_json)
        transactions = transaction_adapter.validate_python(raw_transactions)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid bank transactions: {exc}") from exc

    try:
        extraction = await extractor.extract(content, mime_type, document.filename or "document")
    except GeminiUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    workflow = engine.process(
        extraction=extraction,
        transactions=transactions,
        source_name=document.filename or "document",
    )
    return workflow.model_dump(mode="json")


@app.post("/api/workflows/{workflow_id}/approve", tags=["workflows"])
async def approve_workflow(workflow_id: str, request: ApprovalRequest) -> dict[str, object]:
    return engine.approve(workflow_id, request).model_dump(mode="json")


@app.post("/api/workflows/{workflow_id}/reject", tags=["workflows"])
async def reject_workflow(workflow_id: str, request: RejectionRequest) -> dict[str, object]:
    return engine.reject(workflow_id, request).model_dump(mode="json")


@app.get("/api/workflows/{workflow_id}/evidence", tags=["evidence"])
async def download_evidence(workflow_id: str) -> Response:
    content, cloud_uri = engine.evidence_pack(workflow_id)
    headers = {
        "Content-Disposition": f'attachment; filename="{workflow_id}-evidence.zip"',
        "X-Cherry-Audit-Chain": "verified",
    }
    if cloud_uri:
        headers["X-Cherry-Evidence-URI"] = cloud_uri
    return Response(content=content, media_type="application/zip", headers=headers)


@app.get("/api/month-end", tags=["workflows"])
async def month_end_summary() -> dict[str, object]:
    return engine.month_end_summary().model_dump(mode="json")
