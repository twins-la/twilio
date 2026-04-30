"""Smoke tests for STOP / START / HELP keyword semantics.

The twin recognises Twilio's documented opt-out keywords on inbound
SMS bodies, records opt-out state per (account, twilio_number,
recipient), enforces it on outbound, and auto-replies to HELP.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Silent(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args, **_kwargs):
        return


def _server():
    s = HTTPServer(("127.0.0.1", 0), _Silent)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _provision(client, account, auth_headers, twilio_number, url):
    resp = client.post(
        f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
        headers=auth_headers,
        data={"PhoneNumber": twilio_number, "SmsUrl": url, "SmsMethod": "POST"},
    )
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)


class TestKeywordDetection:
    def test_stop_records_opt_out(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            _provision(client, account, auth_headers, "+15551112222", f"http://127.0.0.1:{port}/")

            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "STOP",
                },
            )
            assert resp.status_code == 201
            assert resp.get_json()["keyword"] == "STOP"
        finally:
            server.shutdown()
            server.server_close()

        # Subsequent outbound is rejected with 21610
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551112222", "Body": "hi"},
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == 21610
        assert "+15559876543" in body["message"]

        # And a normative log entry was written for the opt-out.
        logs = client.get("/_twin/logs", headers=tenant_headers).get_json()["logs"]
        opt_out_logs = [r for r in logs if r["operation"] == "runtime.opt_out.set"]
        assert len(opt_out_logs) == 1
        rec = opt_out_logs[0]
        assert rec["resource"]["type"] == "opt_out"
        assert rec["details"]["twilio_number"] == "+15551112222"
        assert rec["details"]["recipient"] == "+15559876543"

    def test_stop_does_not_block_other_recipients(
        self, client, account, auth_headers, tenant_headers
    ):
        """Opt-out is per (twilio_number, recipient) — other recipients still
        receive messages."""
        server = _server()
        try:
            port = server.server_address[1]
            _provision(client, account, auth_headers, "+15551112222", f"http://127.0.0.1:{port}/")
            client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "STOP",
                },
            )
        finally:
            server.shutdown()
            server.server_close()

        # Different recipient — should succeed.
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15558887777", "From": "+15551112222", "Body": "hi"},
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)

    def test_start_clears_opt_out(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            _provision(client, account, auth_headers, "+15551112222", f"http://127.0.0.1:{port}/")

            for body in ("STOP", "START"):
                client.post(
                    "/_twin/simulate/inbound",
                    headers=tenant_headers,
                    json={
                        "account_sid": account["sid"],
                        "from": "+15559876543",
                        "to": "+15551112222",
                        "body": body,
                    },
                )
        finally:
            server.shutdown()
            server.server_close()

        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551112222", "Body": "hi"},
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)

    def test_help_triggers_auto_reply(self, client, account, auth_headers, tenant_headers):
        server = _server()
        try:
            port = server.server_address[1]
            _provision(client, account, auth_headers, "+15551112222", f"http://127.0.0.1:{port}/")

            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "help",
                },
            )
        finally:
            server.shutdown()
            server.server_close()

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["keyword"] == "HELP"
        assert len(data["replies"]) == 1
        reply = data["replies"][0]
        assert reply["direction"] == "outbound-auto"
        assert "STOP" in reply["body"] and "HELP" in reply["body"]

    def test_stop_isolated_per_account(self, client, account, auth_headers, tenant_headers):
        """Opt-out state is per (account, twilio_number, recipient).

        A second Twilio number on the same account can still send to a
        recipient who STOPped the first number.
        """
        server = _server()
        try:
            port = server.server_address[1]
            _provision(client, account, auth_headers, "+15551112222", f"http://127.0.0.1:{port}/")
            _provision(client, account, auth_headers, "+15553334444", f"http://127.0.0.1:{port}/")

            client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "STOP",
                },
            )
        finally:
            server.shutdown()
            server.server_close()

        # First number rejected
        resp1 = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551112222", "Body": "hi"},
        )
        assert resp1.status_code == 400

        # Second number still allowed
        resp2 = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15553334444", "Body": "hi"},
        )
        assert resp2.status_code == 201

    def test_non_keyword_body_does_not_opt_out(self, client, account, auth_headers, tenant_headers):
        """Real Twilio matches the keyword as the entire body, after trim.
        'stop please' is not STOP."""
        server = _server()
        try:
            port = server.server_address[1]
            _provision(client, account, auth_headers, "+15551112222", f"http://127.0.0.1:{port}/")

            resp = client.post(
                "/_twin/simulate/inbound",
                headers=tenant_headers,
                json={
                    "account_sid": account["sid"],
                    "from": "+15559876543",
                    "to": "+15551112222",
                    "body": "stop please",
                },
            )
        finally:
            server.shutdown()
            server.server_close()

        assert resp.status_code == 201
        assert "keyword" not in resp.get_json()

        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551112222", "Body": "hi"},
        )
        assert resp.status_code == 201

    def test_stop_with_punctuation(self, client, account, auth_headers, tenant_headers):
        """'STOP!' and ' stop ' are still STOP."""
        from twins_twilio.keywords import detect_keyword

        assert detect_keyword("STOP!") == "STOP"
        assert detect_keyword(" stop ") == "STOP"
        assert detect_keyword("STOP.") == "STOP"
        assert detect_keyword("Unsubscribe") == "STOP"
        assert detect_keyword("HELP") == "HELP"
        assert detect_keyword("START") == "START"
        assert detect_keyword("YES") == "START"
        assert detect_keyword("anything else") is None
        assert detect_keyword("") is None
