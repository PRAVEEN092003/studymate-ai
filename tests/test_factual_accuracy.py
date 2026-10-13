import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock

# Setup isolated test database before importing app
temp_db = tempfile.NamedTemporaryFile(delete=False, suffix="_accuracy.db")
temp_db_path = temp_db.name
temp_db.close()

os.environ["DATABASE_PATH"] = temp_db_path
os.environ["GROQ_API_KEY"] = "mock_accuracy_key"
os.environ["PROMPT_VERSION"] = "v2.0"

from app import create_app
from database.db import (
    init_db,
    get_db_connection,
    get_verified_facts,
    search_verified_knowledge,
    insert_verified_fact
)
from services.search_service import (
    is_institution_or_factual_query,
    retrieve_grounding_context,
    try_direct_verified_answer
)
from services.cache_service import generate_cache_key
from routes.chat_routes import ACADEMIC_SYSTEM_PROMPT


class FactualAccuracyTestCase(unittest.TestCase):
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
        conn = get_db_connection()
        conn.execute(
            "INSERT OR IGNORE INTO users (id, full_name, normalized_email, password_hash) VALUES (?, ?, ?, ?)",
            ("acc_user_1", "Accuracy Tester", "acc@test.local", "hash123")
        )
        conn.commit()
        conn.close()

        with self.client.session_transaction() as sess:
            sess["user_id"] = "acc_user_1"
            sess["user_name"] = "Accuracy Tester"
            sess["user_email"] = "acc@test.local"
            sess["_csrf_token"] = "valid_csrf"

    def test_01_solamalai_facts_seeded_and_accurate(self):
        """Verify that Solamalai facts are accurately stored in SQLite without guessed details."""
        facts = get_verified_facts("Solamalai College of Engineering")
        self.assertGreaterEqual(len(facts), 4)

        categories = {f["category"]: f for f in facts}
        self.assertIn("location", categories)
        self.assertIn("establishment", categories)
        self.assertIn("programs", categories)
        self.assertIn("overview", categories)

        # Verify location accuracy (Madurai, 625020, Veerapanjan)
        loc = categories["location"]["fact_content"]
        self.assertIn("Madurai", loc)
        self.assertIn("625020", loc)
        self.assertIn("Veerapanjan", loc)

        # Verify establishment accuracy (1995, Raja College, 2016 Solamalai Group)
        est = categories["establishment"]["fact_content"]
        self.assertIn("1995", est)
        self.assertIn("Raja College", est)
        self.assertIn("2016", est)

        # Verify URL is official
        for f in facts:
            self.assertEqual(f["source_url"], "https://www.solamalaice.ac.in")

    def test_02_direct_verified_answer_bypasses_groq(self):
        """Verify that direct simple queries retrieve verified facts with sources without calling Groq."""
        query = "Where is Solamalai College of Engineering located?"
        facts = search_verified_knowledge(query)
        self.assertTrue(len(facts) > 0)

        sources = [{"title": f["source_title"], "url": f["source_url"]} for f in facts]
        direct_resp = try_direct_verified_answer(query, facts, sources)

        self.assertIsNotNone(direct_resp)
        self.assertIn("Madurai", direct_resp)
        self.assertIn("625020", direct_resp)
        self.assertIn("https://www.solamalaice.ac.in", direct_resp)

    def test_03_similar_institution_names_not_conflated(self):
        """Verify that searching for distinct or similarly named colleges does not return Solamalai facts."""
        # Query for Thiagarajar College of Engineering
        results = search_verified_knowledge("Tell me about Thiagarajar College of Engineering")
        self.assertEqual(len(results), 0)

        # Query for PSNA College
        results_psna = search_verified_knowledge("Where is PSNA College of Engineering located?")
        self.assertEqual(len(results_psna), 0)

    def test_04_missing_sources_returns_unverified_status(self):
        """Verify that unknown institutions trigger unverified status instead of guessed facts."""
        grounding = retrieve_grounding_context("What is the fee structure at Nonexistent Antarctic University?")
        self.assertTrue(grounding["requires_grounding"])
        self.assertFalse(grounding["has_verified_sources"])
        self.assertIn("UNVERIFIED", grounding["context_prompt"])
        self.assertIn("explicitly inform the student that reliable, verified information", grounding["context_prompt"])

    def test_05_citations_only_for_retrieved_sources(self):
        """Verify that citations are included only when verified sources are present."""
        # Standard coding question: no grounding or fabricated citations
        grounding_code = retrieve_grounding_context("How do I write a binary search in Python?")
        self.assertFalse(grounding_code["requires_grounding"])
        self.assertEqual(len(grounding_code["sources"]), 0)

        # Institutional question: authoritative citations present
        grounding_inst = retrieve_grounding_context("What courses are offered at Solamalai College of Engineering?")
        self.assertTrue(grounding_inst["has_verified_sources"])
        self.assertTrue(len(grounding_inst["sources"]) > 0)
        for s in grounding_inst["sources"]:
            self.assertTrue(s["url"].startswith("https://www.solamalaice.ac.in"))

    def test_06_prompt_version_change_invalidates_cache(self):
        """Verify that changing system prompt version produces different cache keys."""
        q = "Explain Ohm's law."
        ctx = []
        model = "openai/gpt-oss-20b"

        key_v1 = generate_cache_key(q, ctx, model, "v1.0")
        key_v2 = generate_cache_key(q, ctx, model, "v2.0")

        self.assertNotEqual(key_v1, key_v2)

        # Grounded context also alters cache key
        key_grounded = generate_cache_key(q, ctx, model, "v2.0", grounding_context="Solamalai info")
        self.assertNotEqual(key_v2, key_grounded)

    def test_07_system_prompt_rules_and_mark_standards(self):
        """Verify system prompt contains all anti-hallucination rules and mark length guidelines."""
        self.assertIn("NEVER invent factual details", ACADEMIC_SYSTEM_PROMPT)
        self.assertIn("NEVER confuse or conflate similarly named colleges", ACADEMIC_SYSTEM_PROMPT)
        self.assertIn("2-mark questions", ACADEMIC_SYSTEM_PROMPT)
        self.assertIn("5-mark questions", ACADEMIC_SYSTEM_PROMPT)
        self.assertIn("10-mark questions", ACADEMIC_SYSTEM_PROMPT)
        self.assertIn("<VERIFIED_GROUNDING_CONTEXT>", ACADEMIC_SYSTEM_PROMPT)

    def test_08_post_chat_direct_verified_knowledge_response(self):
        """Verify that POST /api/chat serves direct verified factual answer with source."""
        res = self.client.post("/api/chat", json={
            "message": "Where is Solamalai College of Engineering located?",
            "session_id": "direct-kb-session-1"
        }, headers={"X-CSRF-Token": "valid_csrf"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("Madurai", data["response"])
        self.assertIn("625020", data["response"])
        self.assertIn("https://www.solamalaice.ac.in", data["response"])
        self.assertTrue(data.get("verified_grounded"))

    def test_09_general_queries_not_erroneously_grounded(self):
        """Verify standard math or CS problems do not trigger institutional grounding."""
        self.assertFalse(is_institution_or_factual_query("Explain Dijkstra's algorithm step by step."))
        self.assertFalse(is_institution_or_factual_query("How to solve quadratic equations?"))
        self.assertFalse(is_institution_or_factual_query("Write a React component for a timer."))


if __name__ == "__main__":
    unittest.main()
