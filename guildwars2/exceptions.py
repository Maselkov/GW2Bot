class APIError(Exception):
    pass


class APIBadRequest(APIError):
    pass


class APIConnectionError(APIError):
    pass


class APIInactiveError(APIError):
    pass


class APIForbidden(APIError):
    pass


class APINotFound(APIError):
    pass


class APIInvalidKey(APIError):
    pass


class APIKeyError(APIError):
    pass
