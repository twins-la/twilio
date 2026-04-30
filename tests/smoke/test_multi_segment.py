"""Multi-segment inbound — NumSegments > 1."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


class _Capture(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        _Capture.captured.append({"body": body})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args, **_kwargs):
        return


def _server():
    _Capture.captured = []
    s = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


class TestMultiSegment:
    def test_num_segments_propagates(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/sms"
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
                    "body": "x" * 480,
                    "num_segments": 3,
                },
            )
            assert resp.status_code == 201
        finally:
            server.shutdown()
            server.server_close()

        params = {k: v[0] for k, v in parse_qs(_Capture.captured[0]["body"]).items()}
        assert params["NumSegments"] == "3"

    def test_zero_segments_rejected(self, client, account, auth_headers, tenant_headers):
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "account_sid": account["sid"],
                "from": "+15559876543",
                "to": "+15551112222",
                "body": "hi",
                "num_segments": 0,
            },
        )
        assert resp.status_code == 400
