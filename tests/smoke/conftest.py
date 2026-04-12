"""Shared fixtures for smoke tests.

Starts the twin in-process using Flask's test client, SQLite storage,
and an in-process SQLiteTenantStore. No Docker or external process is
needed for testing.
"""

import base64
import os

import pytest

from twins_twilio.app import create_app

# twins_twilio_local sibling lives inside this repo; put the repo root on sys.path.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from twins_twilio_local.storage_sqlite import SQLiteStorage
from twins_local.tenants import (
    SQLiteTenantStore,
    ensure_default_tenant,
    generate_tenant_id,
    generate_tenant_secret,
    hash_secret,
)


@pytest.fixture
def tenant_store(tmp_path):
    """Fresh tenant store with the default tenant bootstrapped."""
    store = SQLiteTenantStore(db_path=str(tmp_path / "tenants.sqlite3"))
    ensure_default_tenant(store)
    return store


@pytest.fixture
def twin_app(tmp_path, tenant_store):
    """Create a fresh twin app with an ephemeral SQLite database."""
    db_path = str(tmp_path / "test_twin.db")
    storage = SQLiteStorage(db_path=db_path)
    app = create_app(
        storage=storage,
        tenants=tenant_store,
        config={"base_url": "http://localhost:8080"},
    )
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(twin_app):
    """Flask test client."""
    return twin_app.test_client()


@pytest.fixture
def tenant(tenant_store):
    """Create and return a test tenant (distinct from the default tenant)."""
    tenant_id = generate_tenant_id()
    tenant_secret = generate_tenant_secret()
    tenant_store.create_tenant(
        tenant_id=tenant_id,
        secret_hash=hash_secret(tenant_secret),
        friendly_name="Test Tenant",
    )
    return {"tenant_id": tenant_id, "tenant_secret": tenant_secret}


@pytest.fixture
def tenant_headers(tenant):
    """HTTP Basic Auth headers for the test tenant."""
    creds = base64.b64encode(
        f"{tenant['tenant_id']}:{tenant['tenant_secret']}".encode()
    ).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def account(client, tenant_headers):
    """Create and return a Twilio-emulation account inside the test tenant."""
    resp = client.post(
        "/_twin/accounts",
        json={"friendly_name": "Test Account"},
        headers=tenant_headers,
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


@pytest.fixture
def auth_headers(account):
    """HTTP Basic Auth headers for the test account (Twilio-emulation API)."""
    creds = base64.b64encode(
        f"{account['sid']}:{account['auth_token']}".encode()
    ).decode()
    return {"Authorization": f"Basic {creds}"}
