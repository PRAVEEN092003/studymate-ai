import os
import uuid
import hashlib
import logging
import threading
from flask import Blueprint, request, jsonify, session
from database.db import (
    ensure_session_exists,
    save_message,
    get_recent_messages,
    get_db_connection,
    get_all_sessions,
    get_session_messages,
    update_session_title,
    delete_session,
    is_valid_session_id,
    record_usage_event
)
from services.groq_service import GroqService
from services.cache_service import generate_cache_key, get_cached_response, store_cached_response
from services.search_service import retrieve_grounding_context, try_direct_verified_answer
from routes.auth_routes import login_required

chat_bp = Blueprint("chat_bp", __name__)
groq_service = GroqService()
logger = logging.getLogger(__name__)

# Concurrency lock & in-flight set to prevent duplicate requests from repeated submissions
_inflight_lock = threading.Lock()
_inflight_requests = set()

ACADEMIC_SYSTEM_PROMPT = (
    "You are StudyMate AI, an encouraging, knowledgeable, and rigorously accurate college study companion.\n\n"
    "Core Capabilities:\n"
    "- Academic doubts, conceptual breakdowns, derivations, and theoretical fundamentals across disciplines.\n"
    "- Programming guidance, debugging, code snippets, and syntax explanations.\n"
    "- Assignment and coursework conceptual support without generating turnkey academic integrity violations.\n"
    "- Exam preparation, revision summaries, flashcard-style reviews, and model question answers.\n\n"
    "Factual Accuracy & Anti-Hallucination Directives:\n"
    "1. NEVER invent factual details, dates, locations, campus addresses, statistics, course offerings, fees, placement figures, or institutional history.\n"
    "2. NEVER confuse or conflate similarly named colleges, universities, or institutions. Verify the exact entity before answering.\n"
    "3. Clearly distinguish verified facts from general educational explanations and uncertain or unverified claims.\n"
    "4. If reliable, verified information for an institution is unavailable, explicitly state that it could not be verified. Direct the student to check official administrative portals or websites.\n"
    "5. NEVER claim that a website, document, or source was checked unless it was actually retrieved and provided in the Grounding Context.\n"
    "6. When verified grounding facts are provided under <VERIFIED_GROUNDING_CONTEXT>, rely strictly on them for institutional facts and include clickable Markdown links ([Source Title](url)) for the verified primary sources provided.\n"
    "7. Question Length & Examination Marks Standards:\n"
    "   - 2-mark questions: Provide concise definitions, core formulas, or 2 key points (~30-60 words).\n"
    "   - 5-mark questions: Provide a structured explanation with 4-5 key bullet points or a brief schematic description (~150-250 words).\n"
    "   - 10-mark questions: Provide an in-depth comprehensive analysis with introduction, architecture/components, working principle, advantages/disadvantages, and code/example where applicable (~350-500 words).\n"
    "8. Do not let these accuracy constraints restrict standard conceptual educational assistance, mathematics, science explanations, algorithms, or programming assistance."
)


def generate_short_title(text: str) -> str:
    """Generate a clean, concise title from the user's first query without calling an LLM."""
    clean_text = " ".join(text.strip().split())
    if len(clean_text) <= 36:
        return clean_text.capitalize()
    return clean_text[:33].strip().capitalize() + "..."


@chat_bp.route("/api/health", methods=["GET"])
def health_check():
    """Minimal public health and status check (zero Groq API requests consumed, no secrets exposed)."""
    db_status = "unhealthy"
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1;").fetchone()
        conn.close()
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return jsonify({
        "status": "online",
        "database": db_status,
        "groq_service_configured": groq_service.is_configured(),
        "model": groq_service.model
    }), 200


@chat_bp.route("/api/sessions", methods=["GET"])
@login_required
def list_sessions():
    """Retrieve all chat sessions strictly belonging to the authenticated user."""
    user_id = session.get("user_id")
    try:
        sessions = get_all_sessions(user_id=user_id)
        return jsonify({
            "success": True,
            "sessions": sessions
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to retrieve conversations."
        }), 500


