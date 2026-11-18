"""utils.py

Logging setup, and masking of social security numbers in text that is indexed or shown to a model.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime

# --- Logging -----------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra fields passed via ``extra={"ctx": {...}}``."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = getattr(record, "ctx", None)
        if ctx:
            payload.update(ctx)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", as_json: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if as_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party loggers are noisy at INFO and some echo document text.
    for noisy in ("docling", "docling_core", "rapidocr", "RapidOCR", "httpx", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --- Social security numbers ---------------------------------------------------

# 3-2-4 digits with one separator are always masked. Nine bare digits only after a label that names them: elsewhere
# they are amounts (spreadsheet cells and OCR text are indexed verbatim), account or order numbers. Employer
# identification numbers (`12-3456789`) are never masked; one printed without its dash after "TIN" is.
_SSN = re.compile(r"\b\d{3}([- ])\d{2}\1(\d{4})\b")
_BARE_SSN = re.compile(r"(\b(?:SSN|ITIN|TIN|social security(?: number| no\.?)?)\b\W{0,4}(?:#|no\.?|number)?"
                       r"\W{0,3})\d{5}(\d{4})\b(?![.,]\d)", re.IGNORECASE)


def mask_ssns(text: str) -> str:
    """SSNs to their last four digits (policy above).

    *Usage:*
    >>> mask_ssns("SSN 412-56-7890 / 412 56 7890, EIN 84-1736295")
    'SSN XXX-XX-7890 / XXX-XX-7890, EIN 84-1736295'
    >>> mask_ssns("Recipient's TIN: 412567890, account 412567890, wages 412567890")
    "Recipient's TIN: XXX-XX-7890, account 412567890, wages 412567890"
    """
    return _BARE_SSN.sub(r"\1XXX-XX-\2", _SSN.sub(r"XXX-XX-\2", text))
