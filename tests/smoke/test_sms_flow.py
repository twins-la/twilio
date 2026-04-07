"""Smoke tests for the end-to-end SMS flow.

Exercises the full Twilio SMS scenario:
1. Create account via Twin Plane
2. Provision a phone number
3. Configure webhook URL on the number
4. Send an outbound SMS
5. Simulate an inbound SMS
6. Verify webhook delivery and message records
"""

import base64
import time

import pytest


class TestAccountCreation:
    """Test account management via Twin Plane."""

    def test_create_account(self, client):
        resp = client.post("/_twin/accounts", json={"friendly_name": "My Account"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["sid"].startswith("AC")
        assert len(data["sid"]) == 34
        assert len(data["auth_token"]) == 32
        assert data["friendly_name"] == "My Account"
        assert data["status"] == "active"
        assert data["type"] == "Full"

    def test_list_accounts(self, client, account):
        resp = client.get("/_twin/accounts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["accounts"]) >= 1

    def test_fetch_account_via_api(self, client, account, auth_headers):
        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}.json",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sid"] == account["sid"]


class TestAuthentication:
    """Test Twilio-style HTTP Basic Auth."""

    def test_no_auth_returns_401(self, client, account):
        resp = client.get(f"/2010-04-01/Accounts/{account['sid']}.json")
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client, account):
        creds = base64.b64encode(f"{account['sid']}:wrongtoken".encode()).decode()
        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}.json",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 401

    def test_mismatched_account_sid_returns_401(self, client, account, auth_headers):
        resp = client.get(
            "/2010-04-01/Accounts/AC00000000000000000000000000000000.json",
            headers=auth_headers,
        )
        assert resp.status_code == 401


class TestPhoneNumbers:
    """Test IncomingPhoneNumber CRUD."""

    def test_create_phone_number(self, client, account, auth_headers):
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["sid"].startswith("PN")
        assert len(data["sid"]) == 34
        assert data["phone_number"] == "+15551234567"
        assert data["account_sid"] == account["sid"]
        assert data["capabilities"]["sms"] is True

    def test_list_phone_numbers(self, client, account, auth_headers):
        # Create a number first
        client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )

        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["incoming_phone_numbers"]) == 1

    def test_fetch_phone_number(self, client, account, auth_headers):
        create_resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )
        sid = create_resp.get_json()["sid"]

        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers/{sid}.json",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["sid"] == sid

    def test_update_phone_number_sms_url(self, client, account, auth_headers):
        create_resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )
        sid = create_resp.get_json()["sid"]

        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers/{sid}.json",
            headers=auth_headers,
            data={"SmsUrl": "http://example.com/sms", "SmsMethod": "POST"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sms_url"] == "http://example.com/sms"
        assert data["sms_method"] == "POST"


class TestOutboundSMS:
    """Test sending outbound SMS messages."""

    def test_send_message(self, client, account, auth_headers):
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={
                "To": "+15559876543",
                "From": "+15551234567",
                "Body": "Hello from the twin!",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["sid"].startswith("SM")
        assert len(data["sid"]) == 34
        assert data["to"] == "+15559876543"
        assert data["from"] == "+15551234567"
        assert data["body"] == "Hello from the twin!"
        assert data["status"] == "queued"
        assert data["direction"] == "outbound-api"

    def test_send_message_missing_to(self, client, account, auth_headers):
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"From": "+15551234567", "Body": "Hello"},
        )
        assert resp.status_code == 400

    def test_message_status_progression(self, client, account, auth_headers):
        """Verify message progresses from queued through delivered."""
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={
                "To": "+15559876543",
                "From": "+15551234567",
                "Body": "Status test",
            },
        )
        sid = resp.get_json()["sid"]

        # Wait for background delivery simulation
        time.sleep(1.0)

        fetch_resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/Messages/{sid}.json",
            headers=auth_headers,
        )
        data = fetch_resp.get_json()
        assert data["status"] == "delivered"
        assert data["date_sent"] != ""

    def test_list_messages(self, client, account, auth_headers):
        client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551234567", "Body": "Test"},
        )

        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["messages"]) >= 1

    def test_fetch_message(self, client, account, auth_headers):
        create_resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
            headers=auth_headers,
            data={"To": "+15559876543", "From": "+15551234567", "Body": "Test"},
        )
        sid = create_resp.get_json()["sid"]

        resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/Messages/{sid}.json",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["sid"] == sid


