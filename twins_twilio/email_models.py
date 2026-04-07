"""Data serialization helpers for email responses.

Used by the Twin Plane to expose stored emails for inspection.
The SendGrid /v3/mail/send endpoint itself returns no body.
"""

from .models import now_rfc2822


def email_to_json(email: dict) -> dict:
    """Convert a stored email to a JSON-serializable dict for Twin Plane retrieval."""
    return {
        "message_id": email.get("message_id", ""),
        "account_sid": email.get("account_sid", ""),
        "from": {
            "email": email.get("from_email", ""),
            "name": email.get("from_name", ""),
        },
        "subject": email.get("subject", ""),
        "personalizations": email.get("personalizations", []),
        "content": email.get("content", []),
        "status": email.get("status", "processed"),
        "date_created": email.get("date_created", now_rfc2822()),
        "date_updated": email.get("date_updated", now_rfc2822()),
    }
