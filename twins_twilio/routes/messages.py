"""Twilio Message resource routes.

POST /2010-04-01/Accounts/{AccountSid}/Messages.json — Send (create)
GET  /2010-04-01/Accounts/{AccountSid}/Messages.json — List
GET  /2010-04-01/Accounts/{AccountSid}/Messages/{Sid}.json — Fetch
"""

import logging
import threading
import time

from flask import Blueprint, g, jsonify, request, current_app

from ..auth import require_auth
from ..errors import bad_request, not_found
from ..models import message_to_json, now_rfc2822
from ..sids import generate_message_sid
from ..webhooks import deliver_status_callback

logger = logging.getLogger(__name__)

messages_bp = Blueprint("messages", __name__)

PREFIX = "/2010-04-01/Accounts/<account_sid>/Messages"


def _simulate_delivery(app, storage, msg_data: dict, auth_token: str):
    """Simulate message delivery in a background thread.

    Progresses: queued → sending → sent → delivered
    with small delays to mimic real Twilio behavior.
    """
    sid = msg_data["sid"]
    account_sid = msg_data["account_sid"]
    status_callback = msg_data.get("status_callback", "")
    status_callback_method = msg_data.get("status_callback_method", "POST")

    transitions = [
        ("sending", 0.1),
        ("sent", 0.2),
        ("delivered", 0.3),
    ]

    with app.app_context():
        g.storage = storage
        for status, delay in transitions:
            time.sleep(delay)
            now = now_rfc2822()
            updates = {"status": status, "date_updated": now}
            if status == "sent":
                updates["date_sent"] = now
            storage.update_message(account_sid, sid, updates)

            if status_callback:
                deliver_status_callback(
                    url=status_callback,
                    method=status_callback_method,
                    message_sid=sid,
                    account_sid=account_sid,
                    from_number=msg_data.get("from_number", ""),
                    to_number=msg_data.get("to", ""),
                    status=status,
                    auth_token=auth_token,
                )


@messages_bp.route(f"{PREFIX}.json", methods=["POST"])
@require_auth
def create_message(account_sid):
    """Send (create) an outbound SMS message."""
    to = request.form.get("To")
    from_number = request.form.get("From")
    body = request.form.get("Body")
    status_callback = request.form.get("StatusCallback", "")
    status_callback_method = request.form.get("StatusCallbackMethod", "POST")

    if not to:
        return bad_request("'To' is required")
    if not from_number:
        return bad_request("'From' is required")
    if not body:
        return bad_request("'Body' is required when not sending media")

    sid = generate_message_sid()
    now = now_rfc2822()

    msg_data = {
        "sid": sid,
        "account_sid": account_sid,
        "to": to,
        "from_number": from_number,
        "body": body,
        "status": "queued",
        "direction": "outbound-api",
        "date_created": now,
        "date_updated": now,
        "date_sent": "",
        "num_segments": "1",
        "price": None,
        "error_code": None,
        "error_message": None,
        "status_callback": status_callback,
        "status_callback_method": status_callback_method,
    }

    result = g.storage.create_message(msg_data)

    g.storage.append_log({
        "operation": "message.create",
        "account_sid": account_sid,
        "message_sid": sid,
        "to": to,
        "from": from_number,
        "body": body,
        "direction": "outbound-api",
    })

    # Simulate delivery in background
    app = current_app._get_current_object()
    storage = g.storage
    auth_token = g.account["auth_token"]
    thread = threading.Thread(
        target=_simulate_delivery,
        args=(app, storage, msg_data, auth_token),
        daemon=True,
    )
    thread.start()

    resp = jsonify(message_to_json(result, g.base_url))
    resp.status_code = 201
    return resp


@messages_bp.route(f"{PREFIX}.json", methods=["GET"])
@require_auth
def list_messages(account_sid):
    """List messages for an account."""
    filters = {}
    for param in ("To", "From", "DateSent"):
        val = request.args.get(param)
        if val:
            filters[param] = val

    messages = g.storage.list_messages(account_sid, filters if filters else None)

    g.storage.append_log({
        "operation": "message.list",
        "account_sid": account_sid,
    })

    items = [message_to_json(m, g.base_url) for m in messages]
    return jsonify({
        "messages": items,
        "uri": f"/2010-04-01/Accounts/{account_sid}/Messages.json",
        "page": 0,
        "page_size": 50,
        "first_page_uri": f"/2010-04-01/Accounts/{account_sid}/Messages.json?Page=0&PageSize=50",
        "next_page_uri": "",
        "previous_page_uri": "",
    })


@messages_bp.route(f"{PREFIX}/<sid>.json", methods=["GET"])
@require_auth
def fetch_message(account_sid, sid):
    """Fetch a single message by SID."""
    msg = g.storage.get_message(account_sid, sid)
    if not msg:
        return not_found("Message")

    g.storage.append_log({
        "operation": "message.fetch",
        "account_sid": account_sid,
        "message_sid": sid,
    })

    return jsonify(message_to_json(msg, g.base_url))
