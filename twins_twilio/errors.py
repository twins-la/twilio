"""Twilio-compatible error responses.

Matches Twilio's error JSON format:
{
    "code": <twilio_error_code>,
    "message": "<description>",
    "more_info": "<url>",
    "status": <http_status>
}

Error codes reference: https://www.twilio.com/docs/api/errors
"""

from flask import jsonify, request


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


# -- Authentication errors (20xxx) --

def authentication_error():
    """401 — code 20003: Permission Denied."""
    resp = error_response(401, 20003, "Permission Denied")
    resp.headers["WWW-Authenticate"] = 'Basic realm="Twilio API"'
    return resp


# -- General errors --

def not_found(resource_type: str = "resource"):
    """404 — code 20404: The requested resource was not found."""
    uri = request.path
    return error_response(
        404, 20404,
        f"The requested resource {uri} was not found",
    )


def bad_request(message: str):
    """400 — generic bad request with code 21211. Prefer specific helpers below."""
    return error_response(400, 21211, message)


# -- Messaging errors (216xx) --

def missing_to():
    """400 — code 21604: 'To' phone number is required."""
    return error_response(
        400, 21604,
        "'To' phone number is required to send a Message",
    )


def missing_from():
    """400 — code 21603: 'From' parameter is required."""
    return error_response(
        400, 21603,
        "A 'From' phone number is required to send a Message",
    )


def missing_body():
    """400 — code 21602: Message body is required."""
    return error_response(
        400, 21602,
        "Message body is required to send a SMS",
    )


def invalid_to_number(number: str):
    """400 — code 21211: Invalid 'To' Phone Number."""
    return error_response(
        400, 21211,
        f"The 'To' number {number} is not a valid phone number",
    )


# -- Phone Number errors (214xx) --

def invalid_phone_number(number: str = ""):
    """400 — code 21421: Phone Number is invalid."""
    msg = f"The phone number '{number}' is not valid" if number else "Phone Number is invalid"
    return error_response(400, 21421, msg)
