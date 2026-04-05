"""Twilio IncomingPhoneNumber resource routes.

POST /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers.json — Create
GET  /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers.json — List
GET  /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers/{Sid}.json — Fetch
POST /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers/{Sid}.json — Update
"""

import re

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..errors import bad_request, not_found
from ..models import now_rfc2822, phone_number_to_json
from ..sids import generate_phone_number_sid

phone_numbers_bp = Blueprint("phone_numbers", __name__)

PREFIX = "/2010-04-01/Accounts/<account_sid>/IncomingPhoneNumbers"

# Fields that can be set on create or update
WRITABLE_FIELDS = [
    "friendly_name", "sms_url", "sms_method", "sms_fallback_url",
    "sms_fallback_method", "sms_application_sid", "voice_url", "voice_method",
    "voice_fallback_url", "voice_fallback_method", "voice_application_sid",
    "status_callback", "status_callback_method",
]

# Map from Twilio POST param names (PascalCase) to internal snake_case
PARAM_MAP = {
    "FriendlyName": "friendly_name",
    "SmsUrl": "sms_url",
    "SmsMethod": "sms_method",
    "SmsFallbackUrl": "sms_fallback_url",
    "SmsFallbackMethod": "sms_fallback_method",
    "SmsApplicationSid": "sms_application_sid",
    "VoiceUrl": "voice_url",
    "VoiceMethod": "voice_method",
    "VoiceFallbackUrl": "voice_fallback_url",
    "VoiceFallbackMethod": "voice_fallback_method",
    "VoiceApplicationSid": "voice_application_sid",
    "StatusCallback": "status_callback",
    "StatusCallbackMethod": "status_callback_method",
}


def _extract_params() -> dict:
    """Extract known Twilio params from the request form data."""
    updates = {}
    for twilio_name, internal_name in PARAM_MAP.items():
        val = request.form.get(twilio_name)
        if val is not None:
            updates[internal_name] = val
    return updates


@phone_numbers_bp.route(f"{PREFIX}.json", methods=["POST"])
@require_auth
def create_phone_number(account_sid):
    """Provision a phone number."""
    phone_number = request.form.get("PhoneNumber")
    if not phone_number:
        return bad_request("PhoneNumber is required")

    # Validate E.164-ish format (Twilio requires E.164 for provisioning)
    if not re.match(r"^\+[1-9]\d{1,14}$", phone_number):
        return bad_request(
            f"The phone number '{phone_number}' is not valid. "
            "Phone numbers must be in E.164 format (e.g., +15551234567)."
        )

    sid = generate_phone_number_sid()
    now = now_rfc2822()

    data = {
        "sid": sid,
        "account_sid": account_sid,
        "phone_number": phone_number,
        "date_created": now,
        "date_updated": now,
    }

    # Apply optional params
    data.update(_extract_params())

    # Default friendly_name to the phone number if not provided
    if "friendly_name" not in data:
        data["friendly_name"] = phone_number

    result = g.storage.create_phone_number(data)

    g.storage.append_log({
        "operation": "phone_number.create",
        "account_sid": account_sid,
        "phone_number_sid": sid,
        "phone_number": phone_number,
    })

    resp = jsonify(phone_number_to_json(result, g.base_url))
    resp.status_code = 201
    return resp


@phone_numbers_bp.route(f"{PREFIX}.json", methods=["GET"])
@require_auth
def list_phone_numbers(account_sid):
    """List all phone numbers for an account."""
    numbers = g.storage.list_phone_numbers(account_sid)

    g.storage.append_log({
        "operation": "phone_number.list",
        "account_sid": account_sid,
    })

    items = [phone_number_to_json(pn, g.base_url) for pn in numbers]
    return jsonify({
        "incoming_phone_numbers": items,
        "uri": f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json",
        "page": 0,
        "page_size": 50,
        "first_page_uri": f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json?Page=0&PageSize=50",
        "next_page_uri": "",
        "previous_page_uri": "",
    })


@phone_numbers_bp.route(f"{PREFIX}/<sid>.json", methods=["GET"])
@require_auth
def fetch_phone_number(account_sid, sid):
    """Fetch a single phone number by SID."""
    pn = g.storage.get_phone_number(account_sid, sid)
    if not pn:
        return not_found("IncomingPhoneNumber")

    g.storage.append_log({
        "operation": "phone_number.fetch",
        "account_sid": account_sid,
        "phone_number_sid": sid,
    })

    return jsonify(phone_number_to_json(pn, g.base_url))


@phone_numbers_bp.route(f"{PREFIX}/<sid>.json", methods=["POST"])
@require_auth
def update_phone_number(account_sid, sid):
    """Update a phone number's configuration."""
    updates = _extract_params()
    if not updates:
        return bad_request("No valid parameters provided")

    updates["date_updated"] = now_rfc2822()
    result = g.storage.update_phone_number(account_sid, sid, updates)
    if not result:
        return not_found("IncomingPhoneNumber")

    g.storage.append_log({
        "operation": "phone_number.update",
        "account_sid": account_sid,
        "phone_number_sid": sid,
        "updates": list(updates.keys()),
    })

    return jsonify(phone_number_to_json(result, g.base_url))
