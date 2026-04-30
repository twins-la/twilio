"""Async webhook attempts emit normative logs with correlation_id.

The status-callback path delivers in a background thread. The thread
must propagate the originating request's correlation_id and emit a
runtime.webhook.send.status log with outcome/reason/status_code so a
debug session can pick up the trail from /_twin/logs.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


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


def _wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class TestAsyncWebhookLogging:
    def test_status_callback_emits_correlated_log(
        self, client, account, auth_headers, tenant_headers
    ):
        server = _server()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/status"
            client.post(
                f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
                headers=auth_headers,
                data={"PhoneNumber": "+15551112222"},
            )

            cid = "corr_test_async_logging_fixed"
            resp = client.post(
                f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
                headers={**auth_headers, "X-Correlation-Id": cid},
                data={
                    "To": "+15559876543",
                    "From": "+15551112222",
                    "Body": "ping",
                    "StatusCallback": url,
                    "StatusCallbackMethod": "POST",
                },
            )
            assert resp.status_code == 201
            assert _wait_for(lambda: len(_Capture.captured) >= 3)
        finally:
            server.shutdown()
            server.server_close()

        # The logs are written from the daemon thread; allow a brief moment
        # for the after-attempt emit to complete.
        def _have_logs():
            logs = client.get("/_twin/logs", headers=tenant_headers).get_json()["logs"]
            return [r for r in logs if r["operation"] == "runtime.webhook.send.status"]

        assert _wait_for(lambda: len(_have_logs()) >= 3, timeout=3.0)
        status_logs = _have_logs()

        # Every status-callback log has the originating request's correlation id.
        for rec in status_logs:
            assert rec["correlation_id"] == cid, rec
            assert rec["plane"] == "runtime"
            assert rec["outcome"] == "success"
            assert rec["details"]["status_code"] == 200
            assert rec["details"]["http_method"] == "POST"
            assert rec["details"]["url_host"].endswith(f":{server.server_address[1]}") or \
                ":" in rec["details"]["url_host"]
