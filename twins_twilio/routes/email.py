"""SendGrid v3 Mail Send route.

POST /v3/mail/send — Send an email
"""

import logging
import threading
import time

from flask import Blueprint, g, request, current_app

from ..email_auth import require_api_key
from ..email_errors import email_bad_request
from ..models import now_rfc2822
from ..sids import generate_email_id

logger = logging.getLogger(__name__)

email_bp = Blueprint("email", __name__)


def _simulate_delivery(app, storage, email_data: dict):
    """Simulate email delivery in a background thread.

    Progresses: processed → delivered
    with small delays to mimic real SendGrid behavior.
    """
    message_id = email_data["message_id"]
    account_sid = email_data["account_sid"]

    transitions = [
        ("delivered", 0.3),
    ]

    with app.app_context():
        g.storage = storage
        for status, delay in transitions:
            time.sleep(delay)
            now = now_rfc2822()
            storage.update_email(account_sid, message_id, {
                "status": status,
                "date_updated": now,
            })


def _is_valid_email(email: str) -> bool:
    """Basic email format validation (must contain @ with local and domain parts)."""
    if not email or not isinstance(email, str):
        return False
    parts = email.split("@")
    return len(parts) == 2 and len(parts[0]) > 0 and "." in parts[1]


def _validate_mail_send(data: dict):
    """Validate the SendGrid v3 mail/send request body.

    Returns (None, None) if valid, or (message, field) if invalid.
    """
    if not isinstance(data, dict):
        return "request body must be a JSON object", None

    # personalizations is required
    personalizations = data.get("personalizations")
    if not personalizations or not isinstance(personalizations, list):
        return "The personalizations field is required and must be an array.", "personalizations"

    # from is required
    from_obj = data.get("from")
    if not from_obj or not isinstance(from_obj, dict) or not from_obj.get("email"):
        return "The from object must be provided for every email send.", "from"

    # Validate from email format
    if not _is_valid_email(from_obj["email"]):
        return f"The from email address is not valid. Got: {from_obj['email']}", "from.email"

    # subject: required at top level or in every personalization
    top_subject = data.get("subject")
    if not top_subject:
        for i, p in enumerate(personalizations):
            if not p.get("subject"):
                return (
                    f"The subject is required. You can get around this requirement "
                    f"if you use a template with a subject defined or if every "
                    f"personalization has a subject defined.",
                    "subject",
                )

    # content is required (unless template_id, which we store but don't render)
    content = data.get("content")
    template_id = data.get("template_id")
    if not content and not template_id:
        return "Unless a valid template_id is provided, the content parameter is required.", "content"

    if content:
        if not isinstance(content, list):
            return "The content must be an array.", "content"
        for item in content:
            if not isinstance(item, dict) or not item.get("type") or not item.get("value"):
                return "Each content item must have 'type' and 'value' fields.", "content"

    # Validate each personalization has 'to'
    for i, p in enumerate(personalizations):
        if not isinstance(p, dict):
            return f"Each personalization must be an object.", f"personalizations[{i}]"
        to = p.get("to")
        if not to or not isinstance(to, list) or len(to) == 0:
            return (
                f"Each personalization must have at least one recipient.",
                f"personalizations[{i}].to",
            )
        for j, recipient in enumerate(to):
            if not isinstance(recipient, dict) or not recipient.get("email"):
                return (
                    f"Each recipient must have an 'email' field.",
                    f"personalizations[{i}].to[{j}].email",
                )
            if not _is_valid_email(recipient["email"]):
                return (
                    f"Does not contain a valid address.",
                    f"personalizations[{i}].to[{j}].email",
                )

    return None, None


@email_bp.route("/v3/mail/send", methods=["POST"])
@require_api_key
def mail_send():
    """SendGrid v3 Mail Send endpoint.

    Accepts a JSON body, validates it, stores the email, simulates delivery,
    and returns 202 Accepted with an empty body and X-Message-Id header.
    """
    if not request.is_json:
        return email_bad_request("request body must be JSON", None)

    data = request.get_json(silent=True)
    if data is None:
        return email_bad_request("request body must be valid JSON", None)

    error_message, error_field = _validate_mail_send(data)
    if error_message:
        return email_bad_request(error_message, error_field)

    message_id = generate_email_id()
    now = now_rfc2822()

    from_obj = data["from"]
    personalizations = data.get("personalizations", [])
    content = data.get("content", [])
    subject = data.get("subject", "")

    # Use first personalization's subject if no top-level subject
    if not subject and personalizations:
        subject = personalizations[0].get("subject", "")

    email_data = {
        "message_id": message_id,
        "account_sid": g.account_sid,
        "from_email": from_obj.get("email", ""),
        "from_name": from_obj.get("name", ""),
        "subject": subject,
        "personalizations": personalizations,
        "content": content,
        "status": "processed",
        "date_created": now,
        "date_updated": now,
    }

    g.storage.create_email(email_data)

    g.storage.append_log({
        "operation": "email.send",
        "account_sid": g.account_sid,
        "message_id": message_id,
        "from_email": from_obj.get("email", ""),
        "subject": subject,
        "personalizations_count": len(personalizations),
    })

    # Simulate delivery in background
    app = current_app._get_current_object()
    storage = g.storage
    thread = threading.Thread(
        target=_simulate_delivery,
        args=(app, storage, email_data),
        daemon=True,
    )
    thread.start()

    resp = current_app.make_response(("", 202))
    resp.headers["X-Message-Id"] = message_id
    return resp
