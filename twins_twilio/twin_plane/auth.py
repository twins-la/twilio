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


def require_twin_or_admin_auth(f):
    """Decorator that accepts either admin Bearer token or tenant Basic Auth.

    Checks for admin auth first (Bearer token matching g.admin_token).
    If no admin token is configured, any Bearer token is accepted (local dev).
    Falls back to tenant Basic Auth if no Bearer token is present.

    Sets g.is_admin (bool), and for tenant auth also sets g.account_sid and g.account.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        # Check for admin Bearer token
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            admin_token = g.admin_token

            # If no admin token configured, accept any Bearer token (local dev)
            if not admin_token or hmac.compare_digest(admin_token, token):
                g.is_admin = True
                g.account_sid = None
                g.account = None
                return f(*args, **kwargs)
            else:
                return _auth_error()

        # Fall through to tenant Basic Auth
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return _auth_error()

        account_sid = auth.username
        auth_token = auth.password

        account = g.storage.get_account(account_sid)
        if not account or not hmac.compare_digest(account["auth_token"], auth_token):
            return _auth_error()

        g.is_admin = False
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
