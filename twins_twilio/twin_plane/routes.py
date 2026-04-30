"""Twin Plane management API.

Served at /_twin/ — separate from the Twilio API surface.

Authentication:
  - POST /_twin/tenants (bootstrap — creates credentials) — unauthenticated.
  - GET  /_twin/health, /scenarios, /references, /settings — unauthenticated read-only.
  - All other endpoints require tenant auth (Basic tenant_id:tenant_secret)
    or operator-admin (Bearer or X-Twin-Admin-Token).

All authenticated endpoints are scoped to the caller's tenant.

Provides:
  - Tenant creation (Twin Plane — not Twilio API)
  - Scenario listing
  - Authoritative references
  - Operation logs (per-tenant)
  - Settings
  - Inbound SMS simulation (per-tenant; the caller's account within the tenant)
  - Account management (create Twilio-emulation accounts inside a tenant)
  - Health check
  - Feedback collection (per-tenant)
"""

from flask import Blueprint, g, jsonify, request

from twins_local.tenants import (
    OPERATOR_ADMIN_TENANT_ID,
    generate_tenant_id,
    generate_tenant_secret,
    hash_secret,
    reject_default_in_cloud,
)

from ..errors import not_found
from ..keywords import HELP_AUTO_REPLY, detect_keyword
from ..logs import emit
from ..models import account_to_json, account_to_json_public, message_to_json, now_rfc2822
from ..email_models import email_to_json
from ..sids import (
    generate_account_sid,
    generate_api_key,
    generate_auth_token,
    generate_feedback_id,
    generate_media_sid,
    generate_message_sid,
    generate_mms_sid,
)
from ..webhooks import (
    OP_INBOUND,
    OP_STATUS,
    WebhookEmitContext,
    build_inbound_webhook_params,
    build_status_callback_params,
    deliver_webhook_async,
    deliver_webhook_sync,
)
from ..twiml import parse_message_response
from .auth import require_tenant, require_tenant_or_admin

from flask import current_app
from twins_local.logs import current_correlation_id

VALID_STATUSES = frozenset({
    "queued", "sending", "sent", "delivered", "failed", "undelivered",
})

twin_plane_bp = Blueprint("twin_plane", __name__, url_prefix="/_twin")


def _scope_tenant_id() -> str:
    """Tenant_id to stamp on log records for the current request."""
    return OPERATOR_ADMIN_TENANT_ID if g.get("is_admin") else g.tenant_id


# -- Unauth info endpoints --


@twin_plane_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "twin": "twilio", "version": "0.3.0"})


@twin_plane_bp.route("/scenarios", methods=["GET"])
def scenarios():
    """List supported scenarios."""
    return jsonify({
        "scenarios": [
            {
                "name": "sms",
                "status": "supported",
                "description": "SMS send and receive via Twilio REST API",
                "capabilities": [
                    "outbound_sms",
                    "inbound_sms_webhook",
                    "webhook_signature_validation",
                    "message_status_progression",
                    "twiml_message_reply",
                    "mms_inbound",
                    "multi_segment_inbound",
                    "stop_start_help_keywords",
                    "operator_status_simulation",
                    "status_callback_lifecycle",
                ],
            },
            {
                "name": "email",
                "status": "supported",
                "description": "Email send via SendGrid v3 Mail Send API",
                "capabilities": [
                    "outbound_email",
                    "email_status_progression",
                    "sendgrid_api_key_auth",
                ],
            },
        ],
    })


@twin_plane_bp.route("/references", methods=["GET"])
def references():
    """Return the authoritative sources used to build this twin."""
    return jsonify({
        "references": [
            {
                "title": "Twilio Messages API",
                "url": "https://www.twilio.com/docs/messaging/api/message-resource",
                "retrieved": "2026-04-04",
            },
            {
                "title": "Twilio IncomingPhoneNumber API",
                "url": "https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource",
                "retrieved": "2026-04-04",
            },
            {
                "title": "Twilio Account API",
                "url": "https://www.twilio.com/docs/iam/api/account",
                "retrieved": "2026-04-04",
            },
            {
                "title": "Twilio Webhook Security",
                "url": "https://www.twilio.com/docs/usage/security",
                "retrieved": "2026-04-04",
            },
            {
                "title": "Twilio SMS Webhooks (TwiML)",
                "url": "https://www.twilio.com/docs/messaging/twiml",
                "retrieved": "2026-04-04",
            },
            {
                "title": "SendGrid Mail Send API",
                "url": "https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send",
                "retrieved": "2026-04-06",
            },
            {
                "title": "SendGrid Authentication",
                "url": "https://www.twilio.com/docs/sendgrid/for-developers/sending-email/authentication",
                "retrieved": "2026-04-06",
            },
            {
                "title": "SendGrid X-Message-Id",
                "url": "https://www.twilio.com/docs/sendgrid/glossary/x-message-id",
                "retrieved": "2026-04-06",
            },
            {
                "title": "SendGrid Error Format",
                "url": "https://www.twilio.com/docs/sendgrid/api-reference/how-to-use-the-sendgrid-v3-api/responses",
                "retrieved": "2026-04-06",
            },
        ],
    })


