"""Smoke tests for the feedback API.

Exercises the feedback collection system:
1. Submit feedback via Twin Plane (requires auth)
2. List and filter feedback (scoped to account)
3. Fetch individual feedback
4. Update feedback status
5. Verify tenant isolation
"""


class TestSubmitFeedback:
    """Test POST /_twin/feedback."""

    def test_submit_body_only(self, client, tenant, tenant_headers):
        resp = client.post("/_twin/feedback",
            headers=tenant_headers,
            json={"body": "The SMS twin doesn't support MMS."},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"].startswith("FB")
        assert len(data["id"]) == 34
        assert data["body"] == "The SMS twin doesn't support MMS."
        assert data["status"] == "pending"
        assert data["category"] == ""
        assert data["context"] == {}
        assert data["tenant_id"] == tenant["tenant_id"]

    def test_submit_with_all_fields(self, client, tenant, tenant_headers):
        resp = client.post("/_twin/feedback",
            headers=tenant_headers,
            json={
                "body": "Webhook delivery fails for HTTPS URLs with self-signed certs.",
                "category": "bug",
                "context": {
                    "message_sid": "SM00000000000000000000000000000000",
                    "error": "SSL certificate verify failed",
                },
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["body"] == "Webhook delivery fails for HTTPS URLs with self-signed certs."
        assert data["category"] == "bug"
        assert data["context"]["message_sid"] == "SM00000000000000000000000000000000"
        assert data["tenant_id"] == tenant["tenant_id"]

    def test_submit_missing_body_returns_400(self, client, auth_headers, tenant_headers):
        resp = client.post("/_twin/feedback",
            headers=tenant_headers,
            json={"category": "bug"},
        )
        assert resp.status_code == 400
        assert "body" in resp.get_json()["error"].lower()

    def test_submit_empty_body_returns_400(self, client, auth_headers, tenant_headers):
        resp = client.post("/_twin/feedback",
            headers=tenant_headers,
            json={"body": "   "},
        )
        assert resp.status_code == 400

    def test_submit_no_auth_returns_401(self, client):
        resp = client.post("/_twin/feedback",
            json={"body": "Should fail"},
        )
        assert resp.status_code == 401


class TestListFeedback:
    """Test GET /_twin/feedback."""

    def test_list_empty(self, client, auth_headers, tenant_headers):
        resp = client.get("/_twin/feedback", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.get_json()["feedback"] == []

    def test_list_returns_submitted(self, client, auth_headers, tenant_headers):
        client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Feedback one"})
        client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Feedback two"})

        resp = client.get("/_twin/feedback", headers=tenant_headers)
        assert resp.status_code == 200
        items = resp.get_json()["feedback"]
        assert len(items) == 2

    def test_list_filter_by_status(self, client, auth_headers, tenant_headers):
        r1 = client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Will be reviewed"})
        client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Still pending"})

        fb_id = r1.get_json()["id"]
        client.post(f"/_twin/feedback/{fb_id}", headers=tenant_headers, json={"status": "reviewed"})

        resp = client.get("/_twin/feedback?status=pending", headers=tenant_headers)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "Still pending"

        resp = client.get("/_twin/feedback?status=reviewed", headers=tenant_headers)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "Will be reviewed"


class TestGetFeedback:
    """Test GET /_twin/feedback/<id>."""

    def test_fetch_existing(self, client, auth_headers, tenant_headers):
        r = client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Test feedback"})
        fb_id = r.get_json()["id"]

        resp = client.get(f"/_twin/feedback/{fb_id}", headers=tenant_headers)
        assert resp.status_code == 200
        assert resp.get_json()["id"] == fb_id

    def test_fetch_nonexistent_returns_404(self, client, auth_headers, tenant_headers):
        resp = client.get("/_twin/feedback/FB00000000000000000000000000000000", headers=tenant_headers)
        assert resp.status_code == 404


class TestUpdateFeedback:
    """Test POST /_twin/feedback/<id> (update)."""

    def test_update_status(self, client, auth_headers, tenant_headers):
        r = client.post("/_twin/feedback", headers=tenant_headers, json={"body": "To review"})
        fb_id = r.get_json()["id"]

        resp = client.post(f"/_twin/feedback/{fb_id}", headers=tenant_headers, json={"status": "reviewed"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "reviewed"

    def test_update_nonexistent_returns_404(self, client, tenant_headers):
        resp = client.post(
            "/_twin/feedback/FB00000000000000000000000000000000",
            headers=tenant_headers,
            json={"status": "reviewed"},
        )
        assert resp.status_code == 404

    def test_update_no_auth_returns_401(self, client, auth_headers, tenant_headers):
        r = client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Test"})
        fb_id = r.get_json()["id"]
        resp = client.post(f"/_twin/feedback/{fb_id}", json={"status": "reviewed"})
        assert resp.status_code == 401


class TestFeedbackLogging:
    """Test that feedback operations are logged."""

    def test_submit_creates_log_entry(self, client, auth_headers, tenant_headers):
        client.post("/_twin/feedback", headers=tenant_headers, json={"body": "Log test"})
        resp = client.get("/_twin/logs", headers=tenant_headers)
        logs = resp.get_json()["logs"]
        feedback_logs = [l for l in logs if l.get("operation") == "twin.feedback.submit"]
        assert len(feedback_logs) >= 1


class TestTenantIsolation:
    """Test that tenants cannot see each other's data."""

    def _make_tenant(self, tenant_store, name):
        import base64
        from twins_local.tenants import (
            generate_tenant_id, generate_tenant_secret, hash_secret,
        )
        tid = generate_tenant_id()
        secret = generate_tenant_secret()
        tenant_store.create_tenant(tid, hash_secret(secret), name)
        creds = base64.b64encode(f"{tid}:{secret}".encode()).decode()
        return tid, {"Authorization": f"Basic {creds}"}

    def test_feedback_isolation(self, client, tenant_store):
        """Tenant A's feedback is not visible to tenant B."""
        tid_a, headers_a = self._make_tenant(tenant_store, "Tenant A")
        tid_b, headers_b = self._make_tenant(tenant_store, "Tenant B")

        client.post("/_twin/feedback", headers=headers_a, json={"body": "A's feedback"})
        client.post("/_twin/feedback", headers=headers_b, json={"body": "B's feedback"})

        resp = client.get("/_twin/feedback", headers=headers_a)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "A's feedback"

        resp = client.get("/_twin/feedback", headers=headers_b)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "B's feedback"

    def test_logs_isolation(self, client, tenant_store):
        """Tenant A's logs are not visible to tenant B."""
        tid_a, headers_a = self._make_tenant(tenant_store, "Log A")
        tid_b, headers_b = self._make_tenant(tenant_store, "Log B")

        client.post("/_twin/feedback", headers=headers_a, json={"body": "A activity"})

        resp = client.get("/_twin/logs", headers=headers_b)
        logs = resp.get_json()["logs"]
        a_logs = [l for l in logs if l.get("tenant_id") == tid_a]
        assert len(a_logs) == 0

    def test_accounts_returns_only_own(self, client, tenant_store):
        """GET /_twin/accounts returns only the tenant's accounts."""
        tid_a, headers_a = self._make_tenant(tenant_store, "Own A")
        tid_b, headers_b = self._make_tenant(tenant_store, "Own B")

        resp_a = client.post("/_twin/accounts", headers=headers_a, json={"friendly_name": "Own A's acct"})
        acct_a = resp_a.get_json()
        client.post("/_twin/accounts", headers=headers_b, json={"friendly_name": "Own B's acct"})

        resp = client.get("/_twin/accounts", headers=headers_a)
        data = resp.get_json()
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["sid"] == acct_a["sid"]

    def test_unauthenticated_protected_endpoints_return_401(self, client):
        """Protected Twin Plane endpoints return 401 without auth."""
        assert client.get("/_twin/accounts").status_code == 401
        assert client.get("/_twin/logs").status_code == 401
        assert client.get("/_twin/emails").status_code == 401
        assert client.get("/_twin/feedback").status_code == 401
        assert client.post("/_twin/api-keys", json={"name": "x"}).status_code == 401
        assert client.post("/_twin/simulate/inbound", json={}).status_code == 401

    def test_unauthenticated_public_endpoints_still_work(self, client, tenant_headers):
        """Public Twin Plane endpoints remain accessible without auth."""
        assert client.get("/_twin/health").status_code == 200
        assert client.get("/_twin/scenarios").status_code == 200
        assert client.get("/_twin/settings").status_code == 200
        # POST /_twin/tenants is unauthenticated bootstrap
        assert client.post("/_twin/tenants", json={}).status_code == 201
