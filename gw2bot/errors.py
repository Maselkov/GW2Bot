"""Messages shown to users for errors from the GW2 API layer."""
from .gw2api.errors import APIError, APIInactiveError, APIInvalidKey, APIKeyError
from .i18n import DEFAULT_LANGUAGE, Catalog, N_


def error_message(error, lang=DEFAULT_LANGUAGE, catalog=None):
    """The message for `error` in `lang`, or "" if it isn't an API layer
    error."""
    catalog = catalog or Catalog()
    if isinstance(error, APIKeyError):
        return catalog.t(lang, error.text, **error.fields)
    if isinstance(error, APIInactiveError):
        return catalog.t(lang, N_("The API is currently down. Try again later."))
    if isinstance(error, APIInvalidKey):
        return catalog.t(lang, N_("Your API key is invalid! Remove your key and add a new one"))
    if isinstance(error, APIError):
        return catalog.t(lang, N_("API has responded with the following error: `{error}`"), error=error)
    return ""