@twin_plane_bp.route("/settings", methods=["GET"])
def get_settings():
    """Get twin settings."""
    return jsonify({
        "twin": "twilio",
        "version": "0.3.0",
        "base_url": g.base_url,
    })


# -- Tenants (bootstrap) --


@twin_plane_bp.route("/tenants", methods=["POST"])
def create_tenant():
    """Create a new tenant.

    Unauthenticated bootstrap. Returns ``tenant_id`` and ``tenant_secret``
    exactly once; the secret is not stored in plaintext.
    """
    friendly_name = request.json.get("friendly_name", "") if request.is_json else ""

    if g.get("is_cloud"):
        tenant_id = generate_tenant_id()
        # UUIDs cannot collide with "default", but be defensive.
        reject_default_in_cloud(tenant_id)
    else:
        tenant_id = generate_tenant_id()

    tenant_secret = generate_tenant_secret()
    tenant = g.tenants.create_tenant(
        tenant_id=tenant_id,
        secret_hash=hash_secret(tenant_secret),
        friendly_name=friendly_name,
    )

    emit(
        g.storage,
        tenant_id=tenant_id,
        plane="twin",
        operation="twin.tenant.create",
        resource={"type": "tenant", "id": tenant_id},
    )

    resp = jsonify({
        "tenant_id": tenant_id,
        "tenant_secret": tenant_secret,
        "friendly_name": tenant["friendly_name"],
        "created_at": tenant["created_at"],
    })
    resp.status_code = 201
    return resp


# -- Logs (tenant-scoped) --


@twin_plane_bp.route("/logs", methods=["GET"])
@require_tenant_or_admin
def logs():
    """Retrieve operation logs. Admin: all logs. Tenant: own logs."""
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    tenant_id = None if g.is_admin else g.tenant_id
    entries = g.storage.list_logs(limit=limit, offset=offset, tenant_id=tenant_id)
    return jsonify({"logs": entries, "limit": limit, "offset": offset})


# -- Accounts (Twilio emulation resources, owned by the tenant) --


@twin_plane_bp.route("/accounts", methods=["POST"])
@require_tenant
def create_account():
    """Create a Twilio-emulation account inside the authenticated tenant.

    Real Twilio account creation requires their console; the twin makes
    it a simple API call, scoped to the calling tenant.
    """
    friendly_name = request.json.get("friendly_name", "") if request.is_json else ""

    sid = generate_account_sid()
    auth_token = generate_auth_token()
    now = now_rfc2822()

    account = g.storage.create_account(
        tenant_id=g.tenant_id,
        sid=sid,
        auth_token=auth_token,
        friendly_name=friendly_name or f"Twin Account {sid[-8:]}",
    )
    account.setdefault("date_created", now)
    account.setdefault("date_updated", now)
    account.setdefault("status", "active")

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.account.create",
        resource={"type": "account", "id": sid},
    )

    resp = jsonify(account_to_json(account, g.base_url))
    resp.status_code = 201
    return resp


@twin_plane_bp.route("/accounts", methods=["GET"])
@require_tenant_or_admin
def list_accounts():
    """List accounts. Admin: all accounts. Tenant: the tenant's accounts."""
    if g.is_admin:
        accounts = g.storage.list_accounts()
        items = [account_to_json_public(a, g.base_url) for a in accounts]
        return jsonify({"accounts": items})
    accounts = g.storage.list_accounts(tenant_id=g.tenant_id)
    items = [account_to_json(a, g.base_url) for a in accounts]
    return jsonify({"accounts": items})


# -- API Keys --


