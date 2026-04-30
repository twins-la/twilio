"""Smoke tests for MMS inbound simulation (NumMedia > 0)."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


class _Capture(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        _Capture.captured.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args, **_kwargs):
        return


def _server():
    _Capture.captured = []
    s = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _provision(client, account, auth_headers, twilio_number, url):
    resp = client.post(
        f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
        headers=auth_headers,
        data={"PhoneNumber": twilio_number, "SmsUrl": url, "SmsMethod": "POST"},
    )
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)


class TestMmsInbound:
    def test_mms_with_external_media_url(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/sms"
            _provision(client, account, auth_headers, "+15551112222", url)

            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "see attached",
                    "num_media": 1,
                    "media_urls": ["https://example.com/cat.jpg"],
                    "media_content_types": ["image/jpeg"],
                },
            )
            assert resp.status_code == 201
            data = resp.get_json()
            assert data["message"]["sid"].startswith("MM")
            assert data["media_urls"] == ["https://example.com/cat.jpg"]
        finally:
            server.shutdown()
            server.server_close()

        params = {k: v[0] for k, v in parse_qs(_Capture.captured[0]["body"]).items()}
        assert params["NumMedia"] == "1"
        assert params["MediaUrl0"] == "https://example.com/cat.jpg"
        assert params["MediaContentType0"] == "image/jpeg"
        assert params["MessageSid"].startswith("MM")

    def test_mms_with_placeholder_media(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/sms"
            _provision(client, account, auth_headers, "+15551112222", url)

            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "",
                    "num_media": 2,
                },
            )
            assert resp.status_code == 201
            data = resp.get_json()
            assert len(data["media_urls"]) == 2
            for url in data["media_urls"]:
                assert "/_twin/media/ME" in url
        finally:
            server.shutdown()
            server.server_close()

        params = {k: v[0] for k, v in parse_qs(_Capture.captured[0]["body"]).items()}
        assert params["NumMedia"] == "2"
        assert "/_twin/media/ME" in params["MediaUrl0"]
        assert "/_twin/media/ME" in params["MediaUrl1"]
        assert params["MediaContentType0"] == "image/png"

    def test_too_many_media_urls_rejected(self, client, account, auth_headers, tenant_headers):
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "account_sid": account["sid"],
                "from": "+15559876543",
                "to": "+15551112222",
                "body": "",
                "num_media": 1,
                "media_urls": ["https://a.example/1", "https://b.example/2"],
            },
        )
        assert resp.status_code == 400

    def test_sms_keeps_sm_prefix(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/sms"
            _provision(client, account, auth_headers, "+15551112222", url)

            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "text only",
                },
            )
            assert resp.status_code == 201
            assert resp.get_json()["message"]["sid"].startswith("SM")
        finally:
            server.shutdown()
            server.server_close()
