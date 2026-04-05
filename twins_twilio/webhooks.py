"""Webhook delivery and X-Twilio-Signature computation.

Implements Twilio's documented webhook signing algorithm:
1. Start with the full webhook URL
2. For POST requests, sort POST params alphabetically, append name+value to URL
3. HMAC-SHA1 sign with the account's AuthToken
4. Base64-encode the result
"""

import base64
import hashlib
import hmac
import logging
import threading
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)


def compute_signature(auth_token: str, url: str, params: dict) -> str:
    """Compute X-Twilio-Signature for a webhook request.

    Args:
        auth_token: The account's AuthToken (used as HMAC key).
        url: The full webhook URL.
        params: The POST parameters (will be sorted alphabetically).

    Returns:
        Base64-encoded HMAC-SHA1 signature.
    """
    # Start with the URL
    data = url

    # Sort parameters alphabetically by key, append key+value
    for key in sorted(params.keys()):
        data += key + str(params[key])

    # HMAC-SHA1 with AuthToken as key
    mac = hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    )

    return base64.b64encode(mac.digest()).decode("utf-8")


def build_webhook_params(
    message_sid: str,
    account_sid: str,
    from_number: str,
    to_number: str,
    body: str,
    num_segments: str = "1",
    num_media: str = "0",
    messaging_service_sid: str = "",
) -> dict:
    """Build the POST parameters for an incoming SMS webhook.

    Matches Twilio's documented webhook parameter set.
    """
    params = {
        "MessageSid": message_sid,
        "AccountSid": account_sid,
        "From": from_number,
        "To": to_number,
        "Body": body,
        "NumMedia": num_media,
        "NumSegments": num_segments,
        # Geographic data — fabricated for twin (out-of-scope per PRINCIPLES.md §4)
        "FromCity": "",
        "FromState": "",
        "FromZip": "",
        "FromCountry": "",
        "ToCity": "",
        "ToState": "",
        "ToZip": "",
        "ToCountry": "",
    }
    if messaging_service_sid:
        params["MessagingServiceSid"] = messaging_service_sid
    return params


def deliver_webhook(
    url: str,
    method: str,
    params: dict,
    auth_token: str,
    callback=None,
) -> None:
    """Deliver a webhook request to the configured URL.

    Runs in a background thread to avoid blocking the API response.

    Args:
        url: The webhook URL to call.
        method: HTTP method (GET or POST).
        params: The webhook parameters.
        auth_token: Account AuthToken for signature computation.
        callback: Optional callable(response_text, status_code) for handling
                  the webhook response (e.g., TwiML parsing).
    """
    def _deliver():
        try:
            signature = compute_signature(auth_token, url, params)
            headers = {"X-Twilio-Signature": signature}

            if method.upper() == "GET":
                resp = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=15,
                )
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                resp = requests.post(
                    url,
                    data=params,
                    headers=headers,
                    timeout=15,
                )

            logger.info(
                "Webhook delivered to %s — status %d", url, resp.status_code
            )

            if callback and resp.status_code == 200:
                callback(resp.text, resp.status_code)

        except Exception:
            logger.exception("Webhook delivery failed for %s", url)

    thread = threading.Thread(target=_deliver, daemon=True)
    thread.start()
    return thread


def deliver_status_callback(
    url: str,
    method: str,
    message_sid: str,
    account_sid: str,
    from_number: str,
    to_number: str,
    status: str,
    auth_token: str,
) -> None:
    """Deliver a status callback webhook for message status changes."""
    params = {
        "MessageSid": message_sid,
        "AccountSid": account_sid,
        "From": from_number,
        "To": to_number,
        "MessageStatus": status,
    }

    def _deliver():
        try:
            signature = compute_signature(auth_token, url, params)
            headers = {"X-Twilio-Signature": signature}

            if method.upper() == "GET":
                requests.get(url, params=params, headers=headers, timeout=15)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                requests.post(url, data=params, headers=headers, timeout=15)
        except Exception:
            logger.exception("Status callback delivery failed for %s", url)

    thread = threading.Thread(target=_deliver, daemon=True)
    thread.start()
