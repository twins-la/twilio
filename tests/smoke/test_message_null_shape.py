"""Regression tests for the Message-resource JSON wire shape.

Real Twilio emits ``error_code``, ``error_message``, ``price``, and
``messaging_service_sid`` as either a real value or JSON ``null``.
Empty strings are not part of the documented shape — SDKs that decode
``error_code`` to ``int | None`` raise on ``""``.

These tests pin the wire-shape contract at the HTTP layer (Flask test
client against the in-process app + SQLite storage) so any future drift
between create-response and list/get-response surfaces in CI rather than
in a consumer's deserializer.

The type-equality sweep (``test_create_and_read_responses_match_types``)
is the load-bearing assertion: it catches any newly-added nullable field
that quietly defaults to ``""`` in storage but ``None`` in the create path.
"""

NULLABLE_MESSAGE_FIELDS = (
    "error_code",
    "error_message",
    "price",
    "messaging_service_sid",
)

NULLABLE_PHONE_NUMBER_FIELDS = (
    "voice_application_sid",
    "sms_application_sid",
)


def _post_message(client, account, auth_headers):
    resp = client.post(
        f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
        headers=auth_headers,
        data={
            "To": "+15559876543",
            "From": "+15551234567",
            "Body": "null-shape regression",
        },
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _list_messages(client, account, auth_headers):
    resp = client.get(
        f"/2010-04-01/Accounts/{account['sid']}/Messages.json",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["messages"]


def _fetch_message(client, account, auth_headers, sid):
    resp = client.get(
        f"/2010-04-01/Accounts/{account['sid']}/Messages/{sid}.json",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


class TestMessageNullableFields:
    """Outbound create path: nullable fields must be JSON null on every read."""

    def test_post_emits_null_for_unset_nullable_fields(
        self, client, account, auth_headers
    ):
        body = _post_message(client, account, auth_headers)
        for field in NULLABLE_MESSAGE_FIELDS:
            assert body[field] is None, (
                f"POST response: {field}={body[field]!r} (expected None / JSON null)"
            )

    def test_list_emits_null_for_unset_nullable_fields(
        self, client, account, auth_headers
    ):
        created = _post_message(client, account, auth_headers)
        listed = _list_messages(client, account, auth_headers)
        match = next((m for m in listed if m["sid"] == created["sid"]), None)
        assert match is not None, "created SID missing from list response"
        for field in NULLABLE_MESSAGE_FIELDS:
            assert match[field] is None, (
                f"GET list: {field}={match[field]!r} (expected None / JSON null)"
            )

    def test_fetch_emits_null_for_unset_nullable_fields(
        self, client, account, auth_headers
    ):
        created = _post_message(client, account, auth_headers)
        fetched = _fetch_message(client, account, auth_headers, created["sid"])
        for field in NULLABLE_MESSAGE_FIELDS:
            assert fetched[field] is None, (
                f"GET fetch: {field}={fetched[field]!r} (expected None / JSON null)"
            )

    def test_create_and_read_responses_match_types(
        self, client, account, auth_headers
    ):
        """Sweep assertion — any nullable field on the create response must
        retain the same nullness on list and fetch.

        This is broader than the four fields named in the issue: it catches
        any newly-added field that the create path emits as None but the
        read path coerces to ``""`` (or vice versa).
        """
        created = _post_message(client, account, auth_headers)
        listed = _list_messages(client, account, auth_headers)
        listed_match = next((m for m in listed if m["sid"] == created["sid"]), None)
        assert listed_match is not None
        fetched = _fetch_message(client, account, auth_headers, created["sid"])

        # For every key the create response declares as None, list and fetch
        # must also be None. Symmetric: if list declares None, create must too.
        common_keys = set(created.keys()) & set(fetched.keys()) & set(listed_match.keys())
        for key in common_keys:
            type_create = type(created[key])
            type_list = type(listed_match[key])
            type_fetch = type(fetched[key])
            assert type_create is type_list is type_fetch, (
                f"Type drift for field {key!r}: "
                f"POST={type_create.__name__} ({created[key]!r}), "
                f"LIST={type_list.__name__} ({listed_match[key]!r}), "
                f"FETCH={type_fetch.__name__} ({fetched[key]!r})"
            )


class TestInboundSimulateNullableFields:
    """Inbound simulate path stores a message dict that omits the four
    nullable fields entirely. Pre-fix this caused list/get to emit ``""``
    while the simulate response itself emitted ``null``."""

    def _provision_number(self, client, account, auth_headers, number):
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": number},
        )
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)

    def test_simulate_inbound_response_emits_null(
        self, client, account, auth_headers, tenant_headers
    ):
        self._provision_number(client, account, auth_headers, "+15551234567")
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "account_sid": account["sid"],
                "from": "+15559876543",
                "to": "+15551234567",
                "body": "inbound null-shape",
            },
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        msg = resp.get_json()["message"]
        for field in NULLABLE_MESSAGE_FIELDS:
            assert msg[field] is None, (
                f"simulate/inbound: {field}={msg[field]!r} (expected None)"
            )

    def test_simulate_inbound_then_fetch_emits_null(
        self, client, account, auth_headers, tenant_headers
    ):
        self._provision_number(client, account, auth_headers, "+15551234567")
        resp = client.post(
            "/_twin/simulate/inbound",
            headers=tenant_headers,
            json={
                "account_sid": account["sid"],
                "from": "+15559876543",
                "to": "+15551234567",
                "body": "inbound null-shape via fetch",
            },
        )
        assert resp.status_code == 201
        sid = resp.get_json()["message"]["sid"]

        fetched = _fetch_message(client, account, auth_headers, sid)
        for field in NULLABLE_MESSAGE_FIELDS:
            assert fetched[field] is None, (
                f"GET fetch (inbound): {field}={fetched[field]!r} (expected None)"
            )


class TestPhoneNumberNullableFields:
    """Sibling sweep: real Twilio docs declare ``voice_application_sid`` and
    ``sms_application_sid`` as ``string | null``. The twin's
    IncomingPhoneNumber resource must match — empty string is wrong here too."""

    def test_create_phone_number_emits_null_for_unset_application_sids(
        self, client, account, auth_headers
    ):
        resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )
        assert resp.status_code == 201
        body = resp.get_json()
        for field in NULLABLE_PHONE_NUMBER_FIELDS:
            assert body[field] is None, (
                f"POST IncomingPhoneNumbers: {field}={body[field]!r} (expected None)"
            )

    def test_fetch_phone_number_emits_null_for_unset_application_sids(
        self, client, account, auth_headers
    ):
        create_resp = client.post(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers.json",
            headers=auth_headers,
            data={"PhoneNumber": "+15551234567"},
        )
        sid = create_resp.get_json()["sid"]
        fetch_resp = client.get(
            f"/2010-04-01/Accounts/{account['sid']}/IncomingPhoneNumbers/{sid}.json",
            headers=auth_headers,
        )
        assert fetch_resp.status_code == 200
        body = fetch_resp.get_json()
        for field in NULLABLE_PHONE_NUMBER_FIELDS:
            assert body[field] is None, (
                f"GET IncomingPhoneNumbers/{{sid}}: {field}={body[field]!r} (expected None)"
            )
