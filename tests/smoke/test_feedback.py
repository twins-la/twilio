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

    def test_submit_body_only(self, client, account, auth_headers):
        resp = client.post("/_twin/feedback",
            headers=auth_headers,
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
        assert data["account_sid"] == account["sid"]

    def test_submit_with_all_fields(self, client, account, auth_headers):
        resp = client.post("/_twin/feedback",
            headers=auth_headers,
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
        assert data["account_sid"] == account["sid"]

    def test_submit_missing_body_returns_400(self, client, auth_headers):
        resp = client.post("/_twin/feedback",
            headers=auth_headers,
            json={"category": "bug"},
        )
        assert resp.status_code == 400
        assert "body" in resp.get_json()["error"].lower()

    def test_submit_empty_body_returns_400(self, client, auth_headers):
        resp = client.post("/_twin/feedback",
            headers=auth_headers,
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

    def test_list_empty(self, client, auth_headers):
        resp = client.get("/_twin/feedback", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["feedback"] == []

    def test_list_returns_submitted(self, client, auth_headers):
        client.post("/_twin/feedback", headers=auth_headers, json={"body": "Feedback one"})
        client.post("/_twin/feedback", headers=auth_headers, json={"body": "Feedback two"})

        resp = client.get("/_twin/feedback", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.get_json()["feedback"]
        assert len(items) == 2

    def test_list_filter_by_status(self, client, auth_headers):
        r1 = client.post("/_twin/feedback", headers=auth_headers, json={"body": "Will be reviewed"})
        client.post("/_twin/feedback", headers=auth_headers, json={"body": "Still pending"})

        fb_id = r1.get_json()["id"]
        client.post(f"/_twin/feedback/{fb_id}", headers=auth_headers, json={"status": "reviewed"})

        resp = client.get("/_twin/feedback?status=pending", headers=auth_headers)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "Still pending"

        resp = client.get("/_twin/feedback?status=reviewed", headers=auth_headers)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "Will be reviewed"


class TestGetFeedback:
    """Test GET /_twin/feedback/<id>."""

    def test_fetch_existing(self, client, auth_headers):
        r = client.post("/_twin/feedback", headers=auth_headers, json={"body": "Test feedback"})
        fb_id = r.get_json()["id"]

        resp = client.get(f"/_twin/feedback/{fb_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["id"] == fb_id

    def test_fetch_nonexistent_returns_404(self, client, auth_headers):
        resp = client.get("/_twin/feedback/FB00000000000000000000000000000000", headers=auth_headers)
        assert resp.status_code == 404


class TestUpdateFeedback:
    """Test POST /_twin/feedback/<id> (update)."""

    def test_update_status(self, client, auth_headers):
        r = client.post("/_twin/feedback", headers=auth_headers, json={"body": "To review"})
        fb_id = r.get_json()["id"]

        resp = client.post(f"/_twin/feedback/{fb_id}", headers=auth_headers, json={"status": "reviewed"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "reviewed"

    def test_update_nonexistent_returns_404(self, client, auth_headers):
        resp = client.post(
            "/_twin/feedback/FB00000000000000000000000000000000",
            headers=auth_headers,
            json={"status": "reviewed"},
        )
        assert resp.status_code == 404

    def test_update_no_auth_returns_401(self, client, auth_headers):
        r = client.post("/_twin/feedback", headers=auth_headers, json={"body": "Test"})
        fb_id = r.get_json()["id"]
        resp = client.post(f"/_twin/feedback/{fb_id}", json={"status": "reviewed"})
        assert resp.status_code == 401


class TestFeedbackLogging:
    """Test that feedback operations are logged."""

    def test_submit_creates_log_entry(self, client, auth_headers):
        client.post("/_twin/feedback", headers=auth_headers, json={"body": "Log test"})
        resp = client.get("/_twin/logs", headers=auth_headers)
        logs = resp.get_json()["logs"]
        feedback_logs = [l for l in logs if l["entry"].get("operation") == "twin.feedback.submit"]
        assert len(feedback_logs) >= 1


class TestTenantIsolation:
    """Test that tenants cannot see each other's data."""

    def test_feedback_isolation(self, client):
        """Account A's feedback is not visible to Account B."""
        import base64

        # Create two accounts
        resp_a = client.post("/_twin/accounts", json={"friendly_name": "Account A"})
        acct_a = resp_a.get_json()
        headers_a = {"Authorization": f"Basic {base64.b64encode(f'{acct_a['sid']}:{acct_a['auth_token']}'.encode()).decode()}"}

        resp_b = client.post("/_twin/accounts", json={"friendly_name": "Account B"})
        acct_b = resp_b.get_json()
        headers_b = {"Authorization": f"Basic {base64.b64encode(f'{acct_b['sid']}:{acct_b['auth_token']}'.encode()).decode()}"}

        # A submits feedback
        client.post("/_twin/feedback", headers=headers_a, json={"body": "A's feedback"})

        # B submits feedback
        client.post("/_twin/feedback", headers=headers_b, json={"body": "B's feedback"})

        # A sees only their own
        resp = client.get("/_twin/feedback", headers=headers_a)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "A's feedback"

        # B sees only their own
        resp = client.get("/_twin/feedback", headers=headers_b)
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "B's feedback"

    def test_logs_isolation(self, client):
        """Account A's logs are not visible to Account B."""
        import base64

        resp_a = client.post("/_twin/accounts", json={"friendly_name": "Log A"})
        acct_a = resp_a.get_json()
        headers_a = {"Authorization": f"Basic {base64.b64encode(f'{acct_a['sid']}:{acct_a['auth_token']}'.encode()).decode()}"}

        resp_b = client.post("/_twin/accounts", json={"friendly_name": "Log B"})
        acct_b = resp_b.get_json()
        headers_b = {"Authorization": f"Basic {base64.b64encode(f'{acct_b['sid']}:{acct_b['auth_token']}'.encode()).decode()}"}

        # A creates some activity (feedback submission generates a log)
        client.post("/_twin/feedback", headers=headers_a, json={"body": "A activity"})

        # B's logs should not contain A's activity
        resp = client.get("/_twin/logs", headers=headers_b)
        logs = resp.get_json()["logs"]
        a_logs = [l for l in logs if l["entry"].get("account_sid") == acct_a["sid"]]
        assert len(a_logs) == 0

    def test_accounts_returns_only_own(self, client):
        """GET /_twin/accounts returns only the authenticated account."""
        import base64

        resp_a = client.post("/_twin/accounts", json={"friendly_name": "Own A"})
        acct_a = resp_a.get_json()
        headers_a = {"Authorization": f"Basic {base64.b64encode(f'{acct_a['sid']}:{acct_a['auth_token']}'.encode()).decode()}"}

        client.post("/_twin/accounts", json={"friendly_name": "Own B"})

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
        assert client.post("/_twin/api-keys", json={}).status_code == 401
        assert client.post("/_twin/simulate/inbound", json={}).status_code == 401

    def test_unauthenticated_public_endpoints_still_work(self, client):
        """Public Twin Plane endpoints remain accessible without auth."""
        assert client.get("/_twin/health").status_code == 200
        assert client.get("/_twin/scenarios").status_code == 200
        assert client.get("/_twin/settings").status_code == 200
        assert client.post("/_twin/accounts", json={}).status_code == 201