@chat_bp.route("/api/sessions/<session_id>/messages", methods=["GET"])
@login_required
def get_session_history(session_id: str):
    """Retrieve chronological message history for a specific session with strict user ownership validation."""
    if not is_valid_session_id(session_id):
        return jsonify({
            "success": False,
            "error": "Invalid session identifier format."
        }), 400

    user_id = session.get("user_id")
    try:
        messages = get_session_messages(session_id, user_id=user_id)
        if messages is None:
            return jsonify({
                "success": False,
                "error": "Conversation not found."
            }), 403

        return jsonify({
            "success": True,
            "session_id": session_id,
            "messages": messages
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to retrieve conversation messages."
        }), 500


@chat_bp.route("/api/sessions/<session_id>", methods=["DELETE"])
@login_required
def remove_session(session_id: str):
    """Safely delete a chat session and associated messages, enforcing user ownership."""
    if not is_valid_session_id(session_id):
        return jsonify({
            "success": False,
            "error": "Invalid session identifier format."
        }), 400

    user_id = session.get("user_id")
    try:
        deleted = delete_session(session_id, user_id=user_id)
        if not deleted:
            return jsonify({
                "success": False,
                "error": "Unable to delete conversation."
            }), 403

        return jsonify({
            "success": True,
            "deleted": True,
            "session_id": session_id
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to delete conversation."
        }), 500


