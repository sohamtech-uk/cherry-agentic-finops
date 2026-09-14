from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from agents import cherry_strands
from agents.cherry_strands.agent import MAX_PROMPT_LENGTH, agent_metadata

router = APIRouter(prefix="/api/strands", tags=["strands"])


class StrandsRequest(BaseModel):
    prompt: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT_LENGTH)
    ]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", **agent_metadata()}


@router.post("/invoke")
def invoke(request: StrandsRequest) -> dict[str, Any]:
    try:
        return cherry_strands.invoke_cherry_agent(request.prompt)
    except Exception:
        raise HTTPException(status_code=503, detail="Agent invocation unavailable.") from None
