"""Smoke tests for the end-to-end email flow.

Exercises the SendGrid v3 Mail Send email scenario:
1. Create account via Twin Plane
2. Create API key via Twin Plane
3. Send an outbound email
4. Verify email storage and retrieval
5. Verify delivery status progression
6. Verify error handling
"""

import time

import pytest


class TestApiKeyCreation:
    """Test API key management via Twin Plane."""

    def test_create_api_key(self, client, account):
        resp = client.post("/_twin/api-keys", json={
            "account_sid": account["sid"],
            "name": "Test Key",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["api_key"].startswith("SG.")
        assert data["account_sid"] == account["sid"]
        assert data["name"] == "Test Key"
        # Key format: SG.{key_id}.{key_secret}
        parts = data["api_key"][3:].split(".", 1)
        assert len(parts) == 2
        assert len(parts[0]) > 0
        assert len(parts[1]) > 0

    def test_create_api_key_missing_account(self, client):
        resp = client.post("/_twin/api-keys", json={
            "account_sid": "AC00000000000000000000000000000000",
        })
        assert resp.status_code == 404

    def test_create_api_key_no_account_sid(self, client):
        resp = client.post("/_twin/api-keys", json={})
        assert resp.status_code == 400


@pytest.fixture
def api_key(client, account):
    """Create and return a test API key via Twin Plane."""
    resp = client.post("/_twin/api-keys", json={
        "account_sid": account["sid"],
        "name": "Test Key",
    })
    assert resp.status_code == 201
    return resp.get_json()


@pytest.fixture
def email_auth_headers(api_key):
    """Authorization headers for SendGrid-style API key auth."""
    return {"Authorization": f"Bearer {api_key['api_key']}"}


class TestEmailAuthentication:
    """Test SendGrid-style API key authentication."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/v3/mail/send", json={})
        assert resp.status_code == 401
        data = resp.get_json()
        assert "errors" in data
        assert data["errors"][0]["message"] == "authorization required"

    def test_invalid_key_returns_401(self, client):
        resp = client.post(
            "/v3/mail/send",
            json={},
            headers={"Authorization": "Bearer SG.invalid.key"},
        )
        assert resp.status_code == 401

    def test_non_sg_prefix_returns_401(self, client):
        resp = client.post(
            "/v3/mail/send",
            json={},
            headers={"Authorization": "Bearer notavalidkey"},
        )
        assert resp.status_code == 401

    def test_malformed_bearer_returns_401(self, client):
        resp = client.post(
            "/v3/mail/send",
            json={},
            headers={"Authorization": "Basic abc123"},
        )
        assert resp.status_code == 401


class TestEmailSending:
    """Test sending outbound email via SendGrid v3 Mail Send."""

    def test_send_email(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com", "name": "Recipient"}]}
                ],
                "from": {"email": "sender@example.com", "name": "Sender"},
                "subject": "Hello from the twin!",
                "content": [
                    {"type": "text/plain", "value": "This is a test email."}
                ],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 202
        assert resp.data == b""  # Empty body on success
        assert "X-Message-Id" in resp.headers
        assert len(resp.headers["X-Message-Id"]) == 22

    def test_send_email_html_content(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "HTML test",
                "content": [
                    {"type": "text/plain", "value": "Plain text"},
                    {"type": "text/html", "value": "<h1>HTML content</h1>"},
                ],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 202

    def test_send_email_multiple_personalizations(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {
                        "to": [{"email": "alice@example.com"}],
                        "subject": "Hello Alice",
                    },
                    {
                        "to": [{"email": "bob@example.com"}],
                        "subject": "Hello Bob",
                    },
                ],
                "from": {"email": "sender@example.com"},
                "content": [
                    {"type": "text/plain", "value": "Personalized email."}
                ],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 202

    def test_send_email_subject_in_personalizations(self, client, email_auth_headers):
        """Subject can be in personalizations instead of top level."""
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {
                        "to": [{"email": "recipient@example.com"}],
                        "subject": "Per-personalization subject",
                    }
                ],
                "from": {"email": "sender@example.com"},
                "content": [
                    {"type": "text/plain", "value": "Test."}
                ],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 202

    def test_send_email_with_cc_bcc(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {
                        "to": [{"email": "to@example.com"}],
                        "cc": [{"email": "cc@example.com"}],
                        "bcc": [{"email": "bcc@example.com"}],
                    }
                ],
                "from": {"email": "sender@example.com"},
                "subject": "CC/BCC test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 202


class TestEmailValidation:
    """Test SendGrid-format request validation and error responses."""

    def test_missing_personalizations(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "from": {"email": "sender@example.com"},
                "subject": "Test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "errors" in data
        assert data["errors"][0]["field"] == "personalizations"

    def test_missing_from(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "subject": "Test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["errors"][0]["field"] == "from"

    def test_missing_subject(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["errors"][0]["field"] == "subject"

    def test_missing_content_and_template(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "Test",
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["errors"][0]["field"] == "content"

    def test_template_id_substitutes_for_content(self, client, email_auth_headers):
        """template_id satisfies the content requirement."""
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "Test",
                "template_id": "d-abc123",
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 202

    def test_missing_to_in_personalization(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [{}],
                "from": {"email": "sender@example.com"},
                "subject": "Test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "personalizations" in data["errors"][0]["field"]

    def test_non_json_body(self, client, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            data="not json",
            headers=email_auth_headers,
        )
        assert resp.status_code == 400

    def test_sendgrid_error_format(self, client, email_auth_headers):
        """Verify error responses match SendGrid format."""
        resp = client.post(
            "/v3/mail/send",
            json={},
            headers=email_auth_headers,
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "errors" in data
        assert isinstance(data["errors"], list)
        assert "message" in data["errors"][0]
        assert "field" in data["errors"][0]


class TestEmailStatusProgression:
    """Test email delivery status simulation."""

    def test_email_progresses_to_delivered(self, client, account, email_auth_headers):
        resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "Status test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        message_id = resp.headers["X-Message-Id"]

        # Wait for background delivery simulation
        time.sleep(0.8)

        fetch_resp = client.get(f"/_twin/emails/{message_id}")
        assert fetch_resp.status_code == 200
        data = fetch_resp.get_json()
        assert data["status"] == "delivered"


class TestEmailRetrieval:
    """Test email retrieval via Twin Plane."""

    def test_list_emails(self, client, account, email_auth_headers):
        # Send an email first
        client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "List test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )

        resp = client.get(f"/_twin/emails?account_sid={account['sid']}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["emails"]) >= 1
        email = data["emails"][0]
        assert email["from"]["email"] == "sender@example.com"
        assert email["subject"] == "List test"

    def test_fetch_email(self, client, email_auth_headers):
        send_resp = client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "Fetch test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )
        message_id = send_resp.headers["X-Message-Id"]

        resp = client.get(f"/_twin/emails/{message_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["message_id"] == message_id
        assert data["subject"] == "Fetch test"
        assert data["personalizations"][0]["to"][0]["email"] == "recipient@example.com"

    def test_fetch_nonexistent_email(self, client):
        resp = client.get("/_twin/emails/nonexistent123")
        assert resp.status_code == 404

    def test_list_emails_all_accounts(self, client, account, email_auth_headers):
        """List emails without specifying account_sid."""
        client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "All accounts test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )

        resp = client.get("/_twin/emails")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["emails"]) >= 1


class TestEmailScenario:
    """Test that email scenario appears in Twin Plane."""

    def test_scenarios_includes_email(self, client):
        resp = client.get("/_twin/scenarios")
        assert resp.status_code == 200
        data = resp.get_json()
        scenario_names = [s["name"] for s in data["scenarios"]]
        assert "email" in scenario_names
        email_scenario = [s for s in data["scenarios"] if s["name"] == "email"][0]
        assert email_scenario["status"] == "supported"
        assert "outbound_email" in email_scenario["capabilities"]


class TestEmailLogging:
    """Test that email operations are logged."""

    def test_send_email_logged(self, client, account, email_auth_headers):
        client.post(
            "/v3/mail/send",
            json={
                "personalizations": [
                    {"to": [{"email": "recipient@example.com"}]}
                ],
                "from": {"email": "sender@example.com"},
                "subject": "Log test",
                "content": [{"type": "text/plain", "value": "Test."}],
            },
            headers=email_auth_headers,
        )

        resp = client.get("/_twin/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        operations = [log["entry"]["operation"] for log in data["logs"]]
        assert "email.send" in operations


class TestEmailSIDFormats:
    """Test SendGrid-format ID generation."""

    def test_api_key_format(self):
        from twins_twilio.sids import generate_api_key
        key_id, key_secret, full_key = generate_api_key()
        assert full_key.startswith("SG.")
        assert full_key == f"SG.{key_id}.{key_secret}"
        assert len(key_id) > 0
        assert len(key_secret) > 0

    def test_email_id_format(self):
        from twins_twilio.sids import generate_email_id
        email_id = generate_email_id()
        assert len(email_id) == 22
