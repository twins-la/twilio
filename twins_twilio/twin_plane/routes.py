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

import logging

from flask import Blueprint, g, jsonify, request

from twins_local.tenants import (
    OPERATOR_ADMIN_TENANT_ID,
    generate_tenant_id,
    generate_tenant_secret,
    hash_secret,
    reject_default_in_cloud,
)

from ..models import account_to_json, account_to_json_public, message_to_json, now_rfc2822
from ..email_models import email_to_json
from ..sids import generate_account_sid, generate_auth_token, generate_message_sid, generate_api_key, generate_feedback_id
from ..webhooks import build_webhook_params, deliver_webhook
from ..twiml import parse_message_response
from .auth import require_tenant, require_tenant_or_admin

logger = logging.getLogger(__name__)

twin_plane_bp = Blueprint("twin_plane", __name__, url_prefix="/_twin")


def _scope_tenant_id() -> str:
    """Tenant_id to stamp on log records for the current request."""
    return OPERATOR_ADMIN_TENANT_ID if g.get("is_admin") else g.tenant_id


# -- Unauth info endpoints --


@twin_plane_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "twin": "twilio", "version": "0.2.0"})


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
        "version": "0.2.0",
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

    g.storage.append_log({
        "tenant_id": tenant_id,
        "operation": "twin.tenant.create",
    })

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

    g.storage.append_log({
        "tenant_id": g.tenant_id,
        "operation": "twin.account.create",
        "account_sid": sid,
    })

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

    g.storage.append_log({
        "tenant_id": g.tenant_id,
        "operation": "twin.api_key.create",
        "account_sid": account_sid,
        "key_id": key_id,
    })

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

    g.storage.append_log({
        "tenant_id": g.tenant_id,
        "operation": "twin.verified_sender.create",
        "account_sid": account_sid,
        "email": email,
    })

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


# -- Simulate inbound SMS --


@twin_plane_bp.route("/simulate/inbound", methods=["POST"])
@require_tenant
def simulate_inbound_sms():
    """Simulate an inbound SMS for an account inside the tenant.

    Required JSON body:
        account_sid: The destination account on the tenant.
        from: sender phone number
        to: destination phone number (must be provisioned on the account)
        body: message text
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
    if not from_number or not to_number or not body:
        return jsonify({"error": "'from', 'to', and 'body' are required"}), 400

    account = g.storage.get_account(account_sid)
    if not account or account.get("tenant_id") != g.tenant_id:
        return jsonify({"error": "Account not found"}), 404

    phone_number_record = g.storage.get_phone_number_by_number(account_sid, to_number)
    if not phone_number_record:
        return jsonify({"error": f"No phone number '{to_number}' found on account"}), 404

    # Create the inbound message record
    message_sid = generate_message_sid()
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
        "num_segments": "1",
    }
    g.storage.create_message(msg_data)

    g.storage.append_log({
        "tenant_id": g.tenant_id,
        "operation": "twin.simulate.inbound",
        "account_sid": account["sid"],
        "message_sid": message_sid,
        "from": from_number,
        "to": to_number,
        "body": body,
    })

    sms_url = phone_number_record.get("sms_url", "")
    sms_method = phone_number_record.get("sms_method", "POST")
    webhook_delivered = False
    reply_messages = []

    if sms_url:
        webhook_params = build_webhook_params(
            message_sid=message_sid,
            account_sid=account["sid"],
            from_number=from_number,
            to_number=to_number,
            body=body,
        )

        from ..webhooks import compute_signature
        import requests as http_requests

        try:
            signature = compute_signature(account["auth_token"], sms_url, webhook_params)
            headers = {
                "X-Twilio-Signature": signature,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            if sms_method.upper() == "GET":
                resp = http_requests.get(
                    sms_url, params=webhook_params, headers=headers, timeout=15
                )
            else:
                resp = http_requests.post(
                    sms_url, data=webhook_params, headers=headers, timeout=15
                )

            webhook_delivered = True

            if resp.status_code == 200 and resp.text.strip():
                reply_bodies = parse_message_response(resp.text)
                for reply_body in reply_bodies:
                    reply_sid = generate_message_sid()
                    reply_data = {
                        "sid": reply_sid,
                        "tenant_id": g.tenant_id,
                        "account_sid": account["sid"],
                        "to": from_number,
                        "from_number": to_number,
                        "body": reply_body,
                        "status": "sent",
                        "direction": "outbound-reply",
                        "date_created": now_rfc2822(),
                        "date_updated": now_rfc2822(),
                        "date_sent": now_rfc2822(),
                        "num_segments": "1",
                    }
                    g.storage.create_message(reply_data)
                    reply_messages.append(reply_data)

                    g.storage.append_log({
                        "tenant_id": g.tenant_id,
                        "operation": "message.reply",
                        "account_sid": account["sid"],
                        "message_sid": reply_sid,
                        "in_reply_to": message_sid,
                        "body": reply_body,
                    })

        except Exception:
            logger.exception("Webhook delivery failed during inbound simulation")

    result = {
        "message": message_to_json(msg_data, g.base_url),
        "webhook_delivered": webhook_delivered,
        "webhook_url": sms_url,
        "replies": [message_to_json(r, g.base_url) for r in reply_messages],
    }

    return jsonify(result), 201


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

    g.storage.append_log({
        "tenant_id": g.tenant_id,
        "operation": "twin.feedback.submit",
        "feedback_id": feedback_id,
        "category": feedback_data["category"],
    })

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

    g.storage.append_log({
        "tenant_id": _scope_tenant_id(),
        "operation": "twin.feedback.update",
        "feedback_id": feedback_id,
        "status": updates.get("status", ""),
    })

    return jsonify(feedback)
