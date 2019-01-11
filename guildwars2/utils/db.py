import re


def prepare_search(search):
    sanitized = re.escape(search)
    return re.compile(sanitized + ".*", re.IGNORECASE)
