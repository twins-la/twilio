"""Twin Plane management API.

Served at /_twin/ — separate from the Twilio API surface.
Not authenticated with Twilio credentials. For 0.1.0, unauthenticated.

Provides:
  - Scenario listing
  - Operation logs
  - Settings
  - Inbound SMS simulation
  - Account management (create accounts — not part of the Twilio emulation surface)
  - Health check
"""

import logging

from flask import Blueprint, g, jsonify, request

from ..models import account_to_json, message_to_json, now_rfc2822
from ..email_models import email_to_json
from ..sids import generate_account_sid, generate_auth_token, generate_message_sid, generate_api_key, generate_feedback_id
from ..webhooks import build_webhook_params, deliver_webhook
from ..twiml import parse_message_response

logger = logging.getLogger(__name__)

twin_plane_bp = Blueprint("twin_plane", __name__, url_prefix="/_twin")


@twin_plane_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "twin": "twilio", "version": "0.1.0"})


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


@twin_plane_bp.route("/logs", methods=["GET"])
def logs():
    """Retrieve operation logs."""
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    entries = g.storage.list_logs(limit=limit, offset=offset)
    return jsonify({"logs": entries, "limit": limit, "offset": offset})


@twin_plane_bp.route("/settings", methods=["GET"])
def get_settings():
    """Get twin settings."""
    return jsonify({
        "twin": "twilio",
        "version": "0.1.0",
        "base_url": g.base_url,
    })


@twin_plane_bp.route("/accounts", methods=["POST"])
def create_account():
    """Create a new account (Twin Plane operation, not Twilio API).

    This is how users create accounts on the twin. Real Twilio account
    creation requires their console; the twin makes it a simple API call.
    """
    friendly_name = request.json.get("friendly_name", "") if request.is_json else ""

    sid = generate_account_sid()
    auth_token = generate_auth_token()
    now = now_rfc2822()

    account = g.storage.create_account(
        sid=sid,
        auth_token=auth_token,
        friendly_name=friendly_name or f"Twin Account {sid[-8:]}",
    )
    account.setdefault("date_created", now)
    account.setdefault("date_updated", now)
    account.setdefault("status", "active")

    g.storage.append_log({
        "operation": "twin.account.create",
        "account_sid": sid,
    })

    resp = jsonify(account_to_json(account, g.base_url))
    resp.status_code = 201
    return resp


@twin_plane_bp.route("/accounts", methods=["GET"])
def list_accounts():
    """List all accounts."""
    accounts = g.storage.list_accounts()
    items = [account_to_json(a, g.base_url) for a in accounts]
    return jsonify({"accounts": items})


