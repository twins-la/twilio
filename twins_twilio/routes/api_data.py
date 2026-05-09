"""Catch-all for unknown ``/<api_version>/Accounts/<sid>/<rest>`` paths.

Closes twins-la/twins-la#2 (twilio half): without this catch-all, Flask
returns its default HTML 404 on any unimplemented endpoint, which breaks
Twilio SDK consumers that decode `Content-Type: application/json`. The
canonical Twilio error envelope is
``{code, message, more_info, status}``.

Path pattern matches the Twilio REST API surface: ``/2010-04-01/Accounts/AC.../...``
plus future api versions. The blueprint is registered LAST so specific
routes (Messages, IncomingPhoneNumbers, etc.) take precedence.
"""

from flask import Blueprint

from ..errors import not_found

api_data_bp = Blueprint("api_data", __name__)


@api_data_bp.route(
    "/<api_version>/Accounts/<sid>/<path:rest>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def unknown_account_path(api_version: str, sid: str, rest: str):
    return not_found()


@api_data_bp.route(
    "/<api_version>/Accounts/<path:rest>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def unknown_account_root_path(api_version: str, rest: str):
    return not_found()
