"""Local host entry point for the Twilio twin.

Wires up SQLite storage, creates the twin Flask app, and serves it.
Can be run directly or via gunicorn.
"""

import logging
import os

from twins_twilio.app import create_app

from .config import ADMIN_TOKEN, BASE_URL, DB_PATH
from .storage_sqlite import SQLiteStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_local_app():
    """Create the locally-hosted twin application.

    This is the WSGI entry point for gunicorn:
        gunicorn 'twins_twilio_local.host:create_local_app()'
    """
    # Ensure data directory exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    storage = SQLiteStorage(db_path=DB_PATH)
    app = create_app(storage=storage, config={"base_url": BASE_URL, "admin_token": ADMIN_TOKEN})

    logger.info("Local twin ready — db=%s base_url=%s", DB_PATH, BASE_URL)
    return app


# For `python -m twins_twilio_local`
app = None


def main():
    global app
    from .config import HOST, PORT

    app = create_local_app()
    logger.info("Starting local twin on %s:%d", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
