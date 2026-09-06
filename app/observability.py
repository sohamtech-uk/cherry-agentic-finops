from __future__ import annotations

from functools import lru_cache

import neatlogs

from app.config import get_settings


@lru_cache(maxsize=1)
def initialize_neatlogs() -> None:
    """Initialize the process-wide Neatlogs pipeline before any agent SDK imports."""

    settings = get_settings()
    api_key = (
        settings.neatlogs_api_key.get_secret_value()
        if settings.neatlogs_api_key
        else None
    )
    if not api_key:
        return
    neatlogs.init(
        api_key=api_key,
        workflow_name=settings.neatlogs_workflow_name,
        register_shutdown_handlers=False,
    )
