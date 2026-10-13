import os
import unittest
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock
from werkzeug.security import check_password_hash

from database.db import (
    init_db,
    get_db_connection,
    get_user_by_email,
    create_user,
    ensure_session_exists,
    save_message,
    get_session_messages
)
from app import create_app


class RegistrationFixTestCase(unittest.TestCase):
    def setUp(self):
        # Create a fresh temporary database for each test to isolate tests completely
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_path = self.temp_db.name
        self.temp_db.close()

        os.environ["DATABASE_PATH"] = self.temp_db_path
        os.environ["GROQ_API_KEY"] = "mock_test_key"

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except Exception:
                pass

    def test_01_registration_on_legacy_schema_with_not_null_username(self):
        """Test registration succeeds even when legacy table had NOT NULL constraint on username."""
        # 1. Pre-create legacy table where username is NOT NULL without default
        conn = sqlite3.connect(self.temp_db_path)
        conn.execute("DROP TABLE IF EXISTS users;")
        conn.execute("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()

        # 2. Run init_db to apply non-destructive migration
        init_db()

        # 3. Perform registration via client
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        res = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Marcus Aurelius",
            "email": "marcus@rome.edu",
            "password": "MeditationsPassword123!",
            "confirm_password": "MeditationsPassword123!"
        })

        # Must redirect to login page (302)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/auth/login", res.headers["Location"])

        # Must exist in DB
        user = get_user_by_email("marcus@rome.edu")
        self.assertIsNotNone(user)
        self.assertEqual(user["full_name"], "Marcus Aurelius")
        self.assertEqual(user["normalized_email"], "marcus@rome.edu")

    def test_02_duplicate_email_returns_duplicate_message(self):
        """Test that attempting to register an existing email returns duplicate message."""
        init_db()
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        # First registration
        res1 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Original Student",
            "email": "student@college.edu",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res1.status_code, 302)

        # Second registration with same email
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        res2 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Duplicate Student",
            "email": "student@college.edu",
            "password": "AnotherPassword12345!",
            "confirm_password": "AnotherPassword12345!"
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn(b"An account with this email address already exists.", res2.data)

    def test_03_email_comparison_is_case_insensitive(self):
        """Test case insensitivity during duplicate check and retrieval."""
        init_db()
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        # Register in mixed case
        res1 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Case Test User",
            "email": "  CaseTest@COLLEGE.edu  ",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res1.status_code, 302)

        # Verify query with different casing returns the user
        user = get_user_by_email("casetest@college.edu")
        self.assertIsNotNone(user)
        user_upper = get_user_by_email("CASETEST@COLLEGE.EDU")
        self.assertIsNotNone(user_upper)
        self.assertEqual(user["id"], user_upper["id"])

        # Attempt registration with all caps
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        res2 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Duplicate User",
            "email": "CASETEST@college.EDU",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn(b"An account with this email address already exists.", res2.data)

    def test_04_two_different_email_addresses_create_separate_accounts(self):
        """Test that two distinct email addresses can register separate accounts."""
        init_db()
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        res1 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Student One",
            "email": "student.one@college.edu",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res1.status_code, 302)

        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        res2 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Student Two",
            "email": "student.two@college.edu",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res2.status_code, 302)

        u1 = get_user_by_email("student.one@college.edu")
        u2 = get_user_by_email("student.two@college.edu")

        self.assertIsNotNone(u1)
        self.assertIsNotNone(u2)
        self.assertNotEqual(u1["id"], u2["id"])
        self.assertEqual(u1["normalized_email"], "student.one@college.edu")
        self.assertEqual(u2["normalized_email"], "student.two@college.edu")

    def test_05_passwords_are_stored_as_secure_hashes(self):
        """Verify passwords are never stored in plaintext and match hash verification."""
        init_db()
        raw_pw = "SuperSecretPassword123!@#"
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Security Tester",
            "email": "security@college.edu",
            "password": raw_pw,
            "confirm_password": raw_pw
        })

        user = get_user_by_email("security@college.edu")
        self.assertIsNotNone(user)
        self.assertNotEqual(user["password_hash"], raw_pw)
        self.assertTrue(check_password_hash(user["password_hash"], raw_pw))
        self.assertFalse(check_password_hash(user["password_hash"], "WrongPassword123"))

    def test_06_existing_users_and_chat_history_remain_intact(self):
        """Verify existing users and their chat sessions are preserved through migrations and registration."""
        init_db()
        # Seed an existing user and chat
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (id, full_name, normalized_email, password_hash) VALUES (?, ?, ?, ?)",
            ("existing_u1", "Existing User", "existing@college.edu", "hash1")
        )
        conn.commit()
        conn.close()

        ensure_session_exists("existing_session_1", user_id="existing_u1")
        save_message("msg1", "existing_session_1", "user", "What is Big-O notation?")
        save_message("msg2", "existing_session_1", "assistant", "Big-O measures upper bound.")

        # Now register a brand new user
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        res = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "New Comer",
            "email": "new@college.edu",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res.status_code, 302)

        # Existing user and chat messages must still be completely intact
        existing_u = get_user_by_email("existing@college.edu")
        self.assertIsNotNone(existing_u)
        self.assertEqual(existing_u["id"], "existing_u1")

        messages = get_session_messages("existing_session_1", user_id="existing_u1")
        self.assertIsNotNone(messages)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "What is Big-O notation?")

    def test_07_registration_failures_do_not_create_partial_records(self):
        """Verify failed registrations do not insert partial or corrupted user records."""
        init_db()
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"

        # 1. Password mismatch
        res1 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Failed User 1",
            "email": "fail1@college.edu",
            "password": "Password12345!",
            "confirm_password": "MismatchedPassword123!"
        })
        self.assertEqual(res1.status_code, 400)
        self.assertIsNone(get_user_by_email("fail1@college.edu"))

        # 2. Too short password
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"
        res2 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Failed User 2",
            "email": "fail2@college.edu",
            "password": "short",
            "confirm_password": "short"
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIsNone(get_user_by_email("fail2@college.edu"))

        # 3. Invalid email
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "test_csrf_token"
        res3 = self.client.post("/auth/register", data={
            "csrf_token": "test_csrf_token",
            "full_name": "Failed User 3",
            "email": "not-an-email",
            "password": "Password12345!",
            "confirm_password": "Password12345!"
        })
        self.assertEqual(res3.status_code, 400)
        self.assertIsNone(get_user_by_email("not-an-email"))

    def test_08_unexpected_integrity_errors_not_misreported_as_duplicate(self):
        """Verify unexpected database integrity errors are reported as integrity errors and not duplicate email."""
        init_db()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"name": "id"}, {"name": "full_name"}, {"name": "normalized_email"}]
        mock_cursor.execute.side_effect = [None, sqlite3.IntegrityError("CHECK constraint failed: some_check")]
        mock_conn.cursor.return_value = mock_cursor

        with patch("database.db.get_db_connection", return_value=mock_conn):
            ok, msg = create_user("uid-test", "Name", "test@test.com", "hash")
            self.assertFalse(ok)
            self.assertIn("Database integrity error", msg)
            self.assertNotIn("already exists", msg)


if __name__ == "__main__":
    unittest.main()
