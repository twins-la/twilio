"""Twilio-format SID generation and SendGrid-format ID generation.

Twilio SIDs follow the pattern: PREFIX + 32 lowercase hex characters.
  AC = Account
  SM = SMS Message
  PN = Phone Number
AuthTokens are 32 lowercase hex characters (no prefix).

SendGrid API keys follow the pattern: SG.{key_id}.{key_secret}
  where key_id and key_secret are base64url-encoded random bytes.
SendGrid email IDs are 22-character base64url-encoded strings.
"""

import base64
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


def generate_feedback_id() -> str:
    return generate_sid("FB")


def generate_auth_token() -> str:
    """Generate a 32-character hex auth token."""
    return secrets.token_hex(16)


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_api_key() -> tuple[str, str, str]:
    """Generate a SendGrid-format API key.

    Returns:
        (key_id, key_secret, full_key) where full_key is "SG.{key_id}.{key_secret}"
    """
    key_id = _base64url_encode(secrets.token_bytes(16))
    key_secret = _base64url_encode(secrets.token_bytes(32))
    full_key = f"SG.{key_id}.{key_secret}"
    return key_id, key_secret, full_key


def generate_email_id() -> str:
    """Generate a SendGrid-format X-Message-Id (22-char base64url string)."""
    return _base64url_encode(secrets.token_bytes(16))
