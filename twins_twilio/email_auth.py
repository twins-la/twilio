"""SendGrid-style API key authentication.

SendGrid uses Bearer token auth where the token is an API key
in the format: SG.{key_id}.{key_secret}
"""

import functools
import hmac

from flask import request, g

from .email_errors import email_authentication_error


def require_api_key(f):
    """Decorator that enforces SendGrid-style API key auth.

    Parses Authorization: Bearer SG.{key_id}.{key_secret}
    Sets g.account_sid and g.api_key on success.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return email_authentication_error()

        token = auth_header[7:]  # Strip "Bearer "
        if not token.startswith("SG."):
            return email_authentication_error()

        parts = token[3:].split(".", 1)  # Strip "SG." and split
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return email_authentication_error()

        key_id, key_secret = parts

        api_key = g.storage.get_api_key_by_id(key_id)
        if not api_key or not hmac.compare_digest(api_key["key_secret"], key_secret):
            return email_authentication_error()

        g.account_sid = api_key["account_sid"]
        g.api_key = api_key
        return f(*args, **kwargs)

    return wrapper
