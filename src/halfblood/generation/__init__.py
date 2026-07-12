"""Generation-facing structured-output contracts."""

from halfblood.generation.errors import (
    AnnotationValidationError,
    IncompleteResponseError,
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderSafetyRefusal,
    ProviderTransientError,
    StructuredOutputError,
    classify_status_code,
    redact_secrets,
)
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    LLMProvider,
    ProviderCapabilities,
)
from halfblood.generation.report import (
    AllPagesFailedError,
    GenerationReport,
    PageGenerationStatus,
)

__all__ = [
    "AllPagesFailedError",
    "AnnotationValidationError",
    "GenerationReport",
    "GenerationRequest",
    "GenerationResult",
    "GenerationUsage",
    "IncompleteResponseError",
    "LLMProvider",
    "PageGenerationStatus",
    "ProviderAuthenticationError",
    "ProviderCapabilities",
    "ProviderCapabilityError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderNotFoundError",
    "ProviderRateLimitError",
    "ProviderSafetyRefusal",
    "ProviderTransientError",
    "StructuredOutputError",
    "classify_status_code",
    "redact_secrets",
]
