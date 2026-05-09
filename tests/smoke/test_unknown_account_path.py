"""Sweep test: unknown ``/<api_version>/Accounts/<sid>/<rest>`` paths
return Twilio-shaped JSON 404. Closes twins-la/twins-la#2 (twilio half).

Twilio's documented error envelope is
``{code, message, more_info, status}``.
"""

import pytest


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "2010-04-01/Accounts/AC0123/UnknownResource.json"),
        ("POST", "2010-04-01/Accounts/AC0123/Messages-misspell.json"),
        ("DELETE", "2010-04-01/Accounts/AC0123/random/nested"),
        ("PUT", "2010-04-01/Accounts/AC0123/IncomingPhoneNumbers/wrong"),
        ("GET", "2010-04-01/Accounts/SomeOtherFormat"),
    ],
)
def test_unknown_account_path_returns_json_404(client, method, path):
    full = f"/{path}"
    resp = client.open(
        full,
        method=method,
        json={"foo": "bar"} if method in ("POST", "PUT", "PATCH") else None,
    )
    assert resp.status_code == 404, f"{method} {full} got {resp.status_code}"
    assert resp.headers["Content-Type"].startswith("application/json"), (
        f"{method} {full} returned {resp.headers.get('Content-Type')!r} "
        f"body={resp.get_data(as_text=True)[:200]!r}"
    )
    body = resp.get_json()
    assert body is not None
    # Twilio error shape: {code, message, more_info, status}.
    assert body["code"] == 20404
    assert body["status"] == 404
    assert "not found" in body["message"].lower()
    assert "more_info" in body


def test_unknown_account_path_no_html_leak(client):
    resp = client.get("/2010-04-01/Accounts/AC0123/literally-anything")
    body = resp.get_data(as_text=True)
    assert "<!doctype" not in body.lower()
