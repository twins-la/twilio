"""Configuration for local hosting of the Twilio twin."""

import os

# Database
DB_PATH = os.environ.get("TWIN_DB_PATH", "data/twin.db")

# Server
HOST = os.environ.get("TWIN_HOST", "0.0.0.0")
PORT = int(os.environ.get("TWIN_PORT", "8080"))

# Base URL — how the twin identifies itself (used in webhook signatures, etc.)
BASE_URL = os.environ.get("TWIN_BASE_URL", f"http://localhost:{PORT}")

# Admin — Bearer token for service-wide Twin Plane operations
# If unset, admin endpoints are unrestricted (local dev convenience)
ADMIN_TOKEN = os.environ.get("TWIN_ADMIN_TOKEN", "")