@twin_plane_bp.route("/api-keys", methods=["POST"])
@require_tenant
def create_api_key():
    """Create a SendGrid-style API key for an account within the tenant.

    Required JSON body:
        account_sid: The account that owns the key.

    Optional:
        name: A friendly name for the key.
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    account_sid = data.get("account_sid")
    if not account_sid:
        return jsonify({"error": "'account_sid' is required"}), 400

    account = g.storage.get_account(account_sid)
    if not account or account.get("tenant_id") != g.tenant_id:
        return jsonify({"error": "Account not found"}), 404

    name = data.get("name", "")

    key_id, key_secret, full_key = generate_api_key()

    g.storage.create_api_key(
        tenant_id=g.tenant_id,
        key_id=key_id,
        key_secret=key_secret,
        account_sid=account_sid,
        name=name or f"Twin API Key {key_id[:8]}",
    )

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.api_key.create",
        resource={"type": "api_key", "id": key_id},
        details={"account_sid": account_sid},
    )

    resp = jsonify({
        "api_key": full_key,
        "key_id": key_id,
        "account_sid": account_sid,
        "name": name or f"Twin API Key {key_id[:8]}",
    })
    resp.status_code = 201
    return resp


# -- Verified Senders --


@twin_plane_bp.route("/verified-senders", methods=["POST"])
@require_tenant
def create_verified_sender():
    """Register a verified sender identity for an account within the tenant.

    Required JSON body:
        account_sid: The account that owns the sender.
        email: The sender email address to verify.

    Optional:
        name: A display name for the sender.
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    account_sid = data.get("account_sid")
    email = data.get("email")
    if not account_sid:
        return jsonify({"error": "'account_sid' is required"}), 400
    if not email or not isinstance(email, str) or "@" not in email:
        return jsonify({"error": "'email' is required and must be a valid email address"}), 400

    account = g.storage.get_account(account_sid)
    if not account or account.get("tenant_id") != g.tenant_id:
        return jsonify({"error": "Account not found"}), 404

    name = data.get("name", "")

    sender = g.storage.create_verified_sender(
        tenant_id=g.tenant_id,
        account_sid=account_sid,
        email=email,
        name=name,
    )

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.verified_sender.create",
        resource={"type": "verified_sender", "id": email},
        details={"account_sid": account_sid},
    )

    resp = jsonify(sender)
    resp.status_code = 201
    return resp


@twin_plane_bp.route("/verified-senders", methods=["GET"])
@require_tenant_or_admin
def list_verified_senders():
    """List verified senders. Admin: all. Tenant: own tenant's."""
    if g.is_admin:
        accounts = g.storage.list_accounts()
    else:
        accounts = g.storage.list_accounts(tenant_id=g.tenant_id)
    senders = []
    for acct in accounts:
        senders.extend(g.storage.list_verified_senders(acct["sid"]))
    return jsonify({"verified_senders": senders})


# -- Emails --


@twin_plane_bp.route("/emails", methods=["GET"])
@require_tenant_or_admin
def list_emails():
    """List emails. Admin: all. Tenant: own tenant's."""
    if g.is_admin:
        accounts = g.storage.list_accounts()
    else:
        accounts = g.storage.list_accounts(tenant_id=g.tenant_id)
    emails = []
    for acct in accounts:
        emails.extend(g.storage.list_emails(acct["sid"]))
    items = [email_to_json(e) for e in emails]
    return jsonify({"emails": items})


@twin_plane_bp.route("/emails/<message_id>", methods=["GET"])
@require_tenant_or_admin
def fetch_email(message_id):
    """Fetch a single email. Admin: any. Tenant: own."""
    if g.is_admin:
        accounts = g.storage.list_accounts()
    else:
        accounts = g.storage.list_accounts(tenant_id=g.tenant_id)
    email = None
    for acct in accounts:
        email = g.storage.get_email(acct["sid"], message_id)
        if email:
            break
    if not email:
        return jsonify({"error": "Email not found"}), 404
    return jsonify(email_to_json(email))


# -- Simulate inbound SMS / status --


def _record_reply(account, message_sid, from_number, to_number, body, *, direction):
    """Insert an outbound-reply message record (TwiML reply or HELP auto-reply)."""
    reply_sid = generate_message_sid()
    now = now_rfc2822()
    reply_data = {
        "sid": reply_sid,
        "tenant_id": g.tenant_id,
        "account_sid": account["sid"],
        "to": from_number,
        "from_number": to_number,
        "body": body,
        "status": "sent",
        "direction": direction,
        "date_created": now,
        "date_updated": now,
        "date_sent": now,
        "num_segments": "1",
    }
    g.storage.create_message(reply_data)
    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="runtime",
        operation="message.reply",
        resource={"type": "message", "id": reply_sid},
        details={
            "account_sid": account["sid"],
            "in_reply_to": message_sid,
            "body": body,
            "direction": direction,
        },
    )
    return reply_data


