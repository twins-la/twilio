"""Smoke tests for POST /_twin/simulate/status.

The endpoint forces a status transition on a tenant-owned outbound
message and fires the registered status callback.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


class _CapturingHandler(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        _CapturingHandler.captured.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args, **_kwargs):
        return


def _start_capture_server():
    _CapturingHandler.captured = []
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _wait_for(predicate, timeout=2.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _send_outbound(client, account, auth_headers, to_number, callback_url):
    client.post(
        f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
        headers=auth_headers,
        data={"PhoneNumber": "+15551112222"},
    )
    resp = client.post(
        f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
        headers=auth_headers,
        data={
            "To": to_number,
            "From": "+15551112222",
            "Body": "ping",
            "StatusCallback": callback_url,
            "StatusCallbackMethod": "POST",
        },
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


class TestStatusSimulation:
    def test_simulate_failed_with_error_code(self, client, account, auth_headers, tenant_headers):
        server, _thread = _start_capture_server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/status"
            msg = _send_outbound(client, account, auth_headers, "+15559876543", url)
            assert _wait_for(lambda: len(_CapturingHandler.captured) >= 3, timeout=3.0), (
                "auto progression should fire 3 callbacks (sending/sent/delivered)"
            )

            resp = client.post(
                "/_twin/simulate/status",
                headers=tenant_headers,
                json={"message_sid": msg["sid"], "status": "failed", "error_code": 30003},
            )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            data = resp.get_json()
            assert data["message"]["status"] == "failed"
            assert data["status_callback"]["fired"] is True

            assert _wait_for(lambda: len(_CapturingHandler.captured) >= 4, timeout=3.0)
        finally:
            server.shutdown()
            server.server_close()

        forced = _CapturingHandler.captured[-1]
        params = {k: v[0] for k, v in parse_qs(forced["body"]).items()}
        assert params["MessageStatus"] == "failed"
        assert params["ErrorCode"] == "30003"
        assert params["MessageSid"] == msg["sid"]
        assert "X-Twilio-Signature" in forced["headers"]

    def test_simulate_undelivered_requires_error_code(
        self, client, account, auth_headers, tenant_headers
    ):
        server, _thread = _start_capture_server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/status"
            msg = _send_outbound(client, account, auth_headers, "+15559876543", url)
            resp = client.post(
                "/_twin/simulate/status",
                headers=tenant_headers,
                json={"message_sid": msg["sid"], "status": "undelivered"},
            )
            assert resp.status_code == 400
            assert "error_code" in resp.get_json()["error"]
        finally:
            server.shutdown()
            server.server_close()

    def test_simulate_status_invalid(self, client, account, auth_headers, tenant_headers):
        server, _thread = _start_capture_server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/status"
            msg = _send_outbound(client, account, auth_headers, "+15559876543", url)
            resp = client.post(
                "/_twin/simulate/status",
                headers=tenant_headers,
                json={"message_sid": msg["sid"], "status": "weird"},
            )
            assert resp.status_code == 400
        finally:
            server.shutdown()
            server.server_close()

    def test_simulate_status_unknown_message(self, client, account, auth_headers, tenant_headers):
        resp = client.post(
            "/_twin/simulate/status",
            headers=tenant_headers,
            json={"message_sid": "SM" + "0" * 32, "status": "delivered"},
        )
        assert resp.status_code == 404

    def test_simulate_status_cross_tenant_isolation(
        self, client, account, auth_headers, tenant_headers, tenant_store
    ):
        """Tenant B cannot force a status transition on tenant A's message."""
        server, _thread = _start_capture_server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/status"
            msg = _send_outbound(client, account, auth_headers, "+15559876543", url)

            import base64
            from twins_local.tenants import (
                generate_tenant_id, generate_tenant_secret, hash_secret,
            )
            other_id = generate_tenant_id()
            other_secret = generate_tenant_secret()
            tenant_store.create_tenant(
                tenant_id=other_id,
                secret_hash=hash_secret(other_secret),
                friendly_name="Other Tenant",
            )
            creds = base64.b64encode(f"{other_id}:{other_secret}".encode()).decode()
            other_headers = {"Authorization": f"Basic {creds}"}

            resp = client.post(
                "/_twin/simulate/status",
                headers=other_headers,
                json={"message_sid": msg["sid"], "status": "delivered"},
            )
            assert resp.status_code == 404, resp.get_data(as_text=True)
        finally:
            server.shutdown()
            server.server_close()

    def test_simulate_status_no_callback_registered(
        self, client, account, auth_headers, tenant_headers
    ):
        client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551112222"},
        )
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551112222", "Body": "no-cb"},
        )
        msg = resp.get_json()

        resp = client.post(
            "/_twin/simulate/status",
            headers=tenant_headers,
            json={"message_sid": msg["sid"], "status": "delivered"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status_callback"]["fired"] is False
        assert data["message"]["status"] == "delivered"

    def test_simulate_status_terminal_persists_against_progression_worker(
        self, client, account, auth_headers, tenant_headers
    ):
        """Closes twins-la/twilio#5: the background progression worker
        (queued → sending → sent → delivered, ~0.6s end-to-end) must NOT
        clobber a manually-set terminal status (delivered/failed/undelivered).
        Real Twilio considers those terminal — no further automatic
        transitions occur.

        Race shape this test prevents: simulate/status sets "delivered"
        within the worker's first 0.1s sleep window; if the worker doesn't
        re-check current status before its next update, it overwrites
        "delivered" with "sending" and the assertion in the previous test
        fires intermittently.

        Deterministic reproduction: call simulate/status, then wait long
        enough for the entire worker cycle (0.6s + slack) to complete,
        then read the message and assert it's still "delivered".
        """
        import time

        client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551112333"},
        )
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876544", "From": "+15551112333", "Body": "race-fix"},
        )
        msg = resp.get_json()

        # Set terminal status BEFORE the worker has had time to progress.
        resp = client.post(
            "/_twin/simulate/status",
            headers=tenant_headers,
            json={"message_sid": msg["sid"], "status": "delivered"},
        )
        assert resp.status_code == 200

        # Wait past the worker's full transition window (0.1 + 0.2 + 0.3 = 0.6s).
        time.sleep(1.0)

        # Read back: status MUST still be "delivered". If the worker
        # clobbered it, this assertion fires.
        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/Messages/{msg['sid']}.json",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "delivered"
