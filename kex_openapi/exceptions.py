"""Exception hierarchy for kex-openapi."""

from __future__ import annotations

from typing import Any


class KexError(Exception):
    """Base class for all kex-openapi errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        response: Any | None = None,
        url: str | None = None,
        params: dict[str, Any] | None = None,
        http_status: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.response = response
        self.url = url
        self.params = params
        self.http_status = http_status
        self.retry_after = retry_after


class KexAuthError(KexError):
    """Raised when an API key is missing, invalid, expired, or unauthorized."""


class KexQuotaExceededError(KexError):
    """Raised when the API reports a request limit violation."""


class KexBadRequestError(KexError):
    """Raised when the request is malformed or rejected."""


class KexMissingParameterError(KexBadRequestError):
    """Raised when the provider reports a missing mandatory parameter."""


class KexInvalidParameterError(KexBadRequestError):
    """Raised when a local or remote parameter value is invalid."""


class KexNotFoundError(KexError):
    """Raised when the provider reports no matching data."""


class KexServerError(KexError):
    """Raised for provider-side or gateway failures."""


class KexServiceUnavailableError(KexServerError):
    """Raised for temporary provider unavailability."""


class KexParseError(KexError):
    """Raised when a response cannot be parsed in the expected shape."""


class KexNetworkError(KexError):
    """Raised for network-level failures."""


class KexTimeoutError(KexNetworkError):
    """Raised when a request times out."""


class KexConnectionError(KexNetworkError):
    """Raised when a connection cannot be established."""


class KexConfigError(KexError):
    """Raised when the client is missing required local configuration."""
