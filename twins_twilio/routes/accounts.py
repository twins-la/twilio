"""Twilio Account resource routes.

GET /2010-04-01/Accounts/{AccountSid}.json — Fetch account
"""

from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..errors import not_found
from ..models import account_to_json

accounts_bp = Blueprint("accounts", __name__)


@accounts_bp.route(
    "/2010-04-01/Accounts/<account_sid>.json",
    methods=["GET"],
)
@require_auth
def fetch_account(account_sid):
    """Fetch a single account by SID."""
    account = g.storage.get_account(account_sid)
    if not account:
        return not_found("Account")

    g.storage.append_log({
        "operation": "account.fetch",
        "account_sid": account_sid,
    })

    return jsonify(account_to_json(account, g.base_url))
