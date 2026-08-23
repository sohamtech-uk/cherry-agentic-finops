from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.repository import build_repository
from app.workflow import WorkflowEngine


@lru_cache(maxsize=1)
def get_engine() -> WorkflowEngine:
    settings = get_settings()
    return WorkflowEngine(settings=settings, repository=build_repository(settings))
