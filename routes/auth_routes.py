import os
import uuid
import secrets
from functools import wraps
from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    session,
    jsonify,
    flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import (
    create_user,
    get_user_by_email,
    is_valid_email,
    record_login_attempt,
    get_recent_failed_attempts,
    clear_login_attempts
)

auth_bp = Blueprint("auth_bp", __name__)


def login_required(f):
    """Decorator requiring an authenticated session for route access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "Authentication required. Please log in."
                }), 401
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def get_client_ip() -> str:
    """Extract client IP address for rate limiting."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown_ip"


def verify_csrf_token(token: str) -> bool:
    """Verify CSRF token matches active session token."""
    session_token = session.get("_csrf_token")
    if not session_token or not token:
        return False
    return secrets.compare_digest(session_token, token)


@auth_bp.route("/auth/register", methods=["GET", "POST"])
def register():
    """Handle new user registration with server-side validation and secure password hashing."""
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    success = None

    if request.method == "POST":
        csrf_tok = request.form.get("csrf_token", "")
        if not verify_csrf_token(csrf_tok):
            error = "Security validation error. Please refresh and try again."
            return render_template("register.html", error=error), 400

        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Validation rules
        if not full_name or len(full_name) < 2:
            error = "Full name must be at least 2 characters long."
        elif not is_valid_email(email):
            error = "Please enter a valid email address."
        elif not password or len(password) < 8:
            error = "Password must be at least 8 characters long."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            # Check for existing user
            existing = get_user_by_email(email)
            if existing:
                error = "An account with this email address already exists."
            else:
                user_id = str(uuid.uuid4())
                password_hash = generate_password_hash(password)
                ok, msg = create_user(user_id, full_name, email, password_hash)
                if ok:
                    # Redirect to login with confirmation
                    return redirect(url_for("auth_bp.login", registered="1"))
                else:
                    if msg == "An account with this email address already exists.":
                        error = msg
                    else:
                        error = "Unable to create account right now. Please try again."

        return render_template("register.html", error=error, full_name=full_name, email=email), 400

    return render_template("register.html", error=error, success=success)


@auth_bp.route("/auth/login", methods=["GET", "POST"])
def login():
    """Handle user authentication with rate limiting and session fixation protection."""
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    registered = request.args.get("registered") == "1"
    next_url = request.args.get("next", "")

    if request.method == "POST":
        csrf_tok = request.form.get("csrf_token", "")
        if not verify_csrf_token(csrf_tok):
            error = "Security validation error. Please refresh and try again."
            return render_template("login.html", error=error), 400

        ip = get_client_ip()
        ip_limiter = f"ip:{ip}"

        # Check rate limit (max 5 failed attempts per 5 minutes)
        if get_recent_failed_attempts(ip_limiter, window_seconds=300) >= 5:
            error = "Too many failed login attempts. Please wait 5 minutes before trying again."
            return render_template("login.html", error=error), 429

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_param = request.form.get("next", "")

        if not email or not password:
            error = "Both email and password are required."
            return render_template("login.html", error=error, email=email), 400

        user = get_user_by_email(email)

        # Constant-time comparison check
        if not user or not user.get("password_hash") or not check_password_hash(user["password_hash"], password):
            record_login_attempt(ip_limiter)
            # Generic error to prevent user enumeration
            error = "Invalid email address or password."
            return render_template("login.html", error=error, email=email), 401

        # Clear failed login attempts upon success
        clear_login_attempts(ip_limiter)

        # Session Fixation Mitigation: Clear old session and re-seed
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user.get("full_name") or user.get("username") or "Student"
        session["user_email"] = user.get("normalized_email") or ""
        session["_csrf_token"] = secrets.token_hex(32)
        session.permanent = True

        # Safe redirect check
        target = next_param if next_param and next_param.startswith("/") and not next_param.startswith("//") else url_for("index")
        return redirect(target)

    return render_template("login.html", error=error, registered=registered, next=next_url)


@auth_bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    """Secure POST logout clearing session credentials and redirecting to login."""
    csrf_tok = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not verify_csrf_token(csrf_tok):
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 400

    session.clear()
    if request.path.startswith("/api/"):
        return jsonify({"success": True, "message": "Logged out successfully."}), 200
    return redirect(url_for("auth_bp.login"))
