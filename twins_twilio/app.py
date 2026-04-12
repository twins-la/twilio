"""Flask application factory for the Twilio twin.

The host calls create_app() with a storage backend, a tenant store, and
configuration, and receives a configured Flask application to serve.
"""

import logging

from flask import Flask, g

from twins_local.logs import install_correlation_id

from .storage import TwinStorage
from .routes.accounts import accounts_bp
from .routes.phone_numbers import phone_numbers_bp
from .routes.messages import messages_bp
from .routes.email import email_bp
from .twin_plane.routes import twin_plane_bp
from .explainer import explainer_bp

logger = logging.getLogger(__name__)


def create_app(
    storage: TwinStorage,
    tenants=None,
    config: dict | None = None,
) -> Flask:
    """Create and configure the Twilio twin Flask application.

    Args:
        storage: A TwinStorage implementation provided by the host.
        tenants: A TenantStore implementation provided by the host. Required
            for Twin Plane tenant auth; tests may omit if they do not
            exercise tenant-protected routes.
        config: Configuration dict. Supported keys:
            - base_url: The base URL of the twin (e.g., "http://localhost:8080")
            - admin_token: Operator-admin Bearer token; empty means local-dev
              (any bearer accepted).
            - is_cloud: When True, the cloud guard rejects tenant_id="default".

    Returns:
        Configured Flask application ready to serve.
    """
    config = config or {}
    base_url = config.get("base_url", "http://localhost:8080")
    admin_token = config.get("admin_token", "")
    is_cloud = bool(config.get("is_cloud", False))

    app = Flask(__name__)
    app.config["TWIN_STORAGE"] = storage
    app.config["TWIN_TENANTS"] = tenants
    app.config["TWIN_BASE_URL"] = base_url
    app.config["TWIN_ADMIN_TOKEN"] = admin_token
    app.config["TWIN_IS_CLOUD"] = is_cloud

    # Stamp every request with a correlation_id so emitted log records
    # share it (twins-la/LOGGING.md §1.2, §3.2).
    install_correlation_id(app)

    @app.before_request
    def inject_context():
        """Make storage, tenants, and config available to all request handlers."""
        g.storage = app.config["TWIN_STORAGE"]
        g.tenants = app.config["TWIN_TENANTS"]
        g.base_url = app.config["TWIN_BASE_URL"]
        g.admin_token = app.config["TWIN_ADMIN_TOKEN"]
        g.is_cloud = app.config["TWIN_IS_CLOUD"]

    # Register Twilio API routes
    app.register_blueprint(accounts_bp)
    app.register_blueprint(phone_numbers_bp)
    app.register_blueprint(messages_bp)

    # Register SendGrid API routes
    app.register_blueprint(email_bp)

    # Register Twin Plane routes
    app.register_blueprint(twin_plane_bp)

    # Register explainer page and agent instructions
    app.register_blueprint(explainer_bp)

    logger.info("Twilio twin created — base_url=%s cloud=%s", base_url, is_cloud)
    return app
