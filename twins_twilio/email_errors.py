"""SendGrid-compatible error responses.

SendGrid error format:
{
    "errors": [
        {
            "message": "<description>",
            "field": "<field_name or null>",
            "help": null
        }
    ]
}
"""

from flask import jsonify


def email_error_response(http_status: int, message: str, field: str | None = None):
    """Return a SendGrid-format error response."""
    resp = jsonify({
        "errors": [
            {
                "message": message,
                "field": field,
                "help": None,
            }
        ]
    })
    resp.status_code = http_status
    return resp


def email_authentication_error():
    return email_error_response(401, "authorization required")


def email_bad_request(message: str, field: str | None = None):
    return email_error_response(400, message, field)
