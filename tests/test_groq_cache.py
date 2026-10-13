import os
import unittest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Set test environment
os.environ["DATABASE_PATH"] = "test_groq_cache.db"
os.environ["GROQ_API_KEY"] = "mock_groq_key_abcdef12345"
os.environ["GROQ_TIMEOUT"] = "5"
os.environ["GROQ_MAX_RETRIES"] = "2"
os.environ["CACHE_TTL_SECONDS"] = "2"  # short TTL for expiration tests

from app import create_app
from database.db import init_db, get_db_connection
from services.cache_service import (
    generate_cache_key,
    get_cached_response,
    store_cached_response
)
from services.groq_service import GroqService


class GroqAndCacheTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists("test_groq_cache.db"):
            try:
                os.remove("test_groq_cache.db")
            except Exception:
                pass

    def setUp(self):
        init_db()
        conn = get_db_connection()
        conn.execute(
            "INSERT OR IGNORE INTO users (id, full_name, normalized_email, password_hash) VALUES (?, ?, ?, ?)",
            ("cache_test_user_1", "Cache Tester", "cache@tester.local", "hash123")
        )
        conn.commit()
        conn.close()

        with self.client.session_transaction() as sess:
            sess["user_id"] = "cache_test_user_1"
            sess["user_name"] = "Cache Tester"
            sess["user_email"] = "cache@tester.local"
            sess["_csrf_token"] = "test_csrf_token"

    def test_01_cache_hit_avoids_api_call(self):
        """Test that eligible cached response is reused and Groq API is not called."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Bubble sort has O(n^2) worst case."}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 15, "total_tokens": 27}
        }

        with patch("services.groq_service.requests.post", return_value=mock_response) as mock_post:
            # First request -> cache miss, calls Groq
            res1 = self.client.post("/api/chat", json={
                "message": "What is the complexity of bubble sort?",
                "session_id": "cache-test-session-1"
            })
            self.assertEqual(res1.status_code, 200)
            self.assertFalse(res1.get_json()["cached"])
            self.assertEqual(mock_post.call_count, 1)

            # Second identical request with identical context -> cache hit, does NOT call Groq
            res2 = self.client.post("/api/chat", json={
                "message": "What is the complexity of bubble sort?",
                "session_id": "cache-test-session-2"
            })
            self.assertEqual(res2.status_code, 200)
            self.assertTrue(res2.get_json()["cached"])
            # Call count remains 1!
            self.assertEqual(mock_post.call_count, 1)

    def test_02_different_model_or_prompt_version_generates_distinct_cache_keys(self):
        """Test that different models or prompt versions do not share cached entries."""
        key1 = generate_cache_key("test question", [], "llama-3.3-70b-versatile", "v1.0")
        key2 = generate_cache_key("test question", [], "mixtral-8x7b-32768", "v1.0")
        key3 = generate_cache_key("test question", [], "llama-3.3-70b-versatile", "v2.0")

        self.assertNotEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_03_expired_cache_entries_are_not_returned(self):
        """Test that expired cache records are purged and not served."""
        key = "test_expired_key"
        store_cached_response(key, "question", "model", "v1.0", "Old response text")

        # Manually alter expires_at in database to the past
        conn = get_db_connection()
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        conn.execute("UPDATE response_cache SET expires_at = ? WHERE cache_key = ?", (past_time, key))
        conn.commit()
        conn.close()

        # Fetching now must return None
        cached = get_cached_response(key)
        self.assertIsNone(cached)

    def test_04_failed_responses_are_not_cached(self):
        """Test that HTTP 500 error responses are never stored in response_cache."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": {"message": "Server error"}}

        with patch("services.groq_service.requests.post", return_value=mock_response):
            res = self.client.post("/api/chat", json={
                "message": "Explain binary search",
                "session_id": "failed-cache-session"
            })
            self.assertEqual(res.status_code, 500)

        # Check DB directly to ensure binary search response was not stored
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM response_cache WHERE prompt = 'Explain binary search'").fetchone()
        conn.close()
        self.assertIsNone(row)

    def test_05_rate_limit_bounded_retries_and_retry_after(self):
        """Test HTTP 429 rate limit respects Retry-After and stops after max retries."""
        service = GroqService()
        service.max_retries = 2

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0.01"}
        mock_429.json.return_value = {"error": {"message": "Rate limit exceeded"}}

        with patch("services.groq_service.requests.post", return_value=mock_429) as mock_post, \
             patch("services.groq_service.time.sleep") as mock_sleep:
            success, err_msg, meta = service.call_chat_completion([{"role": "user", "content": "Hi"}])
            
            self.assertFalse(success)
            self.assertEqual(meta["error_type"], "rate_limit_exceeded")
            # Must retry bounded times (initial + 2 retries = 3 total post calls)
            self.assertEqual(mock_post.call_count, 3)
            # Sleep must have been called
            self.assertGreater(mock_sleep.call_count, 0)

    def test_06_quota_exhaustion_stops_immediately_without_pointless_retries(self):
        """Test that explicit quota exhaustion does not waste retries."""
        service = GroqService()
        service.max_retries = 3

        mock_quota = MagicMock()
        mock_quota.status_code = 429
        mock_quota.headers = {}
        mock_quota.json.return_value = {
            "error": {"message": "You exceeded your current quota, please check your plan.", "code": "insufficient_quota"}
        }

        with patch("services.groq_service.requests.post", return_value=mock_quota) as mock_post:
            success, err_msg, meta = service.call_chat_completion([{"role": "user", "content": "Hi"}])
            
            self.assertFalse(success)
            self.assertEqual(meta["error_type"], "quota_exhausted")
            self.assertIn("quota", err_msg.lower())
            # Should have stopped immediately on 1st attempt!
            self.assertEqual(mock_post.call_count, 1)

    def test_07_token_usage_and_metrics_recorded(self):
        """Test that token counts and usage metrics are logged to api_usage_metrics."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Token test explanation."}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 58, "total_tokens": 100}
        }

        with patch("services.groq_service.requests.post", return_value=mock_response):
            res = self.client.post("/api/chat", json={
                "message": "Token usage test query",
                "session_id": "token-metric-session"
            })
            self.assertEqual(res.status_code, 200)

        # Inspect api_usage_metrics in DB
        conn = get_db_connection()
        row = conn.execute(
            "SELECT * FROM api_usage_metrics WHERE event_type = 'api_success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["prompt_tokens"], 42)
        self.assertEqual(row["completion_tokens"], 58)
        self.assertEqual(row["total_tokens"], 100)

    def test_08_duplicate_submission_blocked(self):
        """Test in-flight deduplication guard prevents duplicate concurrent requests."""
        import hashlib
        from routes.chat_routes import _inflight_lock, _inflight_requests

        session_id = "concurrent-test-sess"
        msg = "Concurrent testing query"
        req_hash = hashlib.sha256(f"cache_test_user_1:{session_id}:{msg}".encode("utf-8")).hexdigest()

        # Simulate in-flight request lock
        with _inflight_lock:
            _inflight_requests.add(req_hash)

        try:
            res = self.client.post("/api/chat", json={
                "message": msg,
                "session_id": session_id
            })
            self.assertEqual(res.status_code, 429)
            self.assertTrue(res.get_json()["is_duplicate"])
        finally:
            with _inflight_lock:
                _inflight_requests.discard(req_hash)

    def test_09_unconfigured_api_key_returns_safe_error(self):
        """Test that unconfigured key returns 503 configuration_error without breaking."""
        service = GroqService()
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            success, err_msg, meta = service.call_chat_completion([{"role": "user", "content": "Hi"}])
            self.assertFalse(success)
            self.assertEqual(meta["error_type"], "configuration_error")
            self.assertIn("not configured", err_msg)

    def test_10_model_and_config_loading(self):
        """Test that default model is openai/gpt-oss-20b and env vars are dynamically read."""
        service = GroqService()
        with patch.dict(os.environ, {"GROQ_MODEL": ""}):
            self.assertEqual(service.model, "openai/gpt-oss-20b")

        with patch.dict(os.environ, {
            "GROQ_MODEL": "openai/gpt-oss-20b",
            "GROQ_MAX_TOKENS": "768",
            "GROQ_TIMEOUT": "30",
            "GROQ_MAX_RETRIES": "2"
        }):
            self.assertEqual(service.model, "openai/gpt-oss-20b")
            self.assertEqual(service.max_tokens, 768)
            self.assertEqual(service.timeout, 30)
            self.assertEqual(service.max_retries, 2)

    def test_11_reasoning_fallback_for_reasoning_models(self):
        """Test that reasoning content is used as fallback when content is empty."""
        service = GroqService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "", "reasoning": "Here is the reasoning explanation."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        }

        with patch("services.groq_service.requests.post", return_value=mock_response):
            success, text, meta = service.call_chat_completion([{"role": "user", "content": "Test"}])
            self.assertTrue(success)
            self.assertEqual(text, "Here is the reasoning explanation.")


if __name__ == "__main__":
    unittest.main()