def _resolve_media(num_media: int, supplied_urls, supplied_types):
    """Return (urls, types) of length ``num_media``, filling missing slots
    with twin-served placeholder PNG URLs.
    """
    urls = list(supplied_urls or [])
    types = list(supplied_types or [])
    while len(urls) < num_media:
        urls.append(f"{g.base_url}/_twin/media/{generate_media_sid()}")
    while len(types) < num_media:
        types.append("image/png")
    return urls[:num_media], types[:num_media]


@twin_plane_bp.route("/simulate/inbound", methods=["POST"])
@require_tenant
def simulate_inbound_sms():
    """Simulate an inbound SMS or MMS for an account inside the tenant.

    Required JSON body:
        account_sid: The destination account on the tenant.
        from: sender phone number
        to: destination phone number (must be provisioned on the account)
        body: message text

    Optional JSON body:
        num_segments: Carrier-reported segment count (default "1").
        num_media: Number of media items (>=0, default 0). When >0 the
            recorded message uses an MM-prefix SID and the webhook payload
            includes MediaUrl0/MediaContentType0/...
        media_urls: Operator-supplied media URLs. Slots not supplied are
            filled with twin-served placeholder URLs.
        media_content_types: MIME types aligned with media_urls.
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    account_sid = data.get("account_sid")
    from_number = data.get("from")
    to_number = data.get("to")
    body = data.get("body")

    if not account_sid:
        return jsonify({"error": "'account_sid' is required"}), 400
    if not from_number or not to_number or body is None:
        return jsonify({"error": "'from', 'to', and 'body' are required"}), 400

    try:
        num_segments = int(data.get("num_segments", 1))
        num_media = int(data.get("num_media", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "'num_segments' and 'num_media' must be integers"}), 400
    if num_segments < 1:
        return jsonify({"error": "'num_segments' must be >= 1"}), 400
    if num_media < 0:
        return jsonify({"error": "'num_media' must be >= 0"}), 400

    supplied_urls = data.get("media_urls") or []
    supplied_types = data.get("media_content_types") or []
    if not isinstance(supplied_urls, list) or not isinstance(supplied_types, list):
        return jsonify({"error": "'media_urls' and 'media_content_types' must be lists"}), 400
    if len(supplied_urls) > num_media:
        return jsonify({"error": "'media_urls' length exceeds 'num_media'"}), 400

    account = g.storage.get_account(account_sid)
    if not account or account.get("tenant_id") != g.tenant_id:
        return jsonify({"error": "Account not found"}), 404

    phone_number_record = g.storage.get_phone_number_by_number(account_sid, to_number)
    if not phone_number_record:
        return jsonify({"error": f"No phone number '{to_number}' found on account"}), 404

    media_urls, media_content_types = _resolve_media(num_media, supplied_urls, supplied_types)

    # Create the inbound message record. MMS uses MM-prefix SIDs.
    message_sid = generate_mms_sid() if num_media > 0 else generate_message_sid()
    now = now_rfc2822()
    msg_data = {
        "sid": message_sid,
        "tenant_id": g.tenant_id,
        "account_sid": account["sid"],
        "to": to_number,
        "from_number": from_number,
        "body": body,
        "status": "received",
        "direction": "inbound",
        "date_created": now,
        "date_updated": now,
        "date_sent": now,
        "num_segments": str(num_segments),
    }
    g.storage.create_message(msg_data)

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.simulate.inbound",
        resource={"type": "message", "id": message_sid},
        details={
            "account_sid": account["sid"],
            "from": from_number,
            "to": to_number,
            "body": body,
            "num_segments": num_segments,
            "num_media": num_media,
        },
    )

    # Apply carrier-keyword semantics. STOP/START update opt-out state;
    # the webhook still fires so the consumer sees the inbound. HELP
    # triggers an auto-reply after the webhook returns.
    keyword = detect_keyword(body)
    if keyword == "STOP":
        g.storage.set_opt_out(
            tenant_id=g.tenant_id,
            account_sid=account["sid"],
            twilio_number=to_number,
            recipient=from_number,
        )
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="runtime",
            operation="runtime.opt_out.set",
            resource={"type": "opt_out", "id": f"{account['sid']}:{to_number}:{from_number}"},
            details={"account_sid": account["sid"], "twilio_number": to_number, "recipient": from_number},
        )
    elif keyword == "START":
        g.storage.clear_opt_out(
            account_sid=account["sid"],
            twilio_number=to_number,
            recipient=from_number,
        )
        emit(
            g.storage,
            tenant_id=g.tenant_id,
            plane="runtime",
            operation="runtime.opt_out.clear",
            resource={"type": "opt_out", "id": f"{account['sid']}:{to_number}:{from_number}"},
            details={"account_sid": account["sid"], "twilio_number": to_number, "recipient": from_number},
        )

    sms_url = phone_number_record.get("sms_url", "")
    sms_method = phone_number_record.get("sms_method", "POST")
    reply_messages = []
    webhook_report = {
        "webhook_delivered": False,
        "webhook_url": sms_url,
        "reason": None,
        "status_code": None,
    }

    if sms_url:
        webhook_params = build_inbound_webhook_params(
            message_sid=message_sid,
            account_sid=account["sid"],
            from_number=from_number,
            to_number=to_number,
            body=body,
            num_segments=str(num_segments),
            num_media=str(num_media),
            media_urls=media_urls,
            media_content_types=media_content_types,
        )

        ok, reason, status_code, response_text = deliver_webhook_sync(
            url=sms_url,
            method=sms_method,
            params=webhook_params,
            auth_token=account["auth_token"],
            emit_ctx=WebhookEmitContext(
                app=current_app._get_current_object(),
                storage=g.storage,
                tenant_id=g.tenant_id,
                correlation_id=current_correlation_id(),
                operation=OP_INBOUND,
                message_sid=message_sid,
            ),
        )
        webhook_report = {
            "webhook_delivered": ok,
            "webhook_url": sms_url,
            "reason": reason,
            "status_code": status_code,
        }

        if ok and response_text and response_text.strip():
            reply_bodies = parse_message_response(response_text)
            for reply_body in reply_bodies:
                reply_messages.append(
                    _record_reply(
                        account, message_sid, from_number, to_number, reply_body,
                        direction="outbound-reply",
                    )
                )

    # HELP auto-reply runs after the webhook returns so the consumer's
    # webhook sees the HELP message before the auto-reply lands.
    if keyword == "HELP":
        reply_messages.append(
            _record_reply(
                account, message_sid, from_number, to_number, HELP_AUTO_REPLY,
                direction="outbound-auto",
            )
        )

    result = {
        "message": message_to_json(msg_data, g.base_url),
        "webhook": webhook_report,
        "replies": [message_to_json(r, g.base_url) for r in reply_messages],
    }
    if keyword:
        result["keyword"] = keyword
    if num_media > 0:
        result["media_urls"] = media_urls

    return jsonify(result), 201


@twin_plane_bp.route("/simulate/status", methods=["POST"])
@require_tenant
def simulate_status():
    """Force a status transition on a tenant-owned outbound message and
    fire the registered status callback.

    Required JSON body:
        message_sid: SID of the outbound message to update.
        status: One of queued | sending | sent | delivered | failed | undelivered.

    Required for failed/undelivered:
        error_code: Twilio error code (e.g., 30003, 30005).

    Optional:
        error_message: Operator-supplied detail string.
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    message_sid = data.get("message_sid")
    status = data.get("status")
    error_code = data.get("error_code")
    error_message = data.get("error_message")

    if not message_sid:
        return jsonify({"error": "'message_sid' is required"}), 400
    if status not in VALID_STATUSES:
        return jsonify({
            "error": f"'status' must be one of: {sorted(VALID_STATUSES)}"
        }), 400
    if status in {"failed", "undelivered"} and error_code in (None, ""):
        return jsonify({
            "error": "'error_code' is required for status 'failed' or 'undelivered'"
        }), 400

    accounts = g.storage.list_accounts(tenant_id=g.tenant_id)
    msg = None
    for acct in accounts:
        msg = g.storage.get_message(acct["sid"], message_sid)
        if msg:
            break
    if not msg:
        return not_found("Message")

    if msg.get("direction") not in ("outbound-api", "outbound-reply", "outbound-auto", "outbound-call"):
        return jsonify({"error": "simulate/status only applies to outbound messages"}), 400

    updates = {"status": status, "date_updated": now_rfc2822()}
    if error_code is not None:
        updates["error_code"] = str(error_code)
        updates["error_message"] = error_message or ""
    g.storage.update_message(msg["account_sid"], message_sid, updates)

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.simulate.status",
        resource={"type": "message", "id": message_sid},
        details={
            "status": status,
            "error_code": str(error_code) if error_code is not None else None,
        },
    )

    status_callback = msg.get("status_callback", "")
    if status_callback:
        params = build_status_callback_params(
            message_sid=message_sid,
            account_sid=msg["account_sid"],
            from_number=msg.get("from_number", ""),
            to_number=msg.get("to", ""),
            status=status,
            error_code=str(error_code) if error_code is not None else None,
            error_message=error_message,
        )
        account = g.storage.get_account(msg["account_sid"])
        deliver_webhook_async(
            url=status_callback,
            method=msg.get("status_callback_method", "POST"),
            params=params,
            auth_token=account["auth_token"],
            emit_ctx=WebhookEmitContext(
                app=current_app._get_current_object(),
                storage=g.storage,
                tenant_id=g.tenant_id,
                correlation_id=current_correlation_id(),
                operation=OP_STATUS,
                message_sid=message_sid,
            ),
        )

    refreshed = g.storage.get_message(msg["account_sid"], message_sid)
    return jsonify({
        "message": message_to_json(refreshed, g.base_url),
        "status_callback": {
            "fired": bool(status_callback),
            "url": status_callback,
        },
    }), 200


