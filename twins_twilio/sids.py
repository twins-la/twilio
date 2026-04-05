"""Twilio-format SID generation.

SIDs follow the pattern: PREFIX + 32 lowercase hex characters.
  AC = Account
  SM = SMS Message
  PN = Phone Number
AuthTokens are 32 lowercase hex characters (no prefix).
"""

import secrets


def generate_sid(prefix: str) -> str:
    """Generate a Twilio-format SID: prefix + 32 hex chars."""
    return prefix + secrets.token_hex(16)


def generate_account_sid() -> str:
    return generate_sid("AC")


def generate_message_sid() -> str:
    return generate_sid("SM")


def generate_phone_number_sid() -> str:
    return generate_sid("PN")


def generate_auth_token() -> str:
    """Generate a 32-character hex auth token."""
    return secrets.token_hex(16)
