"""Messages shown to users for errors from the GW2 API layer."""
from .gw2api.errors import APIError, APIInactiveError, APIInvalidKey, APIKeyError


def error_message(error):
    """The message for `error`, or "" if it isn't an API layer error."""
    if isinstance(error, APIKeyError):
        return str(error)
    if isinstance(error, APIInactiveError):
        return "The API is currently down. Try again later."
    if isinstance(error, APIInvalidKey):
        return "Your API key is invalid! Remove your key and add a new one"
    if isinstance(error, APIError):
        return f"API has responded with the following error: `{error}`"
    return ""
