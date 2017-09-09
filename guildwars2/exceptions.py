class APIError(Exception):
    pass


class APIBadRequest(APIError):
    pass


class APIConnectionError(APIError):
    pass


class APIForbidden(APIError):
    pass


class APINotFound(APIError):
    pass


class APIKeyError(APIError):
    pass
