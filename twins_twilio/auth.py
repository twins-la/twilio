"""HTTP Basic Auth matching Twilio's authentication style.

Twilio uses HTTP Basic Auth where:
  - username = AccountSid
  - password = AuthToken
"""

import functools
import hmac

from flask import request, g

from .errors import authentication_error


def require_auth(f):
    """Decorator that enforces Twilio-style HTTP Basic Auth.

    Sets g.account_sid and g.account on success.
    The storage backend must be available at g.storage.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return authentication_error()

        account_sid = auth.username
        auth_token = auth.password

        # The account_sid in the URL must match the auth credentials
        url_account_sid = kwargs.get("account_sid")
        if url_account_sid and url_account_sid != account_sid:
            return authentication_error()

        account = g.storage.get_account(account_sid)
        if not account or not hmac.compare_digest(account["auth_token"], auth_token):
            return authentication_error()

        g.account_sid = account_sid
        g.account = account
        return f(*args, **kwargs)

    return wrapper
