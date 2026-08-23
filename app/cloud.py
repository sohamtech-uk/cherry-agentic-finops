from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._publisher: Any | None = None
        self._topic_path: str | None = None

    def _ensure_client(self) -> None:
        if self._publisher is not None or not self._settings.google_cloud_project:
            return
        try:
            from google.cloud import pubsub_v1
        except ImportError:
            logger.warning("Pub/Sub package unavailable; event publishing is disabled.")
            return
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(
            self._settings.google_cloud_project,
            self._settings.pubsub_topic or "finance-workflow-events",
        )

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._settings.cloud_mode or not self._settings.pubsub_topic:
            return
        self._ensure_client()
        if not self._publisher or not self._topic_path:
            return
        body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
        future = self._publisher.publish(self._topic_path, body, event_type=event_type)
        try:
            future.result(timeout=5)
        except Exception:  # pragma: no cover - cloud transport failures are environment-specific
            logger.exception("Failed to publish workflow event")


class EvidenceStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def upload(self, object_name: str, content: bytes, content_type: str) -> str | None:
        if not self._settings.cloud_mode or not self._settings.evidence_bucket:
            return None
        try:
            from google.cloud import storage
        except ImportError:  # pragma: no cover
            logger.warning("Cloud Storage package unavailable; evidence remains downloadable only.")
            return None
        client = storage.Client(project=self._settings.google_cloud_project)
        bucket = client.bucket(self._settings.evidence_bucket)
        blob = bucket.blob(object_name)
        blob.upload_from_string(content, content_type=content_type)
        return f"gs://{self._settings.evidence_bucket}/{object_name}"
