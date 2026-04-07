"""Flask application factory for the Twilio twin.

The host calls create_app() with a storage backend and configuration,
and receives a configured Flask application to serve.
"""

import logging

from flask import Flask, g

from .storage import TwinStorage
from .routes.accounts import accounts_bp
from .routes.phone_numbers import phone_numbers_bp
from .routes.messages import messages_bp
from .routes.email import email_bp
from .twin_plane.routes import twin_plane_bp

logger = logging.getLogger(__name__)


def create_app(storage: TwinStorage, config: dict | None = None) -> Flask:
    """Create and configure the Twilio twin Flask application.

    Args:
        storage: A TwinStorage implementation provided by the host.
        config: Configuration dict. Supported keys:
            - base_url: The base URL of the twin (e.g., "http://localhost:8080")

    Returns:
        Configured Flask application ready to serve.
    """
    config = config or {}
    base_url = config.get("base_url", "http://localhost:8080")

    app = Flask(__name__)
    app.config["TWIN_STORAGE"] = storage
    app.config["TWIN_BASE_URL"] = base_url

    @app.before_request
    def inject_storage():
        """Make storage and config available to all request handlers."""
        g.storage = app.config["TWIN_STORAGE"]
        g.base_url = app.config["TWIN_BASE_URL"]

    # Register Twilio API routes
    app.register_blueprint(accounts_bp)
    app.register_blueprint(phone_numbers_bp)
    app.register_blueprint(messages_bp)

    # Register SendGrid API routes
    app.register_blueprint(email_bp)

    # Register Twin Plane routes
    app.register_blueprint(twin_plane_bp)

    logger.info("Twilio twin created — base_url=%s", base_url)
    return app
