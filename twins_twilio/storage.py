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

    # -- Logs --

    @abstractmethod
    def append_log(self, entry: dict) -> None:
        """Append an operation log entry."""

    @abstractmethod
    def list_logs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Retrieve operation logs."""
