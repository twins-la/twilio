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
import os
import sys

import pytest

from twins_twilio.app import create_app

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from twins_twilio_local.storage_sqlite import SQLiteStorage
from twins_local.tenants import (
    SQLiteTenantStore,
    ensure_default_tenant,
    generate_tenant_id,
    generate_tenant_secret,
    hash_secret,
)


ADMIN_TOKEN = "test-admin-secret-token"


@pytest.fixture
def admin_tenant_store(tmp_path):
    store = SQLiteTenantStore(db_path=str(tmp_path / "admin_tenants.sqlite3"))
    ensure_default_tenant(store)
    return store


@pytest.fixture
def admin_app(tmp_path, admin_tenant_store):
    """Twin app with an admin token configured."""
    db_path = str(tmp_path / "admin_test.db")
    storage = SQLiteStorage(db_path=db_path)
    app = create_app(
        storage=storage,
        tenants=admin_tenant_store,
        config={
            "base_url": "http://localhost:8080",
            "admin_token": ADMIN_TOKEN,
        },
    )
    app.config["TESTING"] = True
    return app


@pytest.fixture
def admin_client(admin_app):
    return admin_app.test_client()


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _make_tenant(store, name):
    tid = generate_tenant_id()
    secret = generate_tenant_secret()
    store.create_tenant(tid, hash_secret(secret), name)
    creds = base64.b64encode(f"{tid}:{secret}".encode()).decode()
    return tid, {"Authorization": f"Basic {creds}"}


@pytest.fixture
def two_tenants(admin_client, admin_tenant_store):
    """Create two tenants, each with one account, and return details + headers."""
    tid_a, headers_a = _make_tenant(admin_tenant_store, "Tenant A")
    tid_b, headers_b = _make_tenant(admin_tenant_store, "Tenant B")

    resp_a = admin_client.post(
        "/_twin/accounts", headers=headers_a, json={"friendly_name": "Account A"}
    )
    acct_a = resp_a.get_json()

    resp_b = admin_client.post(
        "/_twin/accounts", headers=headers_b, json={"friendly_name": "Account B"}
    )
    acct_b = resp_b.get_json()

    return {
        "tid_a": tid_a, "a": acct_a, "headers_a": headers_a,
        "tid_b": tid_b, "b": acct_b, "headers_b": headers_b,
    }


class TestAdminAccountAccess:
    """Test admin access to accounts across tenants."""

    def test_admin_lists_all_accounts(self, admin_client, admin_headers, two_tenants):
        resp = admin_client.get("/_twin/accounts", headers=admin_headers)
        assert resp.status_code == 200
        accounts = resp.get_json()["accounts"]
        assert len(accounts) == 2
        sids = {a["sid"] for a in accounts}
        assert two_tenants["a"]["sid"] in sids
        assert two_tenants["b"]["sid"] in sids

    def test_admin_list_omits_auth_tokens(self, admin_client, admin_headers, two_tenants):
        resp = admin_client.get("/_twin/accounts", headers=admin_headers)
        accounts = resp.get_json()["accounts"]
        for account in accounts:
            assert "auth_token" not in account

    def test_tenant_sees_only_own_accounts(self, admin_client, two_tenants):
        resp = admin_client.get("/_twin/accounts", headers=two_tenants["headers_a"])
        assert resp.status_code == 200
        accounts = resp.get_json()["accounts"]
        assert len(accounts) == 1
        assert accounts[0]["sid"] == two_tenants["a"]["sid"]
        # Tenant sees their account's auth_token
        assert "auth_token" in accounts[0]


class TestAdminFeedbackAccess:
    """Test admin access to feedback across tenants."""

    def test_admin_lists_all_feedback(self, admin_client, admin_headers, two_tenants):
        admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_a"],
            json={"body": "Feedback from A"},
        )
        admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_b"],
            json={"body": "Feedback from B"},
        )

        resp = admin_client.get("/_twin/feedback", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.get_json()["feedback"]
        assert len(items) == 2
        bodies = {f["body"] for f in items}
        assert "Feedback from A" in bodies
        assert "Feedback from B" in bodies

    def test_admin_reads_any_feedback(self, admin_client, admin_headers, two_tenants):
        r = admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_a"],
            json={"body": "A's private feedback"},
        )
        fb_id = r.get_json()["id"]

        resp = admin_client.get(f"/_twin/feedback/{fb_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.get_json()["body"] == "A's private feedback"

    def test_admin_updates_any_feedback(self, admin_client, admin_headers, two_tenants):
        r = admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_a"],
            json={"body": "Needs review"},
        )
        fb_id = r.get_json()["id"]

        resp = admin_client.post(
            f"/_twin/feedback/{fb_id}",
            headers=admin_headers,
            json={"status": "reviewed"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "reviewed"

    def test_tenant_cannot_see_others_feedback(self, admin_client, two_tenants):
        r = admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_a"],
            json={"body": "A only"},
        )
        fb_id = r.get_json()["id"]

        resp = admin_client.get(
            f"/_twin/feedback/{fb_id}", headers=two_tenants["headers_b"]
        )
        assert resp.status_code == 404


class TestAdminLogAccess:
    """Test admin access to logs across tenants."""

    def test_admin_sees_all_logs(self, admin_client, admin_headers, two_tenants):
        admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_a"],
            json={"body": "A log activity"},
        )
        admin_client.post(
            "/_twin/feedback",
            headers=two_tenants["headers_b"],
            json={"body": "B log activity"},
        )

        resp = admin_client.get("/_twin/logs", headers=admin_headers)
        assert resp.status_code == 200
        logs = resp.get_json()["logs"]
        tenant_ids = {l.get("tenant_id") for l in logs}
        assert two_tenants["tid_a"] in tenant_ids
        assert two_tenants["tid_b"] in tenant_ids


class TestAdminEmailAccess:
    """Test admin access to emails."""

    def test_admin_sees_all_emails(self, admin_client, admin_headers, two_tenants):
        resp = admin_client.get("/_twin/emails", headers=admin_headers)
        assert resp.status_code == 200
        assert "emails" in resp.get_json()


class TestAdminAuthEnforcement:
    """Test admin auth validation."""

    def test_wrong_admin_token_returns_401(self, admin_client):
        resp = admin_client.get(
            "/_twin/accounts", headers={"Authorization": "Bearer wrong-token"}
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
        # POST /_twin/tenants is unauthenticated bootstrap
        assert admin_client.post("/_twin/tenants", json={}).status_code == 201


class TestNoAdminTokenConfigured:
    """Test behavior when TWIN_ADMIN_TOKEN is not set (local dev mode)."""

    def test_any_bearer_token_accepted(self, client):
        """With no admin token configured, any Bearer token works as admin."""
        resp = client.get(
            "/_twin/accounts", headers={"Authorization": "Bearer anything"}
        )
        assert resp.status_code == 200

    def test_tenant_auth_still_works(self, client, account, tenant_headers):
        """Tenant auth works regardless of admin token config."""
        resp = client.get("/_twin/accounts", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.get_json()["accounts"][0]["sid"] == account["sid"]
