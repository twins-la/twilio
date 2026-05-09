"""Closes twins-la/twilio#4 — `POST /_twin/simulate/inbound` accepts either
lowercase (Twin Plane convention) or CamelCase (Twilio outgoing-webhook
shape) keys.
"""

import pytest


@pytest.fixture
def provisioned_number(client, tenant_headers):
    """Create an account + provision a phone number on it. Returns the
    (account_sid, phone_number) tuple ready for inbound simulation."""
    resp = client.post(
        "/_twin/accounts",
        headers=tenant_headers,
        json={"friendly_name": "test-account"},
    )
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
    account = resp.get_json()
    account_sid = account["sid"]

    auth = (account_sid, account["auth_token"])
    resp = client.post(
        f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json",
        data={"PhoneNumber": "+15555550100"},
        auth=auth,
    )
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
    return account_sid, "+15555550100"


class TestSimulateInboundCamelCase:
    def test_accepts_lowercase_keys(self, client, tenant_headers, provisioned_number):
        account_sid, to_number = provisioned_number
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "account_sid": account_sid,
                "from": "+15555550199",
                "to": to_number,
                "body": "hello (lowercase)",
            },
        )
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)

    def test_accepts_camel_case_keys(self, client, tenant_headers, provisioned_number):
        account_sid, to_number = provisioned_number
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "AccountSid": account_sid,
                "From": "+15555550199",
                "To": to_number,
                "Body": "hello (CamelCase)",
            },
        )
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)

    def test_lowercase_wins_on_conflict(self, client, tenant_headers, provisioned_number):
        """When both forms are supplied, lowercase (canonical Twin Plane)
        takes precedence — the body / from / to / account_sid recorded
        on the inbound message reflect the lowercase values."""
        account_sid, to_number = provisioned_number
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "account_sid": account_sid,
                "AccountSid": "AC_BAD",
                "from": "+15555550199",
                "From": "+15500000000",
                "to": to_number,
                "To": "+15511111111",
                "body": "lowercase wins",
                "Body": "CamelCase loses",
            },
        )
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)
        body = resp.get_json()
        msg = body["message"]
        assert msg["body"] == "lowercase wins"
        assert msg["from"] == "+15555550199"
        assert msg["to"] == to_number
        assert msg["account_sid"] == account_sid
