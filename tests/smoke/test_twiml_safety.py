"""TwiML parser must resist XML entity-expansion (billion-laughs) — TWTW-004.

The parser swaps stdlib ElementTree for defusedxml; a malicious webhook
response that declares expanding entities must be rejected (no expansion,
no hang), surfacing as an unparseable response rather than a 500/DoS.
"""

from twins_twilio.twiml import parse_message_response

BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE lolz [\n"
    '  <!ENTITY lol "lol">\n'
    '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
    '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
    "]>\n"
    "<Response><Message>&lol3;</Message></Response>"
)


def test_billion_laughs_is_rejected_not_expanded():
    # defusedxml forbids entity declarations → parse fails → empty result,
    # without expanding the entity tree.
    assert parse_message_response(BILLION_LAUGHS) == []


def test_well_formed_twiml_still_parses():
    twiml = "<Response><Message>Hello there</Message></Response>"
    assert parse_message_response(twiml) == ["Hello there"]


def test_body_subelement_form_still_parses():
    twiml = "<Response><Message><Body>Hi</Body></Message></Response>"
    assert parse_message_response(twiml) == ["Hi"]
