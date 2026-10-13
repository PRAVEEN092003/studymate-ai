import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

def get_db_path() -> str:
    """Return the currently configured database path from environment or default."""
    return os.getenv("DATABASE_PATH", "college_assistant.db")


def utc_now_iso() -> str:
    """Return timezone-aware current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def get_db_connection():
    """Create and return a thread-safe connection to the SQLite database."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def is_valid_session_id(session_id: str) -> bool:
    """Validate session ID format to prevent injection or invalid IDs."""
    if not session_id or not isinstance(session_id, str):
        return False
    return bool(re.match(r"^[a-zA-Z0-9_\-]{1,64}$", session_id.strip()))


def is_valid_email(email: str) -> bool:
    """Basic format validation for email addresses."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if len(email) < 5 or len(email) > 254:
        return False
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def init_db():
    """Initialize database tables and run automatic migrations if needed."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            normalized_email TEXT,
            password_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT DEFAULT 'College Study Session',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS response_cache (
            cache_key TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            response_text TEXT NOT NULL,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS api_usage_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            model TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT NOT NULL,
            attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS verified_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name TEXT NOT NULL,
            normalized_entity TEXT NOT NULL,
            category TEXT NOT NULL,
            fact_content TEXT NOT NULL,
            source_url TEXT,
            source_title TEXT,
            verified_at TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_cache_key ON response_cache(cache_key);
        CREATE INDEX IF NOT EXISTS idx_cache_expires ON response_cache(expires_at);
        CREATE INDEX IF NOT EXISTS idx_usage_event ON api_usage_metrics(event_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(identifier, attempt_time);
        CREATE INDEX IF NOT EXISTS idx_vk_entity ON verified_knowledge(normalized_entity);
        CREATE INDEX IF NOT EXISTS idx_vk_category ON verified_knowledge(category);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vk_unique ON verified_knowledge(normalized_entity, category);
    """)

    # Check and migrate users columns if database existed from earlier phases
    cursor.execute("PRAGMA table_info(users);")
    user_cols = [row["name"] for row in cursor.fetchall()]
    if "full_name" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT;")
    if "normalized_email" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN normalized_email TEXT;")
    if "password_hash" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT;")
    if "username" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT;")

    # Sync username and full_name for existing records if needed
    cursor.execute("UPDATE users SET full_name = username WHERE full_name IS NULL AND username IS NOT NULL;")
    cursor.execute("UPDATE users SET username = full_name WHERE username IS NULL AND full_name IS NOT NULL;")

    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_normalized_email ON users(normalized_email);")

    # Ensure response_cache has expires_at
    cursor.execute("PRAGMA table_info(response_cache);")
    cache_cols = [row["name"] for row in cursor.fetchall()]
    if "expires_at" not in cache_cols:
        cursor.execute("ALTER TABLE response_cache ADD COLUMN expires_at TIMESTAMP;")

    # Seed authoritative verified facts for Solamalai College of Engineering
    seed_facts = [
        (
            "Solamalai College of Engineering",
            "solamalai college of engineering",
            "overview",
            "Solamalai College of Engineering is an autonomous engineering institution located in Madurai, Tamil Nadu. It is approved by the All India Council for Technical Education (AICTE), New Delhi, and affiliated with Anna University, Chennai. The institution holds autonomous status.",
            "https://www.solamalaice.ac.in",
            "Solamalai College of Engineering - Official Website",
            "2026-10-12T00:00:00Z"
        ),
        (
            "Solamalai College of Engineering",
            "solamalai college of engineering",
            "establishment",
            "The institution was originally established in 1995 as Raja College of Engineering and Technology (RCET). It was subsequently acquired by the Solamalai Group in 2016 and renamed to Solamalai College of Engineering.",
            "https://www.solamalaice.ac.in",
            "Solamalai College of Engineering - About Institution",
            "2026-10-12T00:00:00Z"
        ),
        (
            "Solamalai College of Engineering",
            "solamalai college of engineering",
            "location",
            "The college campus is located at S.V. Raja Nagar, Sivagangai Main Road, Veerapanjan, Madurai, Tamil Nadu, PIN: 625020, India. Phone: 0452-2429346, +91-9698044566. Official email: info@solamalaice.ac.in.",
            "https://www.solamalaice.ac.in",
            "Solamalai College of Engineering - Campus & Contact",
            "2026-10-12T00:00:00Z"
        ),
        (
            "Solamalai College of Engineering",
            "solamalai college of engineering",
            "programs",
            "Undergraduate (UG) Programs (B.E./B.Tech): B.E. Computer Science and Engineering (CSE), B.E. CSE (Artificial Intelligence & Machine Learning), B.E. Electronics and Communication Engineering (ECE), B.E. Electrical and Electronics Engineering (EEE), B.E. Mechanical Engineering, B.E. Civil Engineering, B.E. Electronics Engineering (VLSI Design & Technology), B.Tech. Artificial Intelligence and Data Science (AI & DS), B.Tech. Computer Science and Business Systems (CSBS).\nPostgraduate (PG) Programs: M.E. Computer Science and Engineering, M.E. Embedded System Technologies, M.E. Soil Mechanics and Foundation Engineering, and Master of Business Administration (MBA).",
            "https://www.solamalaice.ac.in",
            "Solamalai College of Engineering - Academic Programs & Departments",
            "2026-10-12T00:00:00Z"
        ),
        (
            "Solamalai College of Engineering",
            "solamalai college of engineering",
            "fees_and_placements",
            "Current annual tuition fee schedules, hostel charges, and exact annual placement statistics are determined each academic year by institutional administration and government counselling authorities (TNEA/TANCET/Anna University). Students should verify current year numbers directly with the college admissions office (0452-2429346 / info@solamalaice.ac.in) or on www.solamalaice.ac.in.",
            "https://www.solamalaice.ac.in",
            "Solamalai College of Engineering - Admissions Information",
            "2026-10-12T00:00:00Z"
        )
    ]

    for fact in seed_facts:
        cursor.execute(
            """
            INSERT OR IGNORE INTO verified_knowledge
            (entity_name, normalized_entity, category, fact_content, source_url, source_title, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            fact
        )

    conn.commit()
    conn.close()


# ==============================================================================
# User Management Helpers
# ==============================================================================

def create_user(user_id: str, full_name: str, normalized_email: str, password_hash: str) -> Tuple[bool, str]:
    """Create a new user with hashed credentials in the SQLite database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        clean_name = full_name.strip()
        clean_email = normalized_email.strip().lower()
        now = utc_now_iso()

        cursor.execute("PRAGMA table_info(users);")
        user_cols = [row["name"] for row in cursor.fetchall()]

        if "username" in user_cols:
            cursor.execute(
                """
                INSERT INTO users (id, username, full_name, normalized_email, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, clean_name, clean_name, clean_email, password_hash, now)
            )
        else:
            cursor.execute(
                """
                INSERT INTO users (id, full_name, normalized_email, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, clean_name, clean_email, password_hash, now)
            )
        conn.commit()
        conn.close()
        return True, "User registered successfully."
    except sqlite3.IntegrityError as ie:
        conn.close()
        err_msg = str(ie).lower()
        if "unique" in err_msg and ("normalized_email" in err_msg or "email" in err_msg):
            return False, "An account with this email address already exists."
        return False, f"Database integrity error: {str(ie)}"
    except Exception as e:
        conn.close()
        return False, f"Database error during registration: {str(e)}"


def get_user_by_email(normalized_email: str) -> Optional[Dict]:
    """Retrieve user record by normalized email."""
    if not normalized_email or not isinstance(normalized_email, str):
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, full_name, normalized_email, password_hash, created_at FROM users WHERE normalized_email = ?",
        (normalized_email.strip().lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_user_by_id(user_id: str) -> Optional[Dict]:
    """Retrieve user record by user ID."""
    if not user_id or not isinstance(user_id, str):
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, full_name, normalized_email, password_hash, created_at FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


# ==============================================================================
# Login Rate Limiting Helpers
# ==============================================================================

def record_login_attempt(identifier: str):
    """Record a failed login attempt for an identifier (IP address or email)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO login_attempts (identifier, attempt_time) VALUES (?, ?)",
        (identifier[:128], utc_now_iso())
    )
    conn.commit()
    conn.close()


def get_recent_failed_attempts(identifier: str, window_seconds: int = 300) -> int:
    """Count failed login attempts for an identifier in the past window_seconds (default: 5 mins)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    cursor.execute(
        "SELECT COUNT(*) as count FROM login_attempts WHERE identifier = ? AND attempt_time >= ?",
        (identifier[:128], cutoff)
    )
    row = cursor.fetchone()
    count = row["count"] if row else 0
    conn.close()
    return count


def clear_login_attempts(identifier: str):
    """Clear failed login attempts upon successful login."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM login_attempts WHERE identifier = ?", (identifier[:128],))
    conn.commit()
    conn.close()


