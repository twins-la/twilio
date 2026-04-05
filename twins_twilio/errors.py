"""Twilio-compatible error responses.

Matches Twilio's error JSON format:
{
    "code": <twilio_error_code>,
    "message": "<description>",
    "more_info": "<url>",
    "status": <http_status>
}
"""

from flask import jsonify


def error_response(http_status: int, code: int, message: str):
    """Return a Twilio-format error response."""
    resp = jsonify({
        "code": code,
        "message": message,
        "more_info": f"https://www.twilio.com/docs/errors/{code}",
        "status": http_status,
    })
    resp.status_code = http_status
    return resp


def not_found(resource_type: str = "resource"):
    return error_response(404, 20404, f"The requested {resource_type} was not found")


def authentication_error():
    return error_response(401, 20003, "Authentication Error - invalid username")


def bad_request(message: str):
    return error_response(400, 21211, message)
