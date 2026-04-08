"""Smoke tests for the feedback API.

Exercises the feedback collection system:
1. Submit feedback via Twin Plane
2. List and filter feedback
3. Fetch individual feedback
4. Update feedback status
"""


class TestSubmitFeedback:
    """Test POST /_twin/feedback."""

    def test_submit_body_only(self, client):
        resp = client.post("/_twin/feedback", json={
            "body": "The SMS twin doesn't support MMS.",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"].startswith("FB")
        assert len(data["id"]) == 34
        assert data["body"] == "The SMS twin doesn't support MMS."
        assert data["status"] == "pending"
        assert data["category"] == ""
        assert data["context"] == {}
        assert data["account_sid"] == ""

    def test_submit_with_all_fields(self, client, account):
        resp = client.post("/_twin/feedback", json={
            "body": "Webhook delivery fails for HTTPS URLs with self-signed certs.",
            "category": "bug",
            "context": {
                "message_sid": "SM00000000000000000000000000000000",
                "error": "SSL certificate verify failed",
            },
            "account_sid": account["sid"],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["body"] == "Webhook delivery fails for HTTPS URLs with self-signed certs."
        assert data["category"] == "bug"
        assert data["context"]["message_sid"] == "SM00000000000000000000000000000000"
        assert data["context"]["error"] == "SSL certificate verify failed"
        assert data["account_sid"] == account["sid"]

    def test_submit_missing_body_returns_400(self, client):
        resp = client.post("/_twin/feedback", json={
            "category": "bug",
        })
        assert resp.status_code == 400
        assert "body" in resp.get_json()["error"].lower()

    def test_submit_empty_body_returns_400(self, client):
        resp = client.post("/_twin/feedback", json={
            "body": "   ",
        })
        assert resp.status_code == 400

    def test_submit_not_json_returns_400(self, client):
        resp = client.post("/_twin/feedback", data="not json")
        assert resp.status_code == 400


class TestListFeedback:
    """Test GET /_twin/feedback."""

    def test_list_empty(self, client):
        resp = client.get("/_twin/feedback")
        assert resp.status_code == 200
        assert resp.get_json()["feedback"] == []

    def test_list_returns_submitted(self, client):
        client.post("/_twin/feedback", json={"body": "Feedback one"})
        client.post("/_twin/feedback", json={"body": "Feedback two"})

        resp = client.get("/_twin/feedback")
        assert resp.status_code == 200
        items = resp.get_json()["feedback"]
        assert len(items) == 2

    def test_list_filter_by_status(self, client):
        # Submit two items
        r1 = client.post("/_twin/feedback", json={"body": "Will be reviewed"})
        client.post("/_twin/feedback", json={"body": "Still pending"})

        # Update one to reviewed
        fb_id = r1.get_json()["id"]
        client.post(f"/_twin/feedback/{fb_id}", json={"status": "reviewed"})

        # Filter by pending
        resp = client.get("/_twin/feedback?status=pending")
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "Still pending"

        # Filter by reviewed
        resp = client.get("/_twin/feedback?status=reviewed")
        items = resp.get_json()["feedback"]
        assert len(items) == 1
        assert items[0]["body"] == "Will be reviewed"


class TestGetFeedback:
    """Test GET /_twin/feedback/<id>."""

    def test_fetch_existing(self, client):
        r = client.post("/_twin/feedback", json={"body": "Test feedback"})
        fb_id = r.get_json()["id"]

        resp = client.get(f"/_twin/feedback/{fb_id}")
        assert resp.status_code == 200
        assert resp.get_json()["id"] == fb_id
        assert resp.get_json()["body"] == "Test feedback"

    def test_fetch_nonexistent_returns_404(self, client):
        resp = client.get("/_twin/feedback/FB00000000000000000000000000000000")
        assert resp.status_code == 404


class TestUpdateFeedback:
    """Test POST /_twin/feedback/<id> (update)."""

    def test_update_status(self, client):
        r = client.post("/_twin/feedback", json={"body": "To review"})
        fb_id = r.get_json()["id"]

        resp = client.post(f"/_twin/feedback/{fb_id}", json={"status": "reviewed"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "reviewed"

    def test_update_nonexistent_returns_404(self, client):
        resp = client.post(
            "/_twin/feedback/FB00000000000000000000000000000000",
            json={"status": "reviewed"},
        )
        assert resp.status_code == 404

    def test_update_not_json_returns_400(self, client):
        r = client.post("/_twin/feedback", json={"body": "Test"})
        fb_id = r.get_json()["id"]
        resp = client.post(f"/_twin/feedback/{fb_id}", data="not json")
        assert resp.status_code == 400


class TestFeedbackLogging:
    """Test that feedback operations are logged."""

    def test_submit_creates_log_entry(self, client):
        client.post("/_twin/feedback", json={"body": "Log test"})
        resp = client.get("/_twin/logs")
        logs = resp.get_json()["logs"]
        feedback_logs = [l for l in logs if l["entry"].get("operation") == "twin.feedback.submit"]
        assert len(feedback_logs) >= 1
