import os
import hashlib
import json
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from database.db import get_db_connection, cleanup_expired_cache

DEFAULT_CACHE_TTL_SECONDS = 86400  # 24 hours


def get_cache_ttl() -> int:
    """Read cache expiration TTL in seconds from environment configuration."""
    try:
        return int(os.getenv("CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def generate_cache_key(
    question: str,
    context: List[Dict[str, str]],
    model: str,
    prompt_version: str,
    grounding_context: Optional[str] = None
) -> str:
    """
    Generate a deterministic SHA-256 hash key using:
    - Cleaned, whitespace-collapsed question text
    - Normalized conversation context history turns
    - Target model identifier
    - System prompt version identifier
    - Grounding context (verified facts / source context)
    """
    normalized_question = " ".join(question.strip().lower().split())

    # Normalize context into a stable structure
    normalized_context = [
        {
            "role": msg.get("role", "").strip().lower(),
            "content": " ".join(msg.get("content", "").strip().split())
        }
        for msg in context
    ]

    payload = {
        "question": normalized_question,
        "context": normalized_context,
        "model": model.strip().lower(),
        "prompt_version": prompt_version.strip()
    }
    if grounding_context and grounding_context.strip():
        payload["grounding_context"] = " ".join(grounding_context.strip().split())

    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_cached_response(cache_key: str) -> Optional[str]:
    """
    Retrieve response from SQLite cache if present and unexpired.
    Does not serve expired entries.
    """
    # Lightweight opportunistic cleanup (roughly 1 in 10 requests)
    if random.random() < 0.1:
        cleanup_expired_cache()

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT response_text, expires_at 
        FROM response_cache 
        WHERE cache_key = ?
        """,
        (cache_key,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    # Check expiration
    expires_at = row["expires_at"]
    if expires_at and expires_at < now:
        # Cache entry has expired - purge it
        cursor.execute("DELETE FROM response_cache WHERE cache_key = ?", (cache_key,))
        conn.commit()
        conn.close()
        return None

    conn.close()
    return row["response_text"]


def store_cached_response(
    cache_key: str,
    prompt: str,
    model: str,
    prompt_version: str,
    response_text: str
):
    """
    Store successful, valid response in SQLite cache with an expiration timestamp.
    Never caches empty or failed responses.
    """
    if not response_text or not response_text.strip():
        return

    ttl_seconds = get_cache_ttl()
    now_dt = datetime.now(timezone.utc)
    expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()
    created_at = now_dt.isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO response_cache
        (cache_key, prompt, model, prompt_version, response_text, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (cache_key, prompt, model, prompt_version, response_text, expires_at, created_at)
    )
    conn.commit()
    conn.close()
