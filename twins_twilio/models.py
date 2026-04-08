"""Data serialization helpers for Twilio-compatible response shapes.

These functions convert internal storage dicts into Twilio API response format.
Field names match Twilio's documented JSON response fields exactly.
"""

from datetime import datetime, timezone


def _rfc2822(dt: datetime) -> str:
    """Format a datetime as RFC 2822, matching Twilio's format."""
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def now_rfc2822() -> str:
    return _rfc2822(_now())


def account_to_json(account: dict, base_url: str) -> dict:
    """Convert a stored account to Twilio Account JSON response."""
    sid = account["sid"]
    return {
        "sid": sid,
        "friendly_name": account.get("friendly_name", ""),
        "auth_token": account["auth_token"],
        "status": account.get("status", "active"),
        "type": "Full",
        "date_created": account.get("date_created", now_rfc2822()),
        "date_updated": account.get("date_updated", now_rfc2822()),
        "owner_account_sid": sid,
        "uri": f"/2010-04-01/Accounts/{sid}.json",
        "subresource_uris": {
            "messages": f"/2010-04-01/Accounts/{sid}/Messages.json",
            "incoming_phone_numbers": f"/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json",
        },
    }


def account_to_json_public(account: dict, base_url: str) -> dict:
    """Convert a stored account to JSON without auth_token (for admin listings)."""
    result = account_to_json(account, base_url)
    del result["auth_token"]
    return result


def phone_number_to_json(pn: dict, base_url: str) -> dict:
    """Convert a stored phone number to Twilio IncomingPhoneNumber JSON."""
    sid = pn["sid"]
    account_sid = pn["account_sid"]
    return {
        "sid": sid,
        "account_sid": account_sid,
        "friendly_name": pn.get("friendly_name", pn.get("phone_number", "")),
        "phone_number": pn["phone_number"],
        "voice_url": pn.get("voice_url", ""),
        "voice_method": pn.get("voice_method", "POST"),
        "voice_fallback_url": pn.get("voice_fallback_url", ""),
        "voice_fallback_method": pn.get("voice_fallback_method", "POST"),
        "sms_url": pn.get("sms_url", ""),
        "sms_method": pn.get("sms_method", "POST"),
        "sms_fallback_url": pn.get("sms_fallback_url", ""),
        "sms_fallback_method": pn.get("sms_fallback_method", "POST"),
        "status_callback": pn.get("status_callback", ""),
        "status_callback_method": pn.get("status_callback_method", "POST"),
        "voice_application_sid": pn.get("voice_application_sid", ""),
        "sms_application_sid": pn.get("sms_application_sid", ""),
        "capabilities": {
            "voice": False,
            "sms": True,
            "mms": False,
            "fax": False,
        },
        "status": "in-use",
        "date_created": pn.get("date_created", now_rfc2822()),
        "date_updated": pn.get("date_updated", now_rfc2822()),
        "api_version": "2010-04-01",
        "uri": f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers/{sid}.json",
    }


def message_to_json(msg: dict, base_url: str) -> dict:
    """Convert a stored message to Twilio Message JSON."""
    sid = msg["sid"]
    account_sid = msg["account_sid"]
    return {
        "sid": sid,
        "account_sid": account_sid,
        "date_created": msg.get("date_created", now_rfc2822()),
        "date_updated": msg.get("date_updated", now_rfc2822()),
        "date_sent": msg.get("date_sent", ""),
        "to": msg.get("to", ""),
        "from": msg.get("from_number", ""),
        "body": msg.get("body", ""),
        "status": msg.get("status", "queued"),
        "num_segments": str(msg.get("num_segments", "1")),
        "num_media": "0",
        "direction": msg.get("direction", "outbound-api"),
        "price": msg.get("price"),
        "price_unit": "USD",
        "error_code": msg.get("error_code"),
        "error_message": msg.get("error_message"),
        "api_version": "2010-04-01",
        "messaging_service_sid": msg.get("messaging_service_sid"),
        "uri": f"/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json",
        "subresource_uris": {
            "media": f"/2010-04-01/Accounts/{account_sid}/Messages/{sid}/Media.json",
        },
    }
