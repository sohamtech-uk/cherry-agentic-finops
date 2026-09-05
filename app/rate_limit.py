"""Shared application rate limiter.

The limiter is enabled in production. Cloud Run instances enforce their own counters; a shared
Redis storage backend can be configured later when globally consistent limits are required.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.environment == "production",
    headers_enabled=True,
)