# ==============================================================================
# Usage Metrics & Cache Cleanup Helpers
# ==============================================================================

def record_usage_event(
    event_type: str,
    model: str = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    details: str = None
):
    """Record an internal usage metric event (cache_hit, api_success, api_error, rate_limit)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api_usage_metrics
            (event_type, model, prompt_tokens, completion_tokens, total_tokens, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                model,
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int(total_tokens or 0),
                details[:500] if details else None,
                utc_now_iso()
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Failed to record usage event: {e}")


def cleanup_expired_cache():
    """Remove expired cache records from the response cache table."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = utc_now_iso()
        cursor.execute(
            "DELETE FROM response_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted_count
    except Exception as e:
        print(f"Warning: Cache cleanup failed: {e}")
        return 0


# ==============================================================================
# User-Specific Session & Chat Helpers
# ==============================================================================

def ensure_session_exists(session_id: str, user_id: str = "guest_student") -> Tuple[bool, str]:
    """
    Ensure user and session exist with strict ownership validation.
    Returns (True, session_id) if authorized, or (False, error_msg) if owned by another user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Ensure user record exists for guest/test accounts
    cursor.execute("PRAGMA table_info(users);")
    user_cols = [r["name"] for r in cursor.fetchall()]
    if "username" in user_cols:
        cursor.execute(
            "INSERT OR IGNORE INTO users (id, username, full_name, normalized_email) VALUES (?, ?, ?, ?)",
            (user_id, "College Student", "College Student", f"{user_id}@student.local")
        )
    else:
        cursor.execute(
            "INSERT OR IGNORE INTO users (id, full_name, normalized_email) VALUES (?, ?, ?)",
            (user_id, "College Student", f"{user_id}@student.local")
        )

    # Check if session already exists
    cursor.execute("SELECT user_id FROM chat_sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()

    if row:
        # Enforce server-side ownership check
        if row["user_id"] != user_id:
            conn.close()
            return False, "Access denied: this session belongs to another user."
        conn.close()
        return True, session_id

    # Create new session associated with authenticated user
    now = utc_now_iso()
    cursor.execute(
        """
        INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, user_id, "College Study Session", now, now)
    )
    conn.commit()
    conn.close()
    return True, session_id


