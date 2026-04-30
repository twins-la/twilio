"""End-to-end X-Twilio-Signature byte-equality check.

The twin's existing tests assert the X-Twilio-Signature header is
*present*. This test recomputes the signature using a hand-rolled
reference (independent of the twin's compute_signature) and asserts the
twin's value matches byte-for-byte. A signature-computation regression
that breaks consumer signature validation in production must fail here.
"""

import base64
import hashlib
import hmac
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


class _Capture(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        _Capture.captured.append(
            {
                "path": self.path,
                "body": body,
                "headers": dict(self.headers),
            }
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args, **_kwargs):
        return


def _server():
    _Capture.captured = []
    s = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _reference_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio's algorithm, reimplemented inline so the test does not share
    code with the twin under test. URL + sorted params (k+v) → HMAC-SHA1
    keyed with AuthToken → base64."""
    data = url
    for key in sorted(params.keys()):
        data += key + str(params[key])
    digest = hmac.new(
        auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")


class TestSignatureExactness:
    def test_inbound_signature_matches_reference(
        self, client, account, auth_headers, tenant_headers
    ):
        server = _server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/incoming/sms"
            client.post(
                f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
                headers=auth_headers,
                data={"PhoneNumber": "+15551112222", "SmsUrl": url, "SmsMethod": "POST"},
            )
            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "exact match required",
                },
            )
            assert resp.status_code == 201
        finally:
            server.shutdown()
            server.server_close()

        captured = _Capture.captured[0]
        assert captured["path"] == "/incoming/sms"
        # keep_blank_values is essential: Twilio includes empty-string fields
        # like FromCity in the signed param set; dropping them yields a
        # different reference signature.
        sent_params = {
            k: v[0] for k, v in parse_qs(captured["body"], keep_blank_values=True).items()
        }
        sent_signature = captured["headers"].get("X-Twilio-Signature")
        assert sent_signature, "twin must send X-Twilio-Signature"

        expected = _reference_signature(account["auth_token"], url, sent_params)
        assert sent_signature == expected, (
            "Signature mismatch — twin and reference disagree.\n"
            f"  url: {url}\n"
            f"  params: {sent_params}\n"
            f"  twin sent: {sent_signature}\n"
            f"  reference: {expected}"
        )

    def test_signature_changes_with_url(self):
        """Sanity: changing the URL changes the signature. This is the
        property that makes X-Forwarded-Proto bugs surface — if the
        consumer rebuilds the URL with the wrong scheme/host, their
        verification will fail."""
        from twins_twilio.webhooks import compute_signature

        params = {"From": "+1", "Body": "hi"}
        token = "a" * 32
        sig_https = compute_signature(token, "https://example.com/webhook", params)
        sig_http = compute_signature(token, "http://example.com/webhook", params)
        assert sig_https != sig_http
