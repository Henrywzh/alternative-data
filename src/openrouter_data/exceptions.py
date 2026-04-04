class OpenRouterDataError(RuntimeError):
    """Base package exception."""


class ExtractionError(OpenRouterDataError):
    """Raised when source extraction fails."""


class ValidationError(OpenRouterDataError):
    """Raised when parsed data does not satisfy the expected contract."""
