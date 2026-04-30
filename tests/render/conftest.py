"""Fixtures for browser-render-grain tests of the Twilio twin.

Run:

    pip install -e ".[render]"
    playwright install chromium
    pytest tests/render -m render
"""

import socket
import threading

import pytest
from werkzeug.serving import make_server

from twins_twilio.app import create_app
from twins_twilio_local.storage_sqlite import SQLiteStorage
from twins_local.tenants import SQLiteTenantStore, ensure_default_tenant


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server_url(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("render")
    storage = SQLiteStorage(db_path=str(db_dir / "twin.db"))
    tenants = SQLiteTenantStore(db_path=str(db_dir / "tenants.sqlite3"))
    ensure_default_tenant(tenants)

    port = _free_port()
    app = create_app(
        storage=storage,
        tenants=tenants,
        config={
            "base_url": f"http://127.0.0.1:{port}",
            "admin_token": "",
            "is_cloud": False,
        },
    )

    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
