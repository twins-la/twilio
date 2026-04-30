"""Webhook delivery and X-Twilio-Signature computation.

Implements Twilio's documented webhook signing algorithm:
1. Start with the full webhook URL (exactly as the operator registered it).
2. For POST requests, sort POST params alphabetically and append name+value to URL.
3. HMAC-SHA1 sign with the account's AuthToken.
4. Base64-encode the result.

The signed URL is **never** normalized, downgraded, or rebuilt. A consumer
that mishandles ``X-Forwarded-Proto`` (rebuilding ``request.url`` as
``http://`` after a TLS-terminating proxy stripped the scheme) will fail
its own signature verification — which is the bug class this twin is
designed to surface in CI.

Two delivery primitives are exposed:

- ``deliver_webhook_sync`` — blocks the caller until the consumer
  responds or the timeout fires. Required for the inbound-SMS path so
  TwiML ``<Response><Message>`` replies can be parsed before returning.
- ``deliver_webhook_async`` — runs the same delivery in a daemon thread
  and returns immediately. Used for status callbacks where the operator
  does not need to block on the consumer.

Both call ``emit()`` with a normative log record after the attempt
(``runtime.webhook.send.{inbound|status}``) so an operator can trace a
correlation_id from request → callback in ``/_twin/logs``.
"""

import base64
import hashlib
import hmac
import logging
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from flask import Flask

from .logs import emit

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 15

# Operations recognized by ``runtime.webhook.send.*`` log entries.
OP_INBOUND = "runtime.webhook.send.inbound"
OP_STATUS = "runtime.webhook.send.status"


@dataclass
class WebhookEmitContext:
    """Carries the request-scoped state a webhook worker needs to emit a
    normative log record after delivery.

    ``app`` and ``storage`` let the worker run inside an app context and
    reach the storage backend. ``correlation_id`` is captured on the
    request thread so the worker's log entry shares the originating
    request's id even though Flask's ``g`` is gone by then.
    """

    app: Flask
    storage: object
    tenant_id: str
    correlation_id: str
    operation: str
    message_sid: str


def compute_signature(auth_token: str, url: str, params: dict) -> str:
    """Compute X-Twilio-Signature for a webhook request.

    Args:
        auth_token: The account's AuthToken (used as HMAC key).
        url: The full webhook URL exactly as the operator registered it.
        params: The POST parameters (will be sorted alphabetically).

    Returns:
        Base64-encoded HMAC-SHA1 signature.
    """
    data = url
    for key in sorted(params.keys()):
        data += key + str(params[key])

    mac = hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


