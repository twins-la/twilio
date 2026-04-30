"""Carrier-keyword detection for inbound SMS bodies.

Real Twilio's Advanced Opt-Out feature recognizes specific keywords as
opt-out (STOP family), opt-in (START family), or info (HELP family)
requests. The carrier filters or auto-handles these regardless of whether
they reach the consumer's webhook; the twin matches that semantic by
detecting them and applying opt-out state, while still delivering the
inbound webhook for visibility.

Matching is *exact-token* (case-insensitive, after trimming and stripping
trailing punctuation). "STOP" matches; "stop please" does not. This
matches Twilio's documented behavior — the keyword must be the entire
message content for the carrier to act on it.
"""

import re

# Real Twilio default keyword sets (Advanced Opt-Out).
_STOP_KEYWORDS = frozenset({"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"})
_START_KEYWORDS = frozenset({"START", "YES", "UNSTOP"})
_HELP_KEYWORDS = frozenset({"HELP", "INFO"})

# Canned auto-reply Twilio carriers send for HELP. The exact text varies
# by carrier; this is a representative twin response and is *not*
# operator-configurable in this version.
HELP_AUTO_REPLY = (
    "Reply STOP to unsubscribe. Reply HELP for help. Msg&Data Rates May Apply."
)

_TRIM = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def detect_keyword(body: str) -> str | None:
    """Classify an inbound SMS body as STOP, START, HELP, or None.

    Returns one of "STOP", "START", "HELP", or None when the body is not
    an exact-match keyword. The match is case-insensitive and tolerates
    surrounding whitespace and trailing punctuation (".", "!").
    """
    if not body:
        return None
    token = _TRIM.sub("", body).upper()
    if token in _STOP_KEYWORDS:
        return "STOP"
    if token in _START_KEYWORDS:
        return "START"
    if token in _HELP_KEYWORDS:
        return "HELP"
    return None
