"""Application factory."""
import os

from dotenv import load_dotenv
from flask import Flask

from config import config_by_name

from .extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__)
    name = config_name or os.environ.get("FLASK_CONFIG", "development")
    app.config.from_object(config_by_name[name]())

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401  (registers tables + user_loader)
    from .cli import register_cli

    register_cli(app)

    # Blueprints (auth, uploads, transactions, dashboard) are registered here in the next steps.
    return app
