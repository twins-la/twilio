"""Smoke tests for admin authentication and service-wide access.

Exercises the admin auth model:
1. Admin Bearer token grants cross-tenant access
2. Admin list accounts omits auth_tokens
3. Admin can read/update any feedback
4. Admin can see all logs and emails
5. Wrong admin token returns 401
6. No admin token configured = unrestricted admin access
"""

import base64

import pytest

from twins_twilio.app import create_app

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from twins_twilio_local.storage_sqlite import SQLiteStorage


ADMIN_TOKEN = "test-admin-secret-token"


@pytest.fixture
def admin_app(tmp_path):
    """Create a twin app with admin token configured."""
    db_path = str(tmp_path / "admin_test.db")
    storage = SQLiteStorage(db_path=db_path)
    app = create_app(storage=storage, config={
        "base_url": "http://localhost:8080",
        "admin_token": ADMIN_TOKEN,
    })
    app.config["TESTING"] = True
    return app


@pytest.fixture
def admin_client(admin_app):
    return admin_app.test_client()


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def two_accounts(admin_client):
    """Create two accounts and return their details + auth headers."""
    resp_a = admin_client.post("/_twin/accounts", json={"friendly_name": "Account A"})
    acct_a = resp_a.get_json()
    headers_a = {"Authorization": f"Basic {base64.b64encode(f'{acct_a['sid']}:{acct_a['auth_token']}'.encode()).decode()}"}

    resp_b = admin_client.post("/_twin/accounts", json={"friendly_name": "Account B"})
    acct_b = resp_b.get_json()
    headers_b = {"Authorization": f"Basic {base64.b64encode(f'{acct_b['sid']}:{acct_b['auth_token']}'.encode()).decode()}"}

    return {
        "a": acct_a, "headers_a": headers_a,
        "b": acct_b, "headers_b": headers_b,
    }


class TestAdminAccountAccess:
    """Test admin access to accounts."""

    def test_admin_lists_all_accounts(self, admin_client, admin_headers, two_accounts):
        resp = admin_client.get("/_twin/accounts", headers=admin_headers)
        assert resp.status_code == 200
        accounts = resp.get_json()["accounts"]
        assert len(accounts) == 2
        sids = {a["sid"] for a in accounts}
        assert two_accounts["a"]["sid"] in sids
        assert two_accounts["b"]["sid"] in sids

    def test_admin_list_omits_auth_tokens(self, admin_client, admin_headers, two_accounts):
        resp = admin_client.get("/_twin/accounts", headers=admin_headers)
        accounts = resp.get_json()["accounts"]
        for account in accounts:
            assert "auth_token" not in account

    def test_tenant_still_sees_own_account_only(self, admin_client, two_accounts):
        resp = admin_client.get("/_twin/accounts", headers=two_accounts["headers_a"])
        assert resp.status_code == 200
        accounts = resp.get_json()["accounts"]
        assert len(accounts) == 1
        assert accounts[0]["sid"] == two_accounts["a"]["sid"]
        # Tenant sees their own auth_token
        assert "auth_token" in accounts[0]


class TestAdminFeedbackAccess:
    """Test admin access to feedback."""

    def test_admin_lists_all_feedback(self, admin_client, admin_headers, two_accounts):
        # Each account submits feedback
        admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_a"],
            json={"body": "Feedback from A"},
        )
        admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_b"],
            json={"body": "Feedback from B"},
        )

        # Admin sees both
        resp = admin_client.get("/_twin/feedback", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.get_json()["feedback"]
        assert len(items) == 2
        bodies = {f["body"] for f in items}
        assert "Feedback from A" in bodies
        assert "Feedback from B" in bodies

    def test_admin_reads_any_feedback(self, admin_client, admin_headers, two_accounts):
        r = admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_a"],
            json={"body": "A's private feedback"},
        )
        fb_id = r.get_json()["id"]

        # Admin can read it
        resp = admin_client.get(f"/_twin/feedback/{fb_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.get_json()["body"] == "A's private feedback"

    def test_admin_updates_any_feedback(self, admin_client, admin_headers, two_accounts):
        r = admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_a"],
            json={"body": "Needs review"},
        )
        fb_id = r.get_json()["id"]

        # Admin marks as reviewed
        resp = admin_client.post(f"/_twin/feedback/{fb_id}",
            headers=admin_headers,
            json={"status": "reviewed"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "reviewed"

    def test_tenant_cannot_see_others_feedback(self, admin_client, two_accounts):
        r = admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_a"],
            json={"body": "A only"},
        )
        fb_id = r.get_json()["id"]

        # B cannot see A's feedback
        resp = admin_client.get(f"/_twin/feedback/{fb_id}", headers=two_accounts["headers_b"])
        assert resp.status_code == 404


class TestAdminLogAccess:
    """Test admin access to logs."""

    def test_admin_sees_all_logs(self, admin_client, admin_headers, two_accounts):
        # Both accounts generate activity
        admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_a"],
            json={"body": "A log activity"},
        )
        admin_client.post("/_twin/feedback",
            headers=two_accounts["headers_b"],
            json={"body": "B log activity"},
        )

        resp = admin_client.get("/_twin/logs", headers=admin_headers)
        assert resp.status_code == 200
        logs = resp.get_json()["logs"]
        account_sids = {l["entry"].get("account_sid") for l in logs}
        assert two_accounts["a"]["sid"] in account_sids
        assert two_accounts["b"]["sid"] in account_sids


class TestAdminEmailAccess:
    """Test admin access to emails."""

    def test_admin_sees_all_emails(self, admin_client, admin_headers, two_accounts):
        # We can't easily send emails without the full SendGrid flow,
        # but we can verify the endpoint accepts admin auth
        resp = admin_client.get("/_twin/emails", headers=admin_headers)
        assert resp.status_code == 200
        assert "emails" in resp.get_json()


class TestAdminAuthEnforcement:
    """Test admin auth validation."""

    def test_wrong_admin_token_returns_401(self, admin_client):
        resp = admin_client.get("/_twin/accounts",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_no_auth_returns_401(self, admin_client):
        resp = admin_client.get("/_twin/accounts")
        assert resp.status_code == 401

    def test_public_endpoints_still_public(self, admin_client):
        assert admin_client.get("/_twin/health").status_code == 200
        assert admin_client.get("/_twin/scenarios").status_code == 200
        assert admin_client.get("/_twin/settings").status_code == 200
        assert admin_client.get("/_twin/agent-instructions").status_code == 200
        assert admin_client.get("/").status_code == 200
        assert admin_client.post("/_twin/accounts", json={}).status_code == 201


class TestNoAdminTokenConfigured:
    """Test behavior when TWIN_ADMIN_TOKEN is not set (local dev mode)."""

    def test_any_bearer_token_accepted(self, client):
        """With no admin token configured, any Bearer token works as admin."""
        # client fixture has no admin_token configured
        resp = client.get("/_twin/accounts",
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 200

    def test_tenant_auth_still_works(self, client, account, auth_headers):
        """Tenant auth works regardless of admin token config."""
        resp = client.get("/_twin/accounts", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["accounts"][0]["sid"] == account["sid"]
