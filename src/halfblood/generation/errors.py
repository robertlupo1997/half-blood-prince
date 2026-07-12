from __future__ import annotations

import re
from typing import ClassVar


class ProviderError(Exception):
    """Base for all normalized provider-layer errors."""

    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(redact_secrets(message))


class ProviderConfigurationError(ProviderError, ValueError):
    """An unsafe or unresolvable provider configuration."""

    retryable: ClassVar[bool] = False


class ProviderAuthenticationError(ProviderError):
    retryable: ClassVar[bool] = False


class ProviderNotFoundError(ProviderError):
    retryable: ClassVar[bool] = False


class ProviderCapabilityError(ProviderError):
    retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        requested_mode: str | None = None,
    ) -> None:
        self.requested_mode = requested_mode
        super().__init__(message, status_code=status_code)


class ProviderRateLimitError(ProviderError):
    retryable: ClassVar[bool] = True

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, status_code=status_code)


class ProviderTransientError(ProviderError):
    retryable: ClassVar[bool] = True


class ProviderSafetyRefusal(ProviderError):
    retryable: ClassVar[bool] = False


class IncompleteResponseError(ProviderError):
    retryable: ClassVar[bool] = True


class StructuredOutputError(ProviderError):
    retryable: ClassVar[bool] = False


class AnnotationValidationError(ProviderError):
    retryable: ClassVar[bool] = False


_STATUS_TO_ERROR: dict[int, type[ProviderError]] = {
    401: ProviderAuthenticationError,
    403: ProviderAuthenticationError,
    404: ProviderNotFoundError,
    408: ProviderTransientError,
    409: ProviderTransientError,
    425: ProviderTransientError,
    429: ProviderRateLimitError,
}


def classify_status_code(status_code: int) -> type[ProviderError] | None:
    """Map an unambiguous HTTP status code to its taxonomy class."""
    if status_code in _STATUS_TO_ERROR:
        return _STATUS_TO_ERROR[status_code]
    if 500 <= status_code < 600:
        return ProviderTransientError
    return None


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*:\s*)\S+"),
    re.compile(r"(?i)(bearer\s+)\S+"),
    re.compile(
        r"(?i)((?:api[_-]?key|apikey|token|secret|access[_-]?token)\s*[=:]\s*)\S+"
    ),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
)


def redact_secrets(text: str) -> str:
    """Best-effort scrub of key/token-shaped substrings from free text."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
            redacted,
        )
    return redacted
