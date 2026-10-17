"""Errors raised by the GW2 API client."""

__all__ = [
    "APIError",
    "APIBadRequest",
    "APIConnectionError",
    "APIInactiveError",
    "APIForbidden",
    "APINotFound",
    "APIInvalidKey",
    "APIKeyError",
    "APIRateLimited",
    "APIUnavailable",
]


class APIError(Exception):
    # Whether the same request may succeed if tried again
    retryable = False

    def __init__(self, *args, retry_after=None):
        super().__init__(*args)
        # Seconds the API asked us to wait (Retry-After), if it said
        self.retry_after = retry_after


class APIBadRequest(APIError):
    pass


class APIConnectionError(APIError):
    """Server errors without a more specific meaning, timeouts and network errors."""

    retryable = True


class APIInactiveError(APIError):
    """The endpoint is disabled ("API not active"); retrying won't help."""


class APIForbidden(APIError):
    pass


class APINotFound(APIError):
    pass


class APIInvalidKey(APIError):
    pass


class APIKeyError(APIError):
    """The user has no key, or it lacks permissions. Raised by the bot, not the API."""


class APIRateLimited(APIError):
    retryable = True


class APIUnavailable(APIError):
    retryable = True