# -- Feedback --


@twin_plane_bp.route("/feedback", methods=["POST"])
@require_tenant
def submit_feedback():
    """Submit feedback about the twin.

    Requires tenant auth. The tenant_id is set automatically.

    Required JSON body:
        body: Freeform feedback text.

    Optional:
        category: One of "bug", "missing-scenario", "feature-request", "general".
        context: Dict of structured data.
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    body = data.get("body")

    if not body or not body.strip():
        return jsonify({"error": "'body' is required"}), 400

    feedback_id = generate_feedback_id()
    now = now_rfc2822()

    feedback_data = {
        "id": feedback_id,
        "tenant_id": g.tenant_id,
        "body": body.strip(),
        "category": data.get("category", ""),
        "context": data.get("context", {}),
        "status": "pending",
        "date_created": now,
        "date_updated": now,
    }
    feedback = g.storage.create_feedback(feedback_data)

    emit(
        g.storage,
        tenant_id=g.tenant_id,
        plane="twin",
        operation="twin.feedback.submit",
        resource={"type": "feedback", "id": feedback_id},
        details={"category": feedback_data["category"]},
    )

    return jsonify(feedback), 201


@twin_plane_bp.route("/feedback", methods=["GET"])
@require_tenant_or_admin
def list_feedback():
    """List feedback. Admin: all feedback. Tenant: own feedback.

    Optional query params:
        status: Filter by status (pending, reviewed, published).
    """
    status = request.args.get("status")
    tenant_id = None if g.is_admin else g.tenant_id
    items = g.storage.list_feedback(status=status, tenant_id=tenant_id)
    return jsonify({"feedback": items})


@twin_plane_bp.route("/feedback/<feedback_id>", methods=["GET"])
@require_tenant_or_admin
def get_feedback(feedback_id):
    """Fetch a single feedback item. Admin: any. Tenant: own."""
    feedback = g.storage.get_feedback(feedback_id)
    if not feedback:
        return jsonify({"error": "Feedback not found"}), 404
    if not g.is_admin and feedback.get("tenant_id") != g.tenant_id:
        return jsonify({"error": "Feedback not found"}), 404
    return jsonify(feedback)


@twin_plane_bp.route("/feedback/<feedback_id>", methods=["POST"])
@require_tenant_or_admin
def update_feedback(feedback_id):
    """Update a feedback record. Admin: any. Tenant: own.

    Accepts JSON body with:
        status: New status (e.g., "reviewed", "published").
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    existing = g.storage.get_feedback(feedback_id)
    if not existing:
        return jsonify({"error": "Feedback not found"}), 404
    if not g.is_admin and existing.get("tenant_id") != g.tenant_id:
        return jsonify({"error": "Feedback not found"}), 404

    data = request.json
    updates = {}
    if "status" in data:
        updates["status"] = data["status"]
    updates["date_updated"] = now_rfc2822()

    feedback = g.storage.update_feedback(feedback_id, updates)

    emit(
        g.storage,
        tenant_id=_scope_tenant_id(),
        plane="twin",
        operation="twin.feedback.update",
        resource={"type": "feedback", "id": feedback_id},
        details={"status": updates.get("status", "")},
    )

    return jsonify(feedback)
