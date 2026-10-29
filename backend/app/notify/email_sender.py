"""Email is logged, not sent (Stage 1). Add a second EmailSender for real delivery later."""

import logging
from typing import Protocol

from app.redaction.engine import RedactedText, require_redacted

logger = logging.getLogger("faultline.email")


class EmailSender(Protocol):
    def send(self, to: str, subject: RedactedText, body: RedactedText) -> None: ...


class LogEmailSender:
    def send(self, to: str, subject: RedactedText, body: RedactedText) -> None:
        logger.info("EMAIL (logged, not sent) to=%s subject=%s body=%s", to, require_redacted(subject), require_redacted(body))
