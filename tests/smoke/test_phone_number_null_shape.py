"""Wire-shape and storage-shape coverage for IncomingPhoneNumber nullable
fields.

Closes twins-la/twilio#3 (serializer routes webhook URLs through
`_nullable_str`) and the phone-number half of twins-la/twilio#2 (storage
layer persists ``None`` for unset nullable fields rather than ``""``).
"""

import sqlite3

import pytest

from twins_twilio.models import phone_number_to_json


class TestPhoneNumberToJsonNullableFields:
    """Per Twilio docs the webhook URL fields are documented as
    `string | null`. The serializer must emit JSON `null`, not `""`,
    when no URL is set.
    """

    def test_unset_voice_url_emits_null(self):
        pn = {
            "sid": "PN0123",
            "account_sid": "AC0123",
            "phone_number": "+15551234567",
        }
        out = phone_number_to_json(pn, "http://localhost")
        assert out["voice_url"] is None
        assert out["voice_fallback_url"] is None
        assert out["sms_url"] is None
        assert out["sms_fallback_url"] is None
        assert out["status_callback"] is None

    def test_empty_string_voice_url_emits_null(self):
        """Storage may still hand back '' for legacy rows; serializer
        normalises to None either way (defense-in-depth)."""
        pn = {
            "sid": "PN0123",
            "account_sid": "AC0123",
            "phone_number": "+15551234567",
            "voice_url": "",
            "sms_url": "",
            "status_callback": "",
        }
        out = phone_number_to_json(pn, "http://localhost")
        assert out["voice_url"] is None
        assert out["sms_url"] is None
        assert out["status_callback"] is None

    def test_set_voice_url_passthrough(self):
        pn = {
            "sid": "PN0123",
            "account_sid": "AC0123",
            "phone_number": "+15551234567",
            "voice_url": "https://example.com/voice",
            "sms_url": "https://example.com/sms",
            "status_callback": "https://example.com/cb",
        }
        out = phone_number_to_json(pn, "http://localhost")
        assert out["voice_url"] == "https://example.com/voice"
        assert out["sms_url"] == "https://example.com/sms"
        assert out["status_callback"] == "https://example.com/cb"

    def test_method_fields_remain_non_nullable(self):
        """voice_method / sms_method / etc. are documented `string`
        (always present), not nullable."""
        pn = {
            "sid": "PN0123",
            "account_sid": "AC0123",
            "phone_number": "+15551234567",
        }
        out = phone_number_to_json(pn, "http://localhost")
        assert out["voice_method"] == "POST"
        assert out["sms_method"] == "POST"
        assert out["status_callback_method"] == "POST"


class TestStoragePersistsNullForUnsetNullableFields:
    """Defense-in-depth: any caller that bypasses the serializer (admin
    export, debug endpoint, future resource) must see ``None`` for unset
    nullable fields, not ``""``. Closes the storage-layer half of
    twins-la/twilio#2.
    """

    @pytest.fixture
    def storage(self, tmp_path):
        from twins_twilio_local.storage_sqlite import SQLiteStorage
        return SQLiteStorage(db_path=str(tmp_path / "twin.db"))

    @pytest.fixture
    def account(self, storage):
        from twins_twilio.models import now_rfc2822
        return storage.create_account(
            tenant_id="t-1",
            sid="AC0123",
            auth_token="tok",
            friendly_name="t1",
        )

    def test_phone_number_unset_urls_persist_as_none(self, storage, account):
        from twins_twilio.models import now_rfc2822
        now = now_rfc2822()
        pn = storage.create_phone_number({
            "sid": "PN0001",
            "tenant_id": "t-1",
            "account_sid": account["sid"],
            "phone_number": "+15551234567",
            "date_created": now,
            "date_updated": now,
            # no URL fields supplied
        })
        # The dict returned by create_phone_number reflects what was stored.
        for key in (
            "voice_url", "voice_fallback_url",
            "sms_url", "sms_fallback_url",
            "status_callback",
            "voice_application_sid", "sms_application_sid",
        ):
            assert pn[key] is None, f"{key} must be None, got {pn[key]!r}"

    def test_message_unset_nullable_fields_persist_as_none(self, storage, account):
        from twins_twilio.models import now_rfc2822
        now = now_rfc2822()
        msg = storage.create_message({
            "sid": "SM0001",
            "tenant_id": "t-1",
            "account_sid": account["sid"],
            "to": "+15551234567",
            "from_number": "+15557654321",
            "body": "hi",
            "status": "queued",
            "direction": "outbound-api",
            "date_created": now,
            "date_updated": now,
            # no price/error/messaging_service_sid
        })
        for key in ("price", "error_code", "error_message", "messaging_service_sid"):
            assert msg[key] is None, f"{key} must be None, got {msg[key]!r}"
