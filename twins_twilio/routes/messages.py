"""Twilio Message resource routes.

POST /2010-04-01/Accounts/{AccountSid}/Messages.json — Send (create)
GET  /2010-04-01/Accounts/{AccountSid}/Messages.json — List
GET  /2010-04-01/Accounts/{AccountSid}/Messages/{Sid}.json — Fetch
"""

import logging
import re
import threading
import time

from flask import Blueprint, current_app, g, jsonify, request

from twins_local.logs import current_correlation_id

from ..auth import require_auth
from ..errors import (
    invalid_to_number,
    missing_body,
    missing_from,
    missing_to,
    not_found,
    opted_out_recipient,
)
from ..logs import emit
from ..models import message_to_json, now_rfc2822
from ..sids import generate_message_sid
from ..webhooks import (
    OP_STATUS,
    WebhookEmitContext,
    build_status_callback_params,
    deliver_webhook_async,
)

# E.164 phone number format
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

logger = logging.getLogger(__name__)

messages_bp = Blueprint("messages", __name__)

PREFIX = "/2010-04-01/Accounts/<account_sid>/Messages"


def _simulate_delivery(
    app, storage, msg_data: dict, auth_token: str, tenant_id: str, correlation_id: str
):
    """Simulate message delivery in a background thread.

    Progresses: queued → sending → sent → delivered with small delays
    to mimic real Twilio behavior. Each transition fires a status callback
    if one is registered on the message.
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

    emit_ctx = WebhookEmitContext(
        app=app,
        storage=storage,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        operation=OP_STATUS,
        message_sid=sid,
    )
    with app.app_context():
        g.storage = storage
        g.correlation_id = correlation_id
        try:
            for status, delay in transitions:
                time.sleep(delay)
                now = now_rfc2822()
                updates = {"status": status, "date_updated": now}
                if status == "sent":
                    updates["date_sent"] = now
                storage.update_message(account_sid, sid, updates)

                if status_callback:
                    params = build_status_callback_params(
                        message_sid=sid,
                        account_sid=account_sid,
                        from_number=msg_data.get("from_number", ""),
                        to_number=msg_data.get("to", ""),
                        status=status,
                    )
                    deliver_webhook_async(
                        url=status_callback,
                        method=status_callback_method,
                        params=params,
                        auth_token=auth_token,
                        emit_ctx=emit_ctx,
                    )
        except Exception as exc:
            # Crashing here would silently halt the auto-progression.
            # Emit a normative failure record so the operator can see why.
            emit(
                storage,
                tenant_id=tenant_id,
                plane="runtime",
                operation="runtime.message.progression",
                resource={"type": "message", "id": sid},
                outcome="failure",
                reason=f"progression worker raised: {exc.__class__.__name__}: {exc}",
                details={"account_sid": account_sid},
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
        return missing_to()
    if not from_number:
        return missing_from()
    if not body:
        return missing_body()

    if not _E164_PATTERN.match(to):
        return invalid_to_number(to)

    # Real Twilio rejects messages to recipients who have opted out via STOP.
    # The twin enforces the same so consumer code that ignores opt-outs is
    # caught in CI rather than in production carrier complaints.
    if g.storage.is_opted_out(
        account_sid=account_sid, twilio_number=from_number, recipient=to
    ):
        return opted_out_recipient(to)

    sid = generate_message_sid()
    now = now_rfc2822()

    tenant_id = g.account.get("tenant_id", "")

    msg_data = {
        "sid": sid,
        "tenant_id": tenant_id,
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

    emit(
        g.storage,
        tenant_id=tenant_id,
        plane="data",
        operation="message.create",
        resource={"type": "message", "id": sid},
        details={
            "account_sid": account_sid,
            "to": to,
            "from": from_number,
            "body": body,
            "direction": "outbound-api",
        },
    )

    app = current_app._get_current_object()
    storage = g.storage
    auth_token = g.account["auth_token"]
    correlation_id = current_correlation_id()
    thread = threading.Thread(
        target=_simulate_delivery,
        args=(app, storage, msg_data, auth_token, tenant_id, correlation_id),
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

    emit(
        g.storage,
        tenant_id=g.account["tenant_id"],
        plane="data",
        operation="message.list",
        details={"account_sid": account_sid, "filters": filters or {}},
    )

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

    emit(
        g.storage,
        tenant_id=g.account["tenant_id"],
        plane="data",
        operation="message.fetch",
        resource={"type": "message", "id": sid},
        details={"account_sid": account_sid},
    )

    return jsonify(message_to_json(msg, g.base_url))
