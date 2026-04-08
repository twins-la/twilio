"""HTTP Basic Auth for Twin Plane endpoints.

Reuses the same AccountSid:AuthToken credentials as the Twilio API,
but does not enforce URL path account_sid matching (Twin Plane routes
don't embed account_sid in URLs).
"""

import functools
import hmac

from flask import request, g, jsonify


def require_twin_auth(f):
    """Decorator that enforces Basic Auth on Twin Plane endpoints.

    Sets g.account_sid and g.account on success.
    Returns 401 with WWW-Authenticate header on failure.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return _auth_error()

        account_sid = auth.username
        auth_token = auth.password

        account = g.storage.get_account(account_sid)
        if not account or not hmac.compare_digest(account["auth_token"], auth_token):
            return _auth_error()

        g.account_sid = account_sid
        g.account = account
        return f(*args, **kwargs)

    return wrapper


def _auth_error():
    """Return 401 with Twin Plane realm."""
    resp = jsonify({"error": "Authentication required"})
    resp.status_code = 401
    resp.headers["WWW-Authenticate"] = 'Basic realm="Twin Plane"'
    return resp
