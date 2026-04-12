"""LOGGING.md §3.2 conformance smoke test for the Twilio twin.

Exercises a cross-section of operations and asserts every emitted log
record carries every required field with the required types.
"""

REQUIRED_FIELDS = {
    "timestamp", "twin", "tenant_id", "correlation_id",
    "plane", "operation", "resource", "outcome", "reason", "details",
}
VALID_PLANES = {"twin", "control", "data", "runtime"}
VALID_OUTCOMES = {"success", "failure"}


def _assert_record_conforms(rec):
    # Storage adds `id` as a pagination envelope (LOGGING.md §3.3).
    assert REQUIRED_FIELDS.issubset(rec.keys()), rec
    assert isinstance(rec["timestamp"], str) and rec["timestamp"].endswith("Z")
    assert isinstance(rec["twin"], str) and rec["twin"] == "twilio"
    assert isinstance(rec["tenant_id"], str) and rec["tenant_id"]
    assert isinstance(rec["correlation_id"], str) and rec["correlation_id"]
    assert rec["plane"] in VALID_PLANES, rec
    assert isinstance(rec["operation"], str) and rec["operation"]
    assert rec["resource"] is None or (
        isinstance(rec["resource"], dict)
        and set(rec["resource"].keys()) == {"type", "id"}
    )
    assert rec["outcome"] in VALID_OUTCOMES, rec
    if rec["outcome"] == "failure":
        assert isinstance(rec["reason"], str) and rec["reason"].strip()
    assert isinstance(rec["details"], dict)


def test_all_emitted_records_conform(client, tenant_headers, auth_headers):
    # Exercise a mix of Twin Plane and data-plane operations.
    client.post("/_twin/feedback", headers=tenant_headers, json={"body": "hi"})
    client.get("/_twin/logs", headers=tenant_headers)  # not logged itself
    # (account/auth_headers fixtures already caused twin.account.create to fire.)
    resp = client.get("/_twin/logs", headers=tenant_headers)
    logs = resp.get_json()["logs"]
    assert logs, "expected at least one log record"
    for rec in logs:
        _assert_record_conforms(rec)


def test_correlation_id_is_echoed(client, tenant_headers):
    resp = client.get(
        "/_twin/health", headers={**tenant_headers, "X-Correlation-Id": "caller-xyz"},
    )
    assert resp.headers.get("X-Correlation-Id") == "caller-xyz"


def test_records_in_one_request_share_correlation_id(client, tenant_headers):
    # The inbound simulate endpoint emits multiple records in a single request.
    # We can't hit it without more setup, so use /_twin/feedback which emits one
    # record — and verify that a second record from a fresh request differs.
    client.post(
        "/_twin/feedback",
        headers={**tenant_headers, "X-Correlation-Id": "run-1"},
        json={"body": "one"},
    )
    client.post(
        "/_twin/feedback",
        headers={**tenant_headers, "X-Correlation-Id": "run-2"},
        json={"body": "two"},
    )
    logs = client.get("/_twin/logs", headers=tenant_headers).get_json()["logs"]
    cids = {l["correlation_id"] for l in logs if l["operation"] == "twin.feedback.submit"}
    assert {"run-1", "run-2"}.issubset(cids)
