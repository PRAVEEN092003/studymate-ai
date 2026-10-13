import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, session
from database.db import init_db
from routes.auth_routes import auth_bp, login_required
from routes.chat_routes import chat_bp

# Load environment configuration
load_dotenv(override=True)


def create_app():
    """Application factory for StudyMate AI with authentication and security headers."""
    app = Flask(__name__)

    # Security configuration
    secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY")
    is_production = os.getenv("FLASK_ENV") == "production" or os.getenv("FLASK_DEBUG", "True").lower() not in ("true", "1", "t")

    if not secret_key:
        if is_production:
            raise ValueError("CRITICAL SECURITY ERROR: FLASK_SECRET_KEY must be set in production environment!")
        secret_key = "studymate-dev-insecure-key-change-in-production"

    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

    # Initialize SQLite database tables automatically
    with app.app_context():
        init_db()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)

    # Template context processor for CSRF tokens and user state
    @app.context_processor
    def inject_auth_globals():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(32)
        return {
            "csrf_token": session.get("_csrf_token", ""),
            "current_user_name": session.get("user_name", "Student"),
            "current_user_email": session.get("user_email", ""),
            "is_authenticated": bool(session.get("user_id"))
        }

    @app.route("/", methods=["GET"])
    @login_required
    def index():
        """Serve main chat application page for authenticated users."""
        return render_template("index.html")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "t")
    app.run(host="0.0.0.0", port=port, debug=debug)
