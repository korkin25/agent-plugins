"""Full task evidence for Jev, filtered by the caller's credential redactor.

No packet fields are dropped and no referenced files are opened. This module
cannot promise that arbitrary prose contains no private information: it masks
only the credential patterns implemented by the supplied redactor.
"""
from __future__ import annotations

MAX_INPUT_CHARS = 128 * 1024


def build_context(description, text, redact):
    """Return the entire redacted description and task, without truncation.

    The combined input limit is a processing bound, not a content selection
    budget. Oversized input is rejected wholesale before invoking the redactor;
    callers must skip Jev when ``input_quality.oversized`` is true. Complete
    input reaches the redactor, preserving multiline private-key boundaries.
    """
    description = description if isinstance(description, str) else ""
    text = text if isinstance(text, str) else ""
    if len(description) + len(text) > MAX_INPUT_CHARS:
        return {
            "description": "",
            "task": "",
            "input_quality": {
                "version": 2, "source": "omitted", "redacted": False,
                "oversized": True, "rejected": True,
                "critical_truncation": True,
            },
        }
    safe_description = redact(description)
    safe_task = redact(text)
    return {
        "description": safe_description,
        "task": safe_task,
        "input_quality": {
            "version": 2, "source": "full_text",
            "redacted": safe_description != description or safe_task != text,
            "oversized": False, "rejected": False,
            "critical_truncation": False,
        },
    }
