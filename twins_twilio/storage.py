"""Abstract storage interface for the Twilio twin.

Hosts provide concrete implementations (SQLite, Postgres, etc.).
The twin package never imports a specific database driver.
"""

from abc import ABC, abstractmethod
from typing import Optional


class TwinStorage(ABC):
    """Storage backend contract that hosts must implement."""

    # -- Accounts --

    @abstractmethod
    def create_account(self, sid: str, auth_token: str, friendly_name: str) -> dict:
        """Create an account. Returns the stored account dict."""

    @abstractmethod
    def get_account(self, sid: str) -> Optional[dict]:
        """Fetch an account by SID. Returns None if not found."""

    @abstractmethod
    def list_accounts(self) -> list[dict]:
        """List all accounts."""

    # -- Phone Numbers --

    @abstractmethod
    def create_phone_number(self, data: dict) -> dict:
        """Create a phone number resource. data must include sid, account_sid, phone_number."""

    @abstractmethod
    def get_phone_number(self, account_sid: str, sid: str) -> Optional[dict]:
        """Fetch a phone number by SID within an account."""

    @abstractmethod
    def get_phone_number_by_number(self, account_sid: str, phone_number: str) -> Optional[dict]:
        """Fetch a phone number by its E.164 number within an account."""

    @abstractmethod
    def list_phone_numbers(self, account_sid: str) -> list[dict]:
        """List all phone numbers for an account."""

    @abstractmethod
    def update_phone_number(self, account_sid: str, sid: str, updates: dict) -> Optional[dict]:
        """Update a phone number resource. Returns updated dict or None."""

    # -- Messages --

    @abstractmethod
    def create_message(self, data: dict) -> dict:
        """Create a message record. data must include sid, account_sid, etc."""

    @abstractmethod
    def get_message(self, account_sid: str, sid: str) -> Optional[dict]:
        """Fetch a message by SID within an account."""

    @abstractmethod
    def list_messages(self, account_sid: str, filters: Optional[dict] = None) -> list[dict]:
        """List messages for an account, optionally filtered."""

    @abstractmethod
    def update_message(self, account_sid: str, sid: str, updates: dict) -> Optional[dict]:
        """Update a message record. Returns updated dict or None."""

    # -- API Keys (SendGrid-style) --

    @abstractmethod
    def create_api_key(self, key_id: str, key_secret: str, account_sid: str, name: str) -> dict:
        """Create an API key. Returns the stored key dict."""

    @abstractmethod
    def get_api_key_by_id(self, key_id: str) -> Optional[dict]:
        """Fetch an API key by its key_id. Returns None if not found."""

    @abstractmethod
    def list_api_keys(self, account_sid: str) -> list[dict]:
        """List all API keys for an account."""

    # -- Emails --

    @abstractmethod
    def create_email(self, data: dict) -> dict:
        """Create an email record. data must include message_id, account_sid, etc."""

    @abstractmethod
    def get_email(self, account_sid: str, message_id: str) -> Optional[dict]:
        """Fetch an email by message_id within an account."""

    @abstractmethod
    def list_emails(self, account_sid: str) -> list[dict]:
        """List emails for an account."""

    @abstractmethod
    def update_email(self, account_sid: str, message_id: str, updates: dict) -> Optional[dict]:
        """Update an email record. Returns updated dict or None."""

    # -- Feedback --

    @abstractmethod
    def create_feedback(self, data: dict) -> dict:
        """Create a feedback record. data must include id, body, status, timestamps."""

    @abstractmethod
    def get_feedback(self, feedback_id: str) -> Optional[dict]:
        """Fetch a feedback record by ID. Returns None if not found."""

    @abstractmethod
    def list_feedback(self, status: Optional[str] = None, account_sid: Optional[str] = None) -> list[dict]:
        """List feedback records, optionally filtered by status and/or account."""

    @abstractmethod
    def update_feedback(self, feedback_id: str, updates: dict) -> Optional[dict]:
        """Update a feedback record. Returns updated dict or None."""

    # -- Verified Senders --

    @abstractmethod
    def create_verified_sender(self, account_sid: str, email: str, name: str = "") -> dict:
        """Register a verified sender identity. Returns the stored sender dict."""

    @abstractmethod
    def get_verified_sender_by_email(self, account_sid: str, email: str) -> Optional[dict]:
        """Check if an email is a verified sender for the account. Returns None if not."""

    @abstractmethod
    def list_verified_senders(self, account_sid: str) -> list[dict]:
        """List all verified senders for an account."""

    # -- Logs --

    @abstractmethod
    def append_log(self, entry: dict) -> None:
        """Append an operation log entry."""

    @abstractmethod
    def list_logs(self, limit: int = 100, offset: int = 0, account_sid: Optional[str] = None) -> list[dict]:
        """Retrieve operation logs, optionally filtered by account."""