def save_message(message_id: str, session_id: str, role: str, content: str):
    """Save a single chat message to the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = utc_now_iso()
    cursor.execute(
        """
        INSERT INTO chat_messages (id, session_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (message_id, session_id, role, content, now)
    )
    cursor.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
        (now, session_id)
    )
    conn.commit()
    conn.close()


def get_recent_messages(session_id: str, limit: int = 6):
    """Retrieve the most recent messages for a session to construct limited context."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT role, content FROM chat_messages
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def get_all_sessions(user_id: str):
    """Retrieve only the chat sessions belonging to the authenticated user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.title, s.created_at, s.updated_at,
               COUNT(m.id) as message_count
        FROM chat_sessions s
        LEFT JOIN chat_messages m ON s.id = m.session_id
        WHERE s.user_id = ?
        GROUP BY s.id
        ORDER BY s.updated_at DESC
        """,
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": row["message_count"]
        }
        for row in rows
    ]


def get_session_messages(session_id: str, user_id: str = None) -> Optional[List[Dict]]:
    """
    Retrieve all messages for a session in chronological order.
    If user_id is provided, strictly validates session ownership first.
    Returns None if session does not belong to the user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if user_id:
        cursor.execute("SELECT user_id FROM chat_sessions WHERE id = ?", (session_id,))
        session_row = cursor.fetchone()
        if not session_row or session_row["user_id"] != user_id:
            conn.close()
            return None

    cursor.execute(
        """
        SELECT id, session_id, role, content, created_at
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"]
        }
        for row in rows
    ]


def update_session_title(session_id: str, title: str, user_id: str = None) -> bool:
    """Update title for a session, checking user ownership when user_id is provided."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if user_id:
        cursor.execute(
            "UPDATE chat_sessions SET title = ? WHERE id = ? AND user_id = ?",
            (title, session_id, user_id)
        )
    else:
        cursor.execute(
            "UPDATE chat_sessions SET title = ? WHERE id = ?",
            (title, session_id)
        )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def delete_session(session_id: str, user_id: str = None) -> bool:
    """
    Safely delete a session and all its messages.
    If user_id is specified, verifies ownership before deletion.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if user_id:
        cursor.execute("SELECT id FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return False

    cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


# ==============================================================================
# Verified Knowledge Base Helpers
# ==============================================================================

def normalize_entity_name(name: str) -> str:
    """Normalize an institution or entity name for consistent indexing and lookups."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def get_verified_facts(entity_name: str) -> List[Dict]:
    """Retrieve all verified facts for a specific institution or entity."""
    normalized = normalize_entity_name(entity_name)
    if not normalized:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT entity_name, category, fact_content, source_url, source_title, verified_at
        FROM verified_knowledge
        WHERE normalized_entity = ?
        ORDER BY id ASC
        """,
        (normalized,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_verified_knowledge(query_text: str) -> List[Dict]:
    """
    Search verified knowledge records matching an entity query.
    Detects known entities by full phrase or significant entity tokens.
    """
    if not query_text or not isinstance(query_text, str):
        return []
    normalized_q = normalize_entity_name(query_text)
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Exact entity phrase match
    cursor.execute(
        """
        SELECT entity_name, category, fact_content, source_url, source_title, verified_at
        FROM verified_knowledge
        WHERE ? LIKE '%' || normalized_entity || '%'
           OR normalized_entity LIKE '%' || ? || '%'
        ORDER BY id ASC
        """,
        (normalized_q, normalized_q)
    )
    rows = cursor.fetchall()

    # 2. Key entity token matching (e.g. 'solamalai')
    if not rows:
        tokens = [
            t for t in re.findall(r'[a-zA-Z]{4,}', normalized_q)
            if t not in ('what', 'where', 'when', 'which', 'tell', 'about', 'college',
                         'engineering', 'university', 'institute', 'details', 'campus')
        ]
        for token in tokens:
            cursor.execute(
                """
                SELECT entity_name, category, fact_content, source_url, source_title, verified_at
                FROM verified_knowledge
                WHERE normalized_entity LIKE '%' || ? || '%'
                ORDER BY id ASC
                """,
                (token,)
            )
            found = cursor.fetchall()
            if found:
                rows = found
                break

    conn.close()
    return [dict(r) for r in rows]


def insert_verified_fact(
    entity_name: str,
    category: str,
    fact_content: str,
    source_url: str = None,
    source_title: str = None,
    verified_at: str = None
) -> bool:
    """
    Insert or update a verified fact record.
    Preserves auditability with verified_at timestamp and source reference.
    """
    if not entity_name or not category or not fact_content:
        return False
    normalized = normalize_entity_name(entity_name)
    v_time = verified_at or utc_now_iso()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO verified_knowledge
            (entity_name, normalized_entity, category, fact_content, source_url, source_title, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_entity, category) DO UPDATE SET
                fact_content = excluded.fact_content,
                source_url = excluded.source_url,
                source_title = excluded.source_title,
                verified_at = excluded.verified_at
            """,
            (entity_name.strip(), normalized, category.strip(), fact_content.strip(), source_url, source_title, v_time)
        )
        conn.commit()
        success = True
    except Exception:
        success = False
    finally:
        conn.close()
    return success
