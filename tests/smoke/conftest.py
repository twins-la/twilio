"""Shared fixtures for smoke tests.

Starts the twin in-process using Flask's test client and SQLite storage,
so no Docker or external process is needed for testing.
"""

import os
import tempfile

import pytest

from twins_twilio.app import create_app

# Add the local package to the path so we can use SQLiteStorage
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "local"))

from twins_local.storage_sqlite import SQLiteStorage


@pytest.fixture
def twin_app(tmp_path):
    """Create a fresh twin app with an ephemeral SQLite database."""
    db_path = str(tmp_path / "test_twin.db")
    storage = SQLiteStorage(db_path=db_path)
    app = create_app(storage=storage, config={"base_url": "http://localhost:8080"})
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(twin_app):
    """Flask test client."""
    return twin_app.test_client()


@pytest.fixture
def account(client):
    """Create and return a test account via Twin Plane."""
    resp = client.post("/_twin/accounts", json={"friendly_name": "Test Account"})
    assert resp.status_code == 201
    return resp.get_json()


@pytest.fixture
def auth_headers(account):
    """HTTP Basic Auth headers for the test account."""
    import base64
    creds = base64.b64encode(
        f"{account['sid']}:{account['auth_token']}".encode()
    ).decode()
    return {"Authorization": f"Basic {creds}"}