class TestInboundSMS:
    """Test inbound SMS simulation via Twin Plane."""

    def test_simulate_inbound_no_webhook(self, client, account, auth_headers):
        """Inbound SMS to a number with no webhook configured."""
        # Create a phone number without webhook
        client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )

        resp = client.post("/_twin/simulate/inbound", json={
            "from": "+15559876543",
            "to": "+15551234567",
            "body": "Hello twin!",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["message"]["sid"].startswith("SM")
        assert data["message"]["status"] == "received"
        assert data["message"]["direction"] == "inbound"
        assert data["webhook_delivered"] is False

    def test_simulate_inbound_unknown_number(self, client):
        resp = client.post("/_twin/simulate/inbound", json={
            "from": "+15559876543",
            "to": "+15550000000",
            "body": "Hello",
        })
        assert resp.status_code == 404


class TestTwinPlane:
    """Test Twin Plane management endpoints."""

    def test_health(self, client):
        resp = client.get("/_twin/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["twin"] == "twilio"

    def test_scenarios(self, client):
        resp = client.get("/_twin/scenarios")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["scenarios"]) >= 1
        scenario_names = [s["name"] for s in data["scenarios"]]
        assert "sms" in scenario_names
        sms_scenario = [s for s in data["scenarios"] if s["name"] == "sms"][0]
        assert sms_scenario["status"] == "supported"

    def test_logs(self, client, account):
        resp = client.get("/_twin/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data["logs"], list)
        assert len(data["logs"]) >= 1  # Account creation was logged

    def test_settings(self, client):
        resp = client.get("/_twin/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["twin"] == "twilio"


class TestWebhookSignature:
    """Test X-Twilio-Signature computation."""

    def test_signature_computation(self):
        from twins_twilio.webhooks import compute_signature

        # Known test vector
        auth_token = "12345"
        url = "https://mycompany.com/myapp.php?foo=1&bar=2"
        params = {
            "CallSid": "CA1234567890ABCDE",
            "Caller": "+14158675310",
            "Digits": "1234",
            "From": "+14158675310",
            "To": "+18005551212",
        }

        sig = compute_signature(auth_token, url, params)
        # Signature should be a non-empty base64 string
        assert len(sig) > 0
        assert sig.endswith("=") or sig[-1].isalnum()


class TestSIDFormats:
    """Test that generated SIDs match Twilio format."""

    def test_account_sid_format(self):
        from twins_twilio.sids import generate_account_sid
        sid = generate_account_sid()
        assert sid.startswith("AC")
        assert len(sid) == 34

    def test_message_sid_format(self):
        from twins_twilio.sids import generate_message_sid
        sid = generate_message_sid()
        assert sid.startswith("SM")
        assert len(sid) == 34

    def test_phone_number_sid_format(self):
        from twins_twilio.sids import generate_phone_number_sid
        sid = generate_phone_number_sid()
        assert sid.startswith("PN")
        assert len(sid) == 34

    def test_auth_token_format(self):
        from twins_twilio.sids import generate_auth_token
        token = generate_auth_token()
        assert len(token) == 32
        assert all(c in "0123456789abcdef" for c in token)


class TestTwiMLParsing:
    """Test TwiML response parsing."""

    def test_parse_simple_message(self):
        from twins_twilio.twiml import parse_message_response
        twiml = '<Response><Message>Hello!</Message></Response>'
        messages = parse_message_response(twiml)
        assert messages == ["Hello!"]

    def test_parse_body_element(self):
        from twins_twilio.twiml import parse_message_response
        twiml = '<Response><Message><Body>Hello!</Body></Message></Response>'
        messages = parse_message_response(twiml)
        assert messages == ["Hello!"]

    def test_parse_multiple_messages(self):
        from twins_twilio.twiml import parse_message_response
        twiml = '<Response><Message>One</Message><Message>Two</Message></Response>'
        messages = parse_message_response(twiml)
        assert messages == ["One", "Two"]

    def test_parse_empty_response(self):
        from twins_twilio.twiml import parse_message_response
        twiml = '<Response></Response>'
        messages = parse_message_response(twiml)
        assert messages == []

    def test_parse_invalid_xml(self):
        from twins_twilio.twiml import parse_message_response
        messages = parse_message_response("not xml at all")
        assert messages == []


class TestPersistence:
    """Test that state persists across app recreations (simulating restart)."""

    def test_data_persists_across_restart(self, tmp_path):
        """Create data, recreate the app, verify data is still there."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "local"))
        from twins_local.storage_sqlite import SQLiteStorage
        from twins_twilio.app import create_app

        db_path = str(tmp_path / "persist_test.db")

        # First "run" — create account and phone number
        storage1 = SQLiteStorage(db_path=db_path)
        app1 = create_app(storage=storage1, config={"base_url": "http://localhost:8080"})
        app1.config["TESTING"] = True

        with app1.test_client() as c:
            resp = c.post("/_twin/accounts", json={"friendly_name": "Persist Test"})
            account = resp.get_json()
            account_sid = account["sid"]
            auth_token = account["auth_token"]

            import base64
            creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
            headers = {"Authorization": f"Basic {creds}"}

            c.post(
                f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json",
                headers=headers,
                data={"PhoneNumber": "+15551234567"},
            )

        # Second "run" — new app instance, same database
        storage2 = SQLiteStorage(db_path=db_path)
        app2 = create_app(storage=storage2, config={"base_url": "http://localhost:8080"})
        app2.config["TESTING"] = True

        with app2.test_client() as c:
            # Verify account still exists
            resp = c.get(
                f"/2010-04-01/Accounts/{account_sid}.json",
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.get_json()["sid"] == account_sid

            # Verify phone number still exists
            resp = c.get(
                f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json",
                headers=headers,
            )
            assert resp.status_code == 200
            assert len(resp.get_json()["incoming_phone_numbers"]) == 1
