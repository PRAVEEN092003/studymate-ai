import os
import re
import logging
from typing import Dict, Any, List, Optional
from database.db import search_verified_knowledge

logger = logging.getLogger(__name__)

INSTITUTION_KEYWORDS = {
    "college", "university", "institute", "campus", "polytechnic", "academy",
    "autonomous", "affiliation", "affiliated", "aicte", "anna university",
    "admissions", "admission", "cutoff", "cut-off", "fees", "fee structure",
    "tuition", "hostel", "placement", "placements", "highest package", "average package",
    "courses offered", "departments", "departments offered", "principal", "dean",
    "contact number", "address", "location", "established", "establishment",
    "accreditation", "naac", "nba", "ranking", "nirf", "tnea", "tancet"
}


def is_institution_or_factual_query(query: str) -> bool:
    """
    Determine if a user query requires institutional or verifiable factual grounding.
    Avoids triggering grounding logic on standard conceptual, mathematical,
    algorithmic, or programming questions.
    """
    if not query or not isinstance(query, str):
        return False

    q_lower = query.lower()
    tokens = set(re.findall(r'[a-zA-Z0-9_\-]+', q_lower))

    # Fast check: does it contain an institution-related keyword?
    if tokens & INSTITUTION_KEYWORDS:
        return True

    # Check multi-word keywords
    for kw in ("fee structure", "cut-off", "courses offered", "anna university", "solamalai"):
        if kw in q_lower:
            return True

    return False


def retrieve_grounding_context(query: str) -> Dict[str, Any]:
    """
    Retrieve grounding context from the verified knowledge base and optional web search.

    Returns:
        Dict with keys:
            - requires_grounding (bool): Whether query involves institutional/factual specifics
            - has_verified_sources (bool): Whether reliable records or primary sources were found
            - facts (List[Dict]): Retrieved fact records
            - sources (List[Dict]): Authoritative sources with title and URL
            - context_prompt (str): Text block to inject into the system/user prompt
    """
    if not is_institution_or_factual_query(query):
        return {
            "requires_grounding": False,
            "has_verified_sources": False,
            "facts": [],
            "sources": [],
            "context_prompt": ""
        }

    # 1. Check local Verified Knowledge Base (SQLite)
    verified_records = search_verified_knowledge(query)

    if verified_records:
        facts = []
        sources = []
        seen_urls = set()

        for rec in verified_records:
            facts.append({
                "entity": rec.get("entity_name"),
                "category": rec.get("category"),
                "content": rec.get("fact_content"),
                "source_url": rec.get("source_url"),
                "source_title": rec.get("source_title"),
                "verified_at": rec.get("verified_at")
            })
            url = rec.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "title": rec.get("source_title") or rec.get("entity_name"),
                    "url": url
                })

        # Build grounded context prompt
        entity_name = verified_records[0].get("entity_name", "Institution")
        facts_lines = []
        for f in facts:
            cat = f["category"].replace("_", " ").title()
            facts_lines.append(f"- [{cat}]: {f['content']}")

        source_lines = []
        for s in sources:
            source_lines.append(f"- [{s['title']}]({s['url']})")

        context_prompt = (
            f"\n<VERIFIED_GROUNDING_CONTEXT>\n"
            f"The following verified factual records were retrieved for '{entity_name}':\n"
            + "\n".join(facts_lines) + "\n\n"
            + "Authoritative Primary Sources:\n"
            + "\n".join(source_lines) + "\n"
            + "INSTRUCTIONS:\n"
            + "1. Rely strictly on these verified facts for institutional details.\n"
            + "2. Never invent dates, programs, affiliations, fees, or placements outside these facts.\n"
            + "3. Include the clickable source markdown links from the primary sources list in your response.\n"
            + "4. If asked about current fees or annual statistics not fully specified, advise consulting the official website or admissions office.\n"
            + "</VERIFIED_GROUNDING_CONTEXT>\n"
        )

        return {
            "requires_grounding": True,
            "has_verified_sources": True,
            "facts": facts,
            "sources": sources,
            "context_prompt": context_prompt
        }

    # 2. If not in local verified KB, check optional external web search if enabled
    web_search_enabled = os.getenv("WEB_SEARCH_ENABLED", "False").lower() in ("true", "1", "t")
    if web_search_enabled:
        # Note: If external search provider is configured in future, query it here safely.
        logger.info("External web search check for query: %s", query[:50])

    # 3. No verified facts found for this institution query
    unverified_prompt = (
        "\n<VERIFIED_GROUNDING_CONTEXT>\n"
        "Grounding Status: UNVERIFIED.\n"
        "No verified records or primary sources could be found in the knowledge base for the institution queried.\n"
        "STRICT ACCURACY RULES:\n"
        "1. You MUST explicitly inform the student that reliable, verified information for this specific institution is unavailable in the database.\n"
        "2. Do NOT invent or guess establishment years, locations, courses, fees, rankings, or placement figures.\n"
        "3. Do NOT confuse or conflate this institution with similarly named colleges.\n"
        "4. Never fabricate citations or URLs.\n"
        "5. Politely advise the student to consult the institution's official website or Anna University/AICTE portal directly.\n"
        "</VERIFIED_GROUNDING_CONTEXT>\n"
    )

    return {
        "requires_grounding": True,
        "has_verified_sources": False,
        "facts": [],
        "sources": [],
        "context_prompt": unverified_prompt
    }


def try_direct_verified_answer(query: str, facts: List[Dict], sources: List[Dict]) -> Optional[str]:
    """
    Directly answer simple factual lookup queries using verified knowledge records,
    saving unnecessary Groq LLM API calls and avoiding latency/quota consumption.
    Returns None if the query requires conversational synthesis, comparison, or general explanation.
    """
    if not facts or not query:
        return None

    q_lower = query.lower()
    entity_name = facts[0].get("entity") or facts[0].get("entity_name") or "the institution"

    # 1. Location / Address / Contact
    if any(k in q_lower for k in ("where is", "location of", "address of", "campus address", "contact number", "pin code", "how to contact")):
        for f in facts:
            if f.get("category") == "location":
                content = f.get("fact_content") or f.get("content") or ""
                src = f.get("source_url")
                src_link = f"\n\n**Official Source:** [{f.get('source_title', 'Official Website')}]({src})" if src else ""
                return f"**{entity_name} — Location & Contact Information**\n\n{content}{src_link}"

    # 2. Establishment / History / Former Name
    if any(k in q_lower for k in ("established", "establishment", "founded", "history of", "former name", "old name", "when was")):
        for f in facts:
            if f.get("category") == "establishment":
                content = f.get("fact_content") or f.get("content") or ""
                src = f.get("source_url")
                src_link = f"\n\n**Official Source:** [{f.get('source_title', 'Official Website')}]({src})" if src else ""
                return f"**{entity_name} — Establishment & History**\n\n{content}{src_link}"

    # 3. Courses / Programs / Degrees offered
    if any(k in q_lower for k in ("what courses", "courses offered", "programs offered", "degrees offered", "branches available", "departments offered", "list of courses")):
        for f in facts:
            if f.get("category") == "programs":
                content = f.get("fact_content") or f.get("content") or ""
                src = f.get("source_url")
                src_link = f"\n\n**Official Source:** [{f.get('source_title', 'Official Website')}]({src})" if src else ""
                return f"**{entity_name} — Academic Programs Offered**\n\n{content}{src_link}"

    return None