def build_inbound_webhook_params(
    *,
    message_sid: str,
    account_sid: str,
    from_number: str,
    to_number: str,
    body: str,
    num_segments: str = "1",
    num_media: str = "0",
    media_urls: Optional[list[str]] = None,
    media_content_types: Optional[list[str]] = None,
    messaging_service_sid: str = "",
) -> dict:
    """Build POST parameters for an inbound SMS/MMS webhook.

    ``media_urls`` and ``media_content_types`` are zip-aligned and emit
    ``MediaUrl0``, ``MediaContentType0``, … up to ``num_media``. Geographic
    fields remain empty strings (out-of-scope per ``SCENARIOS.md``).
    """
    params = {
        "MessageSid": message_sid,
        "AccountSid": account_sid,
        "From": from_number,
        "To": to_number,
        "Body": body,
        "NumMedia": num_media,
        "NumSegments": num_segments,
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

    media_urls = media_urls or []
    media_content_types = media_content_types or []
    for idx in range(int(num_media or 0)):
        url = media_urls[idx] if idx < len(media_urls) else ""
        ctype = media_content_types[idx] if idx < len(media_content_types) else "image/png"
        params[f"MediaUrl{idx}"] = url
        params[f"MediaContentType{idx}"] = ctype

    return params


def build_status_callback_params(
    *,
    message_sid: str,
    account_sid: str,
    from_number: str,
    to_number: str,
    status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> dict:
    """Build POST parameters for a message status callback.

    ``ErrorCode`` and ``ErrorMessage`` are included only when ``status``
    is ``failed`` or ``undelivered``, matching real Twilio.
    """
    params = {
        "MessageSid": message_sid,
        "AccountSid": account_sid,
        "From": from_number,
        "To": to_number,
        "MessageStatus": status,
    }
    if status in {"failed", "undelivered"}:
        if error_code is not None:
            params["ErrorCode"] = str(error_code)
        if error_message is not None:
            params["ErrorMessage"] = error_message
    return params


def _send_request(
    *, url: str, method: str, params: dict, auth_token: str
) -> Tuple[bool, Optional[str], Optional[int], Optional[str]]:
    """One signed HTTP attempt. Returns the same shape regardless of caller."""
    signature = compute_signature(auth_token, url, params)
    headers = {"X-Twilio-Signature": signature}

    try:
        if method.upper() == "GET":
            resp = requests.get(
                url, params=params, headers=headers, timeout=WEBHOOK_TIMEOUT_SECONDS
            )
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            resp = requests.post(
                url, data=params, headers=headers, timeout=WEBHOOK_TIMEOUT_SECONDS
            )
    except requests.exceptions.Timeout:
        return (
            False,
            f"webhook delivery timed out after {WEBHOOK_TIMEOUT_SECONDS}s",
            None,
            None,
        )
    except requests.exceptions.ConnectionError as exc:
        return (False, f"webhook target unreachable: {exc}", None, None)
    except requests.exceptions.RequestException as exc:
        return (False, f"webhook delivery raised: {exc.__class__.__name__}", None, None)

    if 200 <= resp.status_code < 300:
        return (True, None, resp.status_code, resp.text)
    return (False, f"webhook target returned HTTP {resp.status_code}", resp.status_code, None)


def _emit_attempt(
    ctx: WebhookEmitContext,
    *,
    url: str,
    ok: bool,
    reason: Optional[str],
    status_code: Optional[int],
    method: str,
) -> None:
    """Record the outcome of one webhook attempt as a normative log."""
    from urllib.parse import urlparse

    url_host = urlparse(url).netloc or url

    emit(
        ctx.storage,
        tenant_id=ctx.tenant_id,
        plane="runtime",
        operation=ctx.operation,
        resource={"type": "message", "id": ctx.message_sid},
        outcome="success" if ok else "failure",
        reason=reason,
        details={
            "url": url,
            "url_host": url_host,
            "http_method": method.upper(),
            "status_code": status_code,
        },
    )


def deliver_webhook_sync(
    *,
    url: str,
    method: str,
    params: dict,
    auth_token: str,
    emit_ctx: WebhookEmitContext,
) -> Tuple[bool, Optional[str], Optional[int], Optional[str]]:
    """Deliver a webhook synchronously and emit a runtime log entry.

    Returns ``(ok, reason, status_code, response_text)``. The caller is
    expected to act on ``response_text`` (e.g., parse TwiML).
    """
    ok, reason, status_code, response_text = _send_request(
        url=url, method=method, params=params, auth_token=auth_token
    )
    _emit_attempt(
        emit_ctx, url=url, ok=ok, reason=reason, status_code=status_code, method=method
    )
    return (ok, reason, status_code, response_text)


def deliver_webhook_async(
    *,
    url: str,
    method: str,
    params: dict,
    auth_token: str,
    emit_ctx: WebhookEmitContext,
) -> threading.Thread:
    """Deliver a webhook in a daemon thread; emit a runtime log entry.

    Returns the started thread (mainly for tests that need to ``join``).
    The worker swallows no exceptions — any failure produces a normative
    failure log via ``_emit_attempt``.
    """

    def _worker() -> None:
        try:
            ok, reason, status_code, _ = _send_request(
                url=url, method=method, params=params, auth_token=auth_token
            )
        except Exception as exc:  # pragma: no cover — defensive
            ok, reason, status_code = False, f"worker raised: {exc.__class__.__name__}", None

        try:
            with emit_ctx.app.app_context():
                from flask import g

                g.storage = emit_ctx.storage
                g.correlation_id = emit_ctx.correlation_id
                _emit_attempt(
                    emit_ctx,
                    url=url,
                    ok=ok,
                    reason=reason,
                    status_code=status_code,
                    method=method,
                )
        except Exception:
            # The daemon thread is exiting; the request thread is gone. The
            # only thing left is stdlib logging — losing the failure here
            # silently would defeat the telemetry contract.
            logger.exception(
                "Failed to emit runtime.webhook.send.* log for url=%s message_sid=%s",
                url, emit_ctx.message_sid,
            )

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


