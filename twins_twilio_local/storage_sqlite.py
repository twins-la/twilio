"""SQLite implementation of TwinStorage.

Provides persistent storage for the Twilio twin using SQLite.
The database file is stored at a configurable path, defaulting to ./data/twin.db.

Every resource table carries a ``tenant_id`` column. Lookups filter by
``tenant_id`` where the Twin Plane scope applies; account-scoped methods
additionally enforce (tenant_id, account_sid) via the account's own
tenant_id column.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from twins_twilio.storage import TwinStorage


_VALID_PHONE_NUMBER_COLUMNS = frozenset({
    "friendly_name", "sms_url", "sms_method", "sms_fallback_url",
    "sms_fallback_method", "sms_application_sid", "voice_url", "voice_method",
    "voice_fallback_url", "voice_fallback_method", "voice_application_sid",
    "status_callback", "status_callback_method", "date_updated",
})

_VALID_MESSAGE_COLUMNS = frozenset({
    "status", "date_updated", "date_sent", "price", "error_code", "error_message",
})

_VALID_EMAIL_COLUMNS = frozenset({
    "status", "date_updated",
})

_VALID_FEEDBACK_COLUMNS = frozenset({
    "status", "date_updated",
})


class SQLiteStorage(TwinStorage):
    """SQLite-backed storage for the Twilio twin.

    Thread-safe via a per-instance lock. Uses WAL mode for concurrent reads.
    """

    def __init__(self, db_path: str = "data/twin.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        sid TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        auth_token TEXT NOT NULL,
                        friendly_name TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'active',
                        date_created TEXT NOT NULL,
                        date_updated TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_accounts_tenant
                        ON accounts(tenant_id);

                    CREATE TABLE IF NOT EXISTS phone_numbers (
                        sid TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        account_sid TEXT NOT NULL,
                        phone_number TEXT NOT NULL,
                        friendly_name TEXT NOT NULL DEFAULT '',
                        sms_url TEXT NOT NULL DEFAULT '',
                        sms_method TEXT NOT NULL DEFAULT 'POST',
                        sms_fallback_url TEXT NOT NULL DEFAULT '',
                        sms_fallback_method TEXT NOT NULL DEFAULT 'POST',
                        sms_application_sid TEXT NOT NULL DEFAULT '',
                        voice_url TEXT NOT NULL DEFAULT '',
                        voice_method TEXT NOT NULL DEFAULT 'POST',
                        voice_fallback_url TEXT NOT NULL DEFAULT '',
                        voice_fallback_method TEXT NOT NULL DEFAULT 'POST',
                        voice_application_sid TEXT NOT NULL DEFAULT '',
                        status_callback TEXT NOT NULL DEFAULT '',
                        status_callback_method TEXT NOT NULL DEFAULT 'POST',
                        date_created TEXT NOT NULL,
                        date_updated TEXT NOT NULL,
                        FOREIGN KEY (account_sid) REFERENCES accounts(sid)
                    );

                    CREATE INDEX IF NOT EXISTS idx_phone_numbers_account
                        ON phone_numbers(account_sid);
                    CREATE INDEX IF NOT EXISTS idx_phone_numbers_number
                        ON phone_numbers(account_sid, phone_number);

                    CREATE TABLE IF NOT EXISTS messages (
                        sid TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        account_sid TEXT NOT NULL,
                        "to" TEXT NOT NULL DEFAULT '',
                        from_number TEXT NOT NULL DEFAULT '',
                        body TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'queued',
                        direction TEXT NOT NULL DEFAULT 'outbound-api',
                        date_created TEXT NOT NULL,
                        date_updated TEXT NOT NULL,
                        date_sent TEXT NOT NULL DEFAULT '',
                        num_segments TEXT NOT NULL DEFAULT '1',
                        price TEXT,
                        error_code TEXT,
                        error_message TEXT,
                        messaging_service_sid TEXT,
                        status_callback TEXT NOT NULL DEFAULT '',
                        status_callback_method TEXT NOT NULL DEFAULT 'POST',
                        FOREIGN KEY (account_sid) REFERENCES accounts(sid)
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_account
                        ON messages(account_sid);

                    CREATE TABLE IF NOT EXISTS api_keys (
                        key_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        key_secret TEXT NOT NULL,
                        account_sid TEXT NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        date_created TEXT NOT NULL,
                        FOREIGN KEY (account_sid) REFERENCES accounts(sid)
                    );

                    CREATE INDEX IF NOT EXISTS idx_api_keys_account
                        ON api_keys(account_sid);

                    CREATE TABLE IF NOT EXISTS emails (
                        message_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        account_sid TEXT NOT NULL,
                        from_email TEXT NOT NULL DEFAULT '',
                        from_name TEXT NOT NULL DEFAULT '',
                        subject TEXT NOT NULL DEFAULT '',
                        personalizations TEXT NOT NULL DEFAULT '[]',
                        content TEXT NOT NULL DEFAULT '[]',
                        status TEXT NOT NULL DEFAULT 'processed',
                        date_created TEXT NOT NULL,
                        date_updated TEXT NOT NULL,
                        FOREIGN KEY (account_sid) REFERENCES accounts(sid)
                    );

                    CREATE INDEX IF NOT EXISTS idx_emails_account
                        ON emails(account_sid);

                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        entry TEXT NOT NULL,
                        tenant_id TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_logs_tenant
                        ON logs(tenant_id);

                    CREATE TABLE IF NOT EXISTS feedback (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL DEFAULT '',
                        body TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT '',
                        context TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'pending',
                        date_created TEXT NOT NULL,
                        date_updated TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_feedback_status
                        ON feedback(status);
                    CREATE INDEX IF NOT EXISTS idx_feedback_tenant
                        ON feedback(tenant_id);

                    CREATE TABLE IF NOT EXISTS verified_senders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL,
                        account_sid TEXT NOT NULL,
                        email TEXT NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        date_created TEXT NOT NULL,
                        FOREIGN KEY (account_sid) REFERENCES accounts(sid),
                        UNIQUE(account_sid, email)
                    );

                    CREATE INDEX IF NOT EXISTS idx_verified_senders_account
                        ON verified_senders(account_sid);
                """)
                conn.commit()
            finally:
                conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        return dict(row)

    # -- Accounts --

    def create_account(
        self,
        tenant_id: str,
        sid: str,
        auth_token: str,
        friendly_name: str,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO accounts (sid, tenant_id, auth_token, friendly_name,"
                    " date_created, date_updated)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (sid, tenant_id, auth_token, friendly_name, now, now),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM accounts WHERE sid = ?", (sid,)).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_account(self, sid: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM accounts WHERE sid = ?", (sid,)).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_accounts(self, tenant_id: Optional[str] = None) -> list[dict]:
        conn = self._get_conn()
        try:
            if tenant_id is None:
                rows = conn.execute("SELECT * FROM accounts ORDER BY date_created").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM accounts WHERE tenant_id = ? ORDER BY date_created",
                    (tenant_id,),
                ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # -- Phone Numbers --

    def create_phone_number(self, data: dict) -> dict:
        cols = [
            "sid", "tenant_id", "account_sid", "phone_number", "friendly_name",
            "sms_url", "sms_method", "sms_fallback_url", "sms_fallback_method",
            "sms_application_sid", "voice_url", "voice_method",
            "voice_fallback_url", "voice_fallback_method", "voice_application_sid",
            "status_callback", "status_callback_method",
            "date_created", "date_updated",
        ]
        values = [data.get(c, "") for c in cols]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(f"INSERT INTO phone_numbers ({col_names}) VALUES ({placeholders})", values)
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM phone_numbers WHERE sid = ?", (data["sid"],)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_phone_number(self, account_sid: str, sid: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM phone_numbers WHERE account_sid = ? AND sid = ?",
                (account_sid, sid),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_phone_number_by_number(self, account_sid: str, phone_number: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM phone_numbers WHERE account_sid = ? AND phone_number = ?",
                (account_sid, phone_number),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_phone_numbers(self, account_sid: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM phone_numbers WHERE account_sid = ? ORDER BY date_created",
                (account_sid,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def update_phone_number(self, account_sid: str, sid: str, updates: dict) -> Optional[dict]:
        if not updates:
            return self.get_phone_number(account_sid, sid)

        safe_updates = {k: v for k, v in updates.items() if k in _VALID_PHONE_NUMBER_COLUMNS}
        if not safe_updates:
            return self.get_phone_number(account_sid, sid)

        set_clause = ", ".join([f"{k} = ?" for k in safe_updates.keys()])
        values = list(safe_updates.values()) + [account_sid, sid]

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    f"UPDATE phone_numbers SET {set_clause} WHERE account_sid = ? AND sid = ?",
                    values,
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM phone_numbers WHERE account_sid = ? AND sid = ?",
                    (account_sid, sid),
                ).fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    # -- Messages --

    def create_message(self, data: dict) -> dict:
        cols = [
            "sid", "tenant_id", "account_sid", '"to"', "from_number", "body", "status",
            "direction", "date_created", "date_updated", "date_sent",
            "num_segments", "price", "error_code", "error_message",
            "messaging_service_sid", "status_callback", "status_callback_method",
        ]
        keys = [
            "sid", "tenant_id", "account_sid", "to", "from_number", "body", "status",
            "direction", "date_created", "date_updated", "date_sent",
            "num_segments", "price", "error_code", "error_message",
            "messaging_service_sid", "status_callback", "status_callback_method",
        ]
        values = [data.get(k, "") for k in keys]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(f"INSERT INTO messages ({col_names}) VALUES ({placeholders})", values)
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM messages WHERE sid = ?", (data["sid"],)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_message(self, account_sid: str, sid: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                'SELECT * FROM messages WHERE account_sid = ? AND sid = ?',
                (account_sid, sid),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_messages(self, account_sid: str, filters: Optional[dict] = None) -> list[dict]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM messages WHERE account_sid = ?"
            params: list = [account_sid]

            if filters:
                if "To" in filters:
                    query += ' AND "to" = ?'
                    params.append(filters["To"])
                if "From" in filters:
                    query += " AND from_number = ?"
                    params.append(filters["From"])

            query += " ORDER BY date_created DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def update_message(self, account_sid: str, sid: str, updates: dict) -> Optional[dict]:
        if not updates:
            return self.get_message(account_sid, sid)

        safe_updates = {k: v for k, v in updates.items() if k in _VALID_MESSAGE_COLUMNS}
        if not safe_updates:
            return self.get_message(account_sid, sid)

        set_clause = ", ".join([f'"{k}" = ?' if k == "to" else f"{k} = ?" for k in safe_updates.keys()])
        values = list(safe_updates.values()) + [account_sid, sid]

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    f"UPDATE messages SET {set_clause} WHERE account_sid = ? AND sid = ?",
                    values,
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM messages WHERE account_sid = ? AND sid = ?",
                    (account_sid, sid),
                ).fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    # -- API Keys --

    def create_api_key(
        self,
        tenant_id: str,
        key_id: str,
        key_secret: str,
        account_sid: str,
        name: str,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO api_keys (key_id, tenant_id, key_secret, account_sid, name, date_created) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key_id, tenant_id, key_secret, account_sid, name, now),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_api_key_by_id(self, key_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_api_keys(self, account_sid: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE account_sid = ? ORDER BY date_created",
                (account_sid,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # -- Emails --

    def create_email(self, data: dict) -> dict:
        cols = [
            "message_id", "tenant_id", "account_sid", "from_email", "from_name",
            "subject", "personalizations", "content", "status",
            "date_created", "date_updated",
        ]
        values = []
        for c in cols:
            val = data.get(c, "")
            if c in ("personalizations", "content") and isinstance(val, list):
                val = json.dumps(val)
            values.append(val)
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(f"INSERT INTO emails ({col_names}) VALUES ({placeholders})", values)
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM emails WHERE message_id = ?", (data["message_id"],)
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_email(self, account_sid: str, message_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM emails WHERE account_sid = ? AND message_id = ?",
                (account_sid, message_id),
            ).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            d["personalizations"] = json.loads(d["personalizations"])
            d["content"] = json.loads(d["content"])
            return d
        finally:
            conn.close()

    def list_emails(self, account_sid: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM emails WHERE account_sid = ? ORDER BY date_created DESC",
                (account_sid,),
            ).fetchall()
            result = []
            for row in rows:
                d = self._row_to_dict(row)
                d["personalizations"] = json.loads(d["personalizations"])
                d["content"] = json.loads(d["content"])
                result.append(d)
            return result
        finally:
            conn.close()

    def update_email(self, account_sid: str, message_id: str, updates: dict) -> Optional[dict]:
        if not updates:
            return self.get_email(account_sid, message_id)

        safe_updates = {k: v for k, v in updates.items() if k in _VALID_EMAIL_COLUMNS}
        if not safe_updates:
            return self.get_email(account_sid, message_id)

        set_clause = ", ".join([f"{k} = ?" for k in safe_updates.keys()])
        values = list(safe_updates.values()) + [account_sid, message_id]

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    f"UPDATE emails SET {set_clause} WHERE account_sid = ? AND message_id = ?",
                    values,
                )
                conn.commit()
                return self.get_email(account_sid, message_id)
            finally:
                conn.close()

    # -- Feedback --

    def create_feedback(self, data: dict) -> dict:
        cols = [
            "id", "tenant_id", "body", "category", "context",
            "status", "date_created", "date_updated",
        ]
        values = []
        for c in cols:
            val = data.get(c, "")
            if c == "context" and isinstance(val, dict):
                val = json.dumps(val)
            values.append(val)
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(f"INSERT INTO feedback ({col_names}) VALUES ({placeholders})", values)
                conn.commit()
                row = conn.execute("SELECT * FROM feedback WHERE id = ?", (data["id"],)).fetchone()
                d = self._row_to_dict(row)
                d["context"] = json.loads(d["context"]) if d["context"] else {}
                return d
            finally:
                conn.close()

    def get_feedback(self, feedback_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
            if not row:
                return None
            d = self._row_to_dict(row)
            d["context"] = json.loads(d["context"]) if d["context"] else {}
            return d
        finally:
            conn.close()

    def list_feedback(
        self,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM feedback WHERE 1=1"
            params: list = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if tenant_id is not None:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            query += " ORDER BY date_created DESC"
            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                d = self._row_to_dict(row)
                d["context"] = json.loads(d["context"]) if d["context"] else {}
                result.append(d)
            return result
        finally:
            conn.close()

    def update_feedback(self, feedback_id: str, updates: dict) -> Optional[dict]:
        if not updates:
            return self.get_feedback(feedback_id)

        safe_updates = {k: v for k, v in updates.items() if k in _VALID_FEEDBACK_COLUMNS}
        if not safe_updates:
            return self.get_feedback(feedback_id)

        set_clause = ", ".join([f"{k} = ?" for k in safe_updates.keys()])
        values = list(safe_updates.values()) + [feedback_id]

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    f"UPDATE feedback SET {set_clause} WHERE id = ?",
                    values,
                )
                conn.commit()
                return self.get_feedback(feedback_id)
            finally:
                conn.close()

    # -- Verified Senders --

    def create_verified_sender(
        self,
        tenant_id: str,
        account_sid: str,
        email: str,
        name: str = "",
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO verified_senders (tenant_id, account_sid, email, name, date_created) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tenant_id, account_sid, email, name, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM verified_senders WHERE account_sid = ? AND email = ?",
                    (account_sid, email),
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def get_verified_sender_by_email(self, account_sid: str, email: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM verified_senders WHERE account_sid = ? AND email = ?",
                (account_sid, email),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_verified_senders(self, account_sid: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM verified_senders WHERE account_sid = ? ORDER BY date_created",
                (account_sid,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # -- Logs --

    def append_log(self, entry: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        tenant_id = entry.get("tenant_id", "")
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO logs (timestamp, entry, tenant_id) VALUES (?, ?, ?)",
                    (now, json.dumps(entry), tenant_id),
                )
                conn.commit()
            finally:
                conn.close()

    def list_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        conn = self._get_conn()
        try:
            if tenant_id is not None:
                rows = conn.execute(
                    "SELECT * FROM logs WHERE tenant_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (tenant_id, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM logs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            result = []
            for row in rows:
                d = self._row_to_dict(row)
                d["entry"] = json.loads(d["entry"])
                result.append(d)
            return result
        finally:
            conn.close()
