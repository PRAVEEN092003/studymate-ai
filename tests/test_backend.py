import os
import unittest
import json
import tempfile
from unittest.mock import patch

# Set a temporary database path before importing app
temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
temp_db_path = temp_db_file.name
temp_db_file.close()

os.environ["DATABASE_PATH"] = temp_db_path
os.environ["GROQ_API_KEY"] = "mock_groq_api_key_test_12345"
os.environ["MAX_MESSAGE_LENGTH"] = "4000"

from app import create_app
from database.db import (
    init_db,
    ensure_session_exists,
    save_message,
    get_all_sessions,
    get_session_messages,
    delete_session,
    get_user_by_email,
    get_recent_failed_attempts,
    clear_login_attempts
)


class BackendTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass

    def setUp(self):
        init_db()
        # Authenticate client by default for general backend tests
        with self.client.session_transaction() as sess:
            sess["user_id"] = "user_test_default_id"
            sess["user_name"] = "Default Student"
            sess["user_email"] = "default@student.local"
            sess["_csrf_token"] = "valid_csrf_token_for_tests"

    def test_01_index_page_authenticated(self):
        """Test GET / renders index HTML successfully for authenticated user."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"StudyMate", response.data)
        self.assertIn(b"chat-sidebar", response.data)
        self.assertIn(b"Default Student", response.data)

    def test_02_health_endpoint_public(self):
        """Test GET /api/health returns healthy JSON status without requiring auth."""
        # Test with a clean unauthenticated client
        unauth_client = self.app.test_client()
        response = unauth_client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["database"], "healthy")
        self.assertTrue(data["groq_service_configured"])
        self.assertNotIn("GROQ_API_KEY", json.dumps(data))

    def test_03_chat_empty_and_missing_payload(self):
        """Test POST /api/chat rejects empty and missing payloads."""
        res1 = self.client.post("/api/chat", json={})
        self.assertEqual(res1.status_code, 400)
        self.assertFalse(res1.get_json()["success"])

        res2 = self.client.post("/api/chat", json={"message": "   "})
        self.assertEqual(res2.status_code, 400)
        self.assertFalse(res2.get_json()["success"])

        res3 = self.client.post("/api/chat", json={"message": 12345})
        self.assertEqual(res3.status_code, 400)

    def test_04_chat_oversized_message(self):
        """Test POST /api/chat rejects messages exceeding length limits."""
        huge_text = "A" * 4001
        res = self.client.post("/api/chat", json={"message": huge_text})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("exceeds the maximum permitted length", data["error"])

    def test_05_invalid_session_id_rejected(self):
        """Test invalid session IDs with malicious chars are rejected."""
        malicious_ids = [
            "session; DROP TABLE users;--",
            "session/../../etc/passwd",
            "<script>alert(1)</script>",
            "a" * 65
        ]
        for bad_id in malicious_ids:
            res = self.client.post("/api/chat", json={
                "message": "Hello",
                "session_id": bad_id
            })
            self.assertEqual(res.status_code, 400)
            self.assertIn("Invalid session identifier format", res.get_json()["error"])

    def test_06_session_lifecycle_and_chronological_messages(self):
        """Test creating session, saving messages, retrieving in order, and deleting safely."""
        session_a = "test-session-a-123"
        session_b = "test-session-b-456"

        ensure_session_exists(session_a, user_id="user_test_default_id")
        ensure_session_exists(session_b, user_id="user_test_default_id")

        save_message("msg-1", session_a, "user", "First question A")
        save_message("msg-2", session_a, "assistant", "First answer A")
        save_message("msg-3", session_a, "user", "Second question A")

        save_message("msg-b1", session_b, "user", "First question B")

        messages_a = get_session_messages(session_a, user_id="user_test_default_id")
        self.assertEqual(len(messages_a), 3)
        self.assertEqual(messages_a[0]["content"], "First question A")
        self.assertEqual(messages_a[1]["content"], "First answer A")
        self.assertEqual(messages_a[2]["content"], "Second question A")

        messages_b = get_session_messages(session_b, user_id="user_test_default_id")
        self.assertEqual(len(messages_b), 1)

        res_del = self.client.delete(f"/api/sessions/{session_a}")
        self.assertEqual(res_del.status_code, 200)

        # Session A messages gone
        self.assertIsNone(get_session_messages(session_a, user_id="user_test_default_id"))

        # Session B messages intact
        self.assertEqual(len(get_session_messages(session_b, user_id="user_test_default_id")), 1)

    def test_07_api_failure_safe_error_no_secret_leakage(self):
        """Test that API failure returns safe error message and never leaks GROQ_API_KEY."""
        with patch("services.groq_service.requests.post") as mock_post:
            mock_post.side_effect = Exception(f"Internal error connecting with key {os.environ['GROQ_API_KEY']}")
            
            res = self.client.post("/api/chat", json={
                "message": "Explain quicksort",
                "session_id": "test-err-leak-session"
            })
            self.assertEqual(res.status_code, 500)
            data = res.get_json()
            self.assertFalse(data["success"])
            self.assertNotIn(os.environ["GROQ_API_KEY"], data["error"])
            self.assertNotIn("mock_groq_api_key_test_12345", json.dumps(data))

    # ==========================================================================
    # Authentication & Authorization Tests
    # ==========================================================================

    def test_08_unauthenticated_requests_blocked(self):
        """Test unauthenticated requests are redirected or receive 401."""
        unauth_client = self.app.test_client()

        # HTML page redirect to /auth/login
        res_page = unauth_client.get("/")
        self.assertEqual(res_page.status_code, 302)
        self.assertIn("/auth/login", res_page.headers["Location"])

        # API endpoint returns 401 JSON
        res_api = unauth_client.get("/api/sessions")
        self.assertEqual(res_api.status_code, 401)
        self.assertFalse(res_api.get_json()["success"])

        res_chat = unauth_client.post("/api/chat", json={"message": "Hello"})
        self.assertEqual(res_chat.status_code, 401)

    def test_09_user_registration_success_and_validation(self):
        """Test user registration flow, validation errors, and password hashing."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "valid_csrf"

        # Short password rejected
        res_short = client.post("/auth/register", data={
            "csrf_token": "valid_csrf",
            "full_name": "Jordan Smith",
            "email": "jordan@college.edu",
            "password": "123",
            "confirm_password": "123"
        })
        self.assertEqual(res_short.status_code, 400)
        self.assertIn(b"at least 8 characters", res_short.data)

        # Password mismatch rejected
        res_mismatch = client.post("/auth/register", data={
            "csrf_token": "valid_csrf",
            "full_name": "Jordan Smith",
            "email": "jordan@college.edu",
            "password": "password123",
            "confirm_password": "password999"
        })
        self.assertEqual(res_mismatch.status_code, 400)
        self.assertIn(b"Passwords do not match", res_mismatch.data)

        # Successful registration
        res_ok = client.post("/auth/register", data={
            "csrf_token": "valid_csrf",
            "full_name": "Jordan Smith",
            "email": "Jordan@College.EDU ",  # Test normalization
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!"
        })
        self.assertEqual(res_ok.status_code, 302)
        self.assertIn("/auth/login", res_ok.headers["Location"])

        # Check DB: normalized email and hashed password
        user = get_user_by_email("jordan@college.edu")
        self.assertIsNotNone(user)
        self.assertEqual(user["full_name"], "Jordan Smith")
        self.assertNotEqual(user["password_hash"], "SecurePassword123!")

        # Duplicate email registration rejected
        res_dup = client.post("/auth/register", data={
            "csrf_token": "valid_csrf",
            "full_name": "Jordan Duplicate",
            "email": "jordan@college.edu",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!"
        })
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn(b"already exists", res_dup.data)

    def test_10_user_login_success_and_failure(self):
        """Test login authentication, invalid credentials, and session establishment."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "valid_csrf"

        # Register user first
        client.post("/auth/register", data={
            "csrf_token": "valid_csrf",
            "full_name": "Taylor Swift",
            "email": "taylor@college.edu",
            "password": "CorrectPassword123",
            "confirm_password": "CorrectPassword123"
        })

        # Wrong password rejected
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "valid_csrf"
        res_fail = client.post("/auth/login", data={
            "csrf_token": "valid_csrf",
            "email": "taylor@college.edu",
            "password": "WrongPassword999"
        })
        self.assertEqual(res_fail.status_code, 401)
        self.assertIn(b"Invalid email address or password", res_fail.data)

        # Successful login
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "valid_csrf"
        res_ok = client.post("/auth/login", data={
            "csrf_token": "valid_csrf",
            "email": "taylor@college.edu",
            "password": "CorrectPassword123"
        })
        self.assertEqual(res_ok.status_code, 302)

        # Check session established
        with client.session_transaction() as sess:
            self.assertIn("user_id", sess)
            self.assertEqual(sess["user_email"], "taylor@college.edu")

    def test_11_user_login_rate_limiting(self):
        """Test rate limiting blocks brute-force login attempts."""
        client = self.app.test_client()
        clear_login_attempts("ip:127.0.0.1")

        with client.session_transaction() as sess:
            sess["_csrf_token"] = "valid_csrf"

        # Trigger 5 failed attempts
        for _ in range(5):
            client.post("/auth/login", data={
                "csrf_token": "valid_csrf",
                "email": "nonexistent@college.edu",
                "password": "wrong"
            })

        # 6th attempt should be blocked by rate limiter
        res_blocked = client.post("/auth/login", data={
            "csrf_token": "valid_csrf",
            "email": "nonexistent@college.edu",
            "password": "wrong"
        })
        self.assertEqual(res_blocked.status_code, 429)
        self.assertIn(b"Too many failed login attempts", res_blocked.data)

        clear_login_attempts("ip:127.0.0.1")

    def test_12_cross_user_session_isolation(self):
        """Test User B cannot view, message in, or delete User A's chat sessions."""
        client_a = self.app.test_client()
        with client_a.session_transaction() as sess:
            sess["user_id"] = "user_alice"
            sess["_csrf_token"] = "valid_csrf"

        client_b = self.app.test_client()
        with client_b.session_transaction() as sess:
            sess["user_id"] = "user_bob"
            sess["_csrf_token"] = "valid_csrf"

        alice_session = "alice-secret-session"
        ensure_session_exists(alice_session, user_id="user_alice")
        save_message("msg-a1", alice_session, "user", "Alice confidential study notes")

        # User A can access
        res_a = client_a.get(f"/api/sessions/{alice_session}/messages")
        self.assertEqual(res_a.status_code, 200)
        self.assertEqual(len(res_a.get_json()["messages"]), 1)

        # User B CANNOT access User A's session messages (403 Forbidden)
        res_b = client_b.get(f"/api/sessions/{alice_session}/messages")
        self.assertEqual(res_b.status_code, 403)

        # User B CANNOT post messages into User A's session (403 Forbidden)
        res_b_post = client_b.post("/api/chat", json={
            "message": "Bob trying to hijack Alice's session",
            "session_id": alice_session
        })
        self.assertEqual(res_b_post.status_code, 403)

        # User B CANNOT delete User A's session (403 Forbidden)
        res_b_del = client_b.delete(f"/api/sessions/{alice_session}")
        self.assertEqual(res_b_del.status_code, 403)

        # Alice's session is still intact!
        res_a_check = client_a.get(f"/api/sessions/{alice_session}/messages")
        self.assertEqual(res_a_check.status_code, 200)

    def test_13_logout_clears_session(self):
        """Test POST /auth/logout clears user session and redirects to login."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = "logout_test_user"
            sess["_csrf_token"] = "valid_csrf"

        res = client.post("/auth/logout", data={"csrf_token": "valid_csrf"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("/auth/login", res.headers["Location"])

        # Session is now empty
        with client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    def test_14_theme_elements_present_in_templates(self):
        """Test that anti-flash scripts and theme toggle buttons are rendered across pages."""
        # 1. Main chat template (authenticated)
        res_index = self.client.get("/")
        self.assertEqual(res_index.status_code, 200)
        self.assertIn(b"theme-toggle-btn", res_index.data)
        self.assertIn(b"studymate_theme", res_index.data)
        self.assertIn(b"sun-icon", res_index.data)
        self.assertIn(b"moon-icon", res_index.data)

        # 2. Login page
        client = self.app.test_client()
        res_login = client.get("/auth/login")
        self.assertEqual(res_login.status_code, 200)
        self.assertIn(b"theme-toggle-btn", res_login.data)
        self.assertIn(b"studymate_theme", res_login.data)
        self.assertIn(b"sun-icon", res_login.data)
        self.assertIn(b"moon-icon", res_login.data)

        # 3. Registration page
        res_reg = client.get("/auth/register")
        self.assertEqual(res_reg.status_code, 200)
        self.assertIn(b"theme-toggle-btn", res_reg.data)
        self.assertIn(b"studymate_theme", res_reg.data)
        self.assertIn(b"sun-icon", res_reg.data)
        self.assertIn(b"moon-icon", res_reg.data)

    def test_15_css_theme_variables_and_rules(self):
        """Verify CSS contains required theme tokens for both light and dark mode."""
        css_path = os.path.join(self.app.root_path, "static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

        self.assertIn("[data-theme=\"light\"]", css_content)
        self.assertIn("[data-theme=\"dark\"]", css_content)
        self.assertIn(".theme-toggle-btn", css_content)
        self.assertIn(".sun-icon", css_content)
        self.assertIn(".moon-icon", css_content)
        self.assertIn("--bg-base", css_content)
        self.assertIn("--bg-surface", css_content)
        self.assertIn("--text-primary", css_content)


if __name__ == "__main__":
    unittest.main()