@chat_bp.route("/api/chat", methods=["POST"])
@login_required
def chat():
    """Chat endpoint supporting conversation context, caching, deduplication, and user isolation."""
    user_id = session.get("user_id")

    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Invalid request body. JSON payload is required."
        }), 400

    raw_message = data.get("message")
    if not raw_message or not isinstance(raw_message, str):
        return jsonify({
            "success": False,
            "error": "The 'message' field is required and must be a non-empty string."
        }), 400

    message = raw_message.strip()
    if not message:
        return jsonify({
            "success": False,
            "error": "Message cannot be empty."
        }), 400

    max_length = int(os.getenv("MAX_MESSAGE_LENGTH", "4000"))
    if len(message) > max_length:
        return jsonify({
            "success": False,
            "error": f"Message exceeds the maximum permitted length of {max_length} characters."
        }), 400

    # Session management & validation
    raw_session_id = data.get("session_id")
    if not raw_session_id or not isinstance(raw_session_id, str) or not raw_session_id.strip():
        session_id = str(uuid.uuid4())
    else:
        session_id = raw_session_id.strip()

    if not is_valid_session_id(session_id):
        return jsonify({
            "success": False,
            "error": "Invalid session identifier format."
        }), 400

    # Enforce server-side user-session association
    ok, session_or_err = ensure_session_exists(session_id, user_id=user_id)
    if not ok:
        return jsonify({
            "success": False,
            "error": session_or_err
        }), 403

    # Deduplication guard: prevent identical duplicate requests in-flight per user
    request_hash = hashlib.sha256(f"{user_id}:{session_id}:{message}".encode("utf-8")).hexdigest()
    with _inflight_lock:
        if request_hash in _inflight_requests:
            return jsonify({
                "success": False,
                "error": "You're temporarily unable to send a message. Please try again shortly.",
                "is_duplicate": True
            }), 429
        _inflight_requests.add(request_hash)

    try:
        # Check existing message count to generate zero-cost first-message title
        existing_messages = get_session_messages(session_id, user_id=user_id) or []
        session_title = None
        if len(existing_messages) == 0:
            session_title = generate_short_title(message)
            update_session_title(session_id, session_title, user_id=user_id)

        # Retrieve limited conversation history from env config
        max_history_turns = int(os.getenv("MAX_HISTORY_TURNS", "4"))
        history = get_recent_messages(session_id, limit=max_history_turns)

        # Check factual grounding requirements
        grounding = retrieve_grounding_context(message)
        grounding_context_text = grounding.get("context_prompt", "") if grounding.get("requires_grounding") else None

        # Check if query can be answered directly from verified knowledge (saves unnecessary Groq API call!)
        direct_answer = None
        if grounding.get("requires_grounding") and grounding.get("has_verified_sources"):
            direct_answer = try_direct_verified_answer(message, grounding.get("facts", []), grounding.get("sources", []))

        prompt_version = os.getenv("PROMPT_VERSION", "v2.0")
        cache_key = generate_cache_key(
            question=message,
            context=history,
            model=groq_service.model,
            prompt_version=prompt_version,
            grounding_context=grounding_context_text
        )

        if direct_answer:
            user_msg_id = str(uuid.uuid4())
            assistant_msg_id = str(uuid.uuid4())
            save_message(user_msg_id, session_id, "user", message)
            save_message(assistant_msg_id, session_id, "assistant", direct_answer)

            store_cached_response(
                cache_key=cache_key,
                prompt=message,
                model=groq_service.model,
                prompt_version=prompt_version,
                response_text=direct_answer
            )

            record_usage_event(
                event_type="verified_kb_direct",
                model="verified_knowledge_base",
                details="Direct verified knowledge response served"
            )

            return jsonify({
                "success": True,
                "response": direct_answer,
                "session_id": session_id,
                "session_title": session_title,
                "cached": False,
                "verified_grounded": True
            }), 200

        # 1. Check SQLite response cache before calling Groq
        cached_content = get_cached_response(cache_key)
        if cached_content:
            user_msg_id = str(uuid.uuid4())
            assistant_msg_id = str(uuid.uuid4())
            save_message(user_msg_id, session_id, "user", message)
            save_message(assistant_msg_id, session_id, "assistant", cached_content)

            record_usage_event(
                event_type="cache_hit",
                model=groq_service.model,
                details="Response served from SQLite cache"
            )

            return jsonify({
                "success": True,
                "response": cached_content,
                "session_id": session_id,
                "session_title": session_title,
                "cached": True
            }), 200

        # 2. Formulate payload for Groq
        system_content = ACADEMIC_SYSTEM_PROMPT
        if grounding_context_text:
            system_content += f"\n\n{grounding_context_text}"

        groq_messages = [{"role": "system", "content": system_content}]
        groq_messages.extend(history)
        groq_messages.append({"role": "user", "content": message})

        # 3. Call Groq API
        success, response_text, meta = groq_service.call_chat_completion(groq_messages)

        if not success:
            status_code = meta.get("status_code", 500)
            is_rate_limit = meta.get("error_type") in ("rate_limit_exceeded", "quota_exhausted")

            record_usage_event(
                event_type="rate_limit" if is_rate_limit else "api_error",
                model=groq_service.model,
                details=response_text
            )

            logger.warning(
                "AI response generation failed for session %s (status %s, type %s): %s",
                session_id,
                status_code,
                meta.get("error_type", "unknown"),
                response_text
            )

            if is_rate_limit:
                friendly_error = "You're temporarily unable to send a message. Please try again shortly."
            else:
                friendly_error = "Response couldn't be generated. Please try again."

            return jsonify({
                "success": False,
                "error": friendly_error,
                "session_id": session_id,
                "is_rate_limit": is_rate_limit
            }), status_code if 400 <= status_code < 600 else 500

        # 4. Save to DB and response cache
        user_msg_id = str(uuid.uuid4())
        assistant_msg_id = str(uuid.uuid4())
        save_message(user_msg_id, session_id, "user", message)
        save_message(assistant_msg_id, session_id, "assistant", response_text)

        record_usage_event(
            event_type="api_success",
            model=groq_service.model,
            prompt_tokens=meta.get("prompt_tokens", 0),
            completion_tokens=meta.get("completion_tokens", 0),
            total_tokens=meta.get("total_tokens", 0)
        )

        store_cached_response(
            cache_key=cache_key,
            prompt=message,
            model=groq_service.model,
            prompt_version=prompt_version,
            response_text=response_text
        )

        return jsonify({
            "success": True,
            "response": response_text,
            "session_id": session_id,
            "session_title": session_title,
            "cached": False
        }), 200

    finally:
        with _inflight_lock:
            _inflight_requests.discard(request_hash)