@twin_plane_bp.route("/api-keys", methods=["POST"])
def create_api_key():
    """Create a SendGrid-style API key for an account.

    This is how users create API keys on the twin. Real SendGrid key
    creation happens in the console; the twin makes it a simple API call.

    Required JSON body:
        account_sid: The account to associate the key with.

    Optional:
        name: A friendly name for the key.
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    account_sid = data.get("account_sid")
    name = data.get("name", "")

    if not account_sid:
        return jsonify({"error": "'account_sid' is required"}), 400

    account = g.storage.get_account(account_sid)
    if not account:
        return jsonify({"error": f"Account '{account_sid}' not found"}), 404

    key_id, key_secret, full_key = generate_api_key()

    g.storage.create_api_key(
        key_id=key_id,
        key_secret=key_secret,
        account_sid=account_sid,
        name=name or f"Twin API Key {key_id[:8]}",
    )

    g.storage.append_log({
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


@twin_plane_bp.route("/emails", methods=["GET"])
def list_emails():
    """List sent emails for inspection.

    Optional query params:
        account_sid: Filter by account.
    """
    account_sid = request.args.get("account_sid")

    if account_sid:
        emails = g.storage.list_emails(account_sid)
    else:
        # List across all accounts
        accounts = g.storage.list_accounts()
        emails = []
        for acct in accounts:
            emails.extend(g.storage.list_emails(acct["sid"]))

    items = [email_to_json(e) for e in emails]
    return jsonify({"emails": items})


@twin_plane_bp.route("/emails/<message_id>", methods=["GET"])
def fetch_email(message_id):
    """Fetch a single email by message_id."""
    account_sid = request.args.get("account_sid")

    if account_sid:
        email = g.storage.get_email(account_sid, message_id)
    else:
        accounts = g.storage.list_accounts()
        email = None
        for acct in accounts:
            email = g.storage.get_email(acct["sid"], message_id)
            if email:
                break

    if not email:
        return jsonify({"error": "Email not found"}), 404

    return jsonify(email_to_json(email))


@twin_plane_bp.route("/simulate/inbound", methods=["POST"])
def simulate_inbound_sms():
    """Simulate an inbound SMS message.

    This triggers the full inbound flow:
    1. Creates an inbound message record
    2. Looks up the destination number's webhook configuration
    3. Delivers the webhook with proper Twilio parameters and signature
    4. Parses TwiML response for auto-reply messages

    Required JSON body:
        from: sender phone number
        to: destination phone number (must be provisioned on the twin)
        body: message text

    Optional:
        account_sid: target account (required if multiple accounts exist)
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    data = request.json
    from_number = data.get("from")
    to_number = data.get("to")
    body = data.get("body")
    target_account_sid = data.get("account_sid")

    if not from_number or not to_number or not body:
        return jsonify({"error": "'from', 'to', and 'body' are required"}), 400

    # Find the phone number resource for the destination
    accounts = g.storage.list_accounts()
    phone_number_record = None
    account = None

    for acct in accounts:
        if target_account_sid and acct["sid"] != target_account_sid:
            continue
        pn = g.storage.get_phone_number_by_number(acct["sid"], to_number)
        if pn:
            phone_number_record = pn
            account = acct
            break

    if not phone_number_record:
        return jsonify({"error": f"No phone number '{to_number}' found on any account"}), 404

    if not account:
        return jsonify({"error": "Account not found"}), 404

    # Create the inbound message record
    message_sid = generate_message_sid()
    now = now_rfc2822()
    msg_data = {
        "sid": message_sid,
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
        "operation": "twin.simulate.inbound",
        "account_sid": account["sid"],
        "message_sid": message_sid,
        "from": from_number,
        "to": to_number,
        "body": body,
    })

    # Deliver webhook if configured
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

        # For simulation, deliver synchronously so we can return the result
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

            # Parse TwiML response for auto-reply
            if resp.status_code == 200 and resp.text.strip():
                reply_bodies = parse_message_response(resp.text)
                for reply_body in reply_bodies:
                    reply_sid = generate_message_sid()
                    reply_data = {
                        "sid": reply_sid,
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
def submit_feedback():
    """Submit feedback about the twin.

    Accepts freeform feedback from agents. No authentication required.

    Required JSON body:
        body: Freeform feedback text.

    Optional:
        category: One of "bug", "missing-scenario", "feature-request", "general".
        context: Dict of structured data (error codes, message SIDs, scenario names, etc.).
        account_sid: The account SID of the agent submitting feedback.
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
        "body": body.strip(),
        "category": data.get("category", ""),
        "context": data.get("context", {}),
        "account_sid": data.get("account_sid", ""),
        "status": "pending",
        "date_created": now,
        "date_updated": now,
    }
    feedback = g.storage.create_feedback(feedback_data)

    g.storage.append_log({
        "operation": "twin.feedback.submit",
        "feedback_id": feedback_id,
        "category": feedback_data["category"],
    })

    return jsonify(feedback), 201


@twin_plane_bp.route("/feedback", methods=["GET"])
def list_feedback():
    """List submitted feedback.

    Optional query params:
        status: Filter by status (pending, reviewed, published).
    """
    status = request.args.get("status")
    items = g.storage.list_feedback(status=status)
    return jsonify({"feedback": items})


@twin_plane_bp.route("/feedback/<feedback_id>", methods=["GET"])
def get_feedback(feedback_id):
    """Fetch a single feedback item."""
    feedback = g.storage.get_feedback(feedback_id)
    if not feedback:
        return jsonify({"error": "Feedback not found"}), 404
    return jsonify(feedback)


@twin_plane_bp.route("/feedback/<feedback_id>", methods=["POST"])
def update_feedback(feedback_id):
    """Update a feedback record (e.g., change status).

    Used by the review pipeline to mark feedback as reviewed or published.

    Accepts JSON body with:
        status: New status (e.g., "reviewed", "published").
    """
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400

    existing = g.storage.get_feedback(feedback_id)
    if not existing:
        return jsonify({"error": "Feedback not found"}), 404

    data = request.json
    updates = {}
    if "status" in data:
        updates["status"] = data["status"]
    updates["date_updated"] = now_rfc2822()

    feedback = g.storage.update_feedback(feedback_id, updates)

    g.storage.append_log({
        "operation": "twin.feedback.update",
        "feedback_id": feedback_id,
        "status": updates.get("status", ""),
    })

    return jsonify(feedback)
