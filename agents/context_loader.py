"""
Context Loader Agent — V8

V8 changes: Removed SentenceTransformer embedding model.
History relevance ranking uses keyword overlap instead of cosine similarity.
Entity tracking and coreference resolution remain unchanged.
"""
import re
import numpy as np
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import get_settings
from state.context import GraphState
from utils.glossary_matcher import find_matches
from utils.permissions import get_permitted_tables, get_role_display

_REFERENCE_PATTERN = re.compile(
    r"\b(it|its|they|them|their|those|these|that|this|"
    r"same|similar|such|the previous|the last|the above|"
    r"those cases|that query|same filter|same status|"
    r"what about|how about)\b"
    r"|^\s*and\b",
    re.IGNORECASE,
)

_ENTITY_PATTERNS = {
    "time_range": re.compile(
        r"\b(today|yesterday|this month|last month|this week|last week|"
        r"this year|last year|mtd|ytd|q[1-4]|last \d+ days|past \d+ days|"
        r"since \w+|20\d{2}|january|february|march|april|may|june|july|"
        r"august|september|october|november|december)\b", re.IGNORECASE),
    "status_filter": re.compile(
        r"\b(open|closed|pending|ineligible|eligible|active|terminal|"
        r"INITIAL_ELIGIBILITY_REVIEW|PENDING_PAYMENTS|PENDING_SECOND_PAYMENT|"
        r"FINAL_ELIGIBILITY_REVIEW|PENDING_RFI|FINAL_DETERMINATION_RENDERED|"
        r"CLOSED_DEFAULT|CLOSED_ADMINISTRATIVE|CLOSED_INITIATING_PARTY|"
        r"CLOSED_NON_INITIATING_PARTY|CLOSED_SPLIT_DECISION)\b", re.IGNORECASE),
    "org_name": re.compile(
        r"\b(UHC|UnitedHealth(?:care)?|HaloMD|Halo MD|PacificHealth|"
        r"Capitol Bridge|VeraTru|Aetna|Cigna|Anthem|Humana|BCBS|"
        r"Blue Cross|Kaiser|Molina|Centene|Radix)\b", re.IGNORECASE),
    "person_name": re.compile(
        r"\b(?:assigned to|closed by|arbitrator|specialist)\s+(\w+ \w+)\b", re.IGNORECASE),
    "dispute_type": re.compile(r"\b(SINGLE|BUNDLED|BATCHED)\b", re.IGNORECASE),
    "payment_type": re.compile(
        r"\b(CASE_PAYMENT|REFUND|CAPITOL_BRIDGE_FEE|CMS_INVOICE|"
        r"THIRD_PARTY_PAYMENT|PARTY_REFUND|incoming|outgoing)\b", re.IGNORECASE),
}

def _get_relevant_history(query: str, history: list[dict], top_k: int = 3) -> list[dict]:
    """Keyword-overlap history ranking (no embedding model needed)."""
    if not history or len(history) <= top_k:
        return history

    query_words = set(query.lower().split())
    scores = []
    for i, h in enumerate(history):
        turn_text = f"{h.get('query', '')} {h.get('summary', '')}".lower()
        turn_words = set(turn_text.split())
        overlap = len(query_words & turn_words)
        scores.append((overlap, i))

    scores.sort(reverse=True)
    selected_indices = sorted([idx for _, idx in scores[:top_k]])
    return [history[i] for i in selected_indices]


def _extract_entities(query: str) -> dict[str, str]:
    entities = {}
    for entity_type, pattern in _ENTITY_PATTERNS.items():
        match = pattern.search(query)
        if match:
            entities[entity_type] = match.group(0).strip()
    return entities


def _update_entity_registry(existing: dict, new_entities: dict) -> dict:
    registry = dict(existing or {})
    registry.update(new_entities)
    return registry


def _resolve_from_registry(query: str, registry: dict) -> tuple[str, bool]:
    if not registry:
        return query, False

    resolved = query
    changed = False
    replacements = {
        r"\bthose cases\b": registry.get("status_filter", ""),
        r"\bthat org(?:anization)?\b": registry.get("org_name", ""),
        r"\bsame (?:time|period|date range)\b": registry.get("time_range", ""),
        r"\bsame status\b": registry.get("status_filter", ""),
        r"\bsame type\b": registry.get("dispute_type", ""),
        r"\bthat payment type\b": registry.get("payment_type", ""),
    }
    for pattern, replacement in replacements.items():
        if replacement and re.search(pattern, resolved, re.IGNORECASE):
            resolved = re.sub(pattern, replacement, resolved, flags=re.IGNORECASE)
            changed = True

    return resolved, changed


SYSTEM_PROMPT = """You are a query resolver for a data analytics chatbot about dispute resolution cases.

Given a short conversation history and a new user message, rewrite the message as a \
fully self-contained question that can be understood with no prior context.

Rules:
- Resolve pronouns: "it", "those", "them", "that" → the specific entity from history.
- Resolve references: "same filter", "same status", "those cases" → repeat the exact condition.
- Resolve follow-ups: "what about X?" or "and Y?" → expand to the full question.
- If the message is already fully self-contained (no dependency on history), return it UNCHANGED.
- Return ONLY the rewritten question — no explanation, no prefix, no punctuation changes.

Entity context from session:
{entity_context}

Conversation history (most relevant turns):
{history}"""


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(none)"
    lines = []
    for i, turn in enumerate(history, 1):
        lines.append(f"Turn {i}: User asked: {turn['query']}")
        if turn.get("summary"):
            lines.append(f"         Result: {turn['summary']}")
    return "\n".join(lines)


def _format_entity_context(registry: dict) -> str:
    if not registry:
        return "(none)"
    return ", ".join(f"{k}: {v}" for k, v in registry.items())


def _needs_resolution(query: str, history: list[dict]) -> bool:
    if not history:
        return False
    return bool(_REFERENCE_PATTERN.search(query))


def _extract_token_usage(response) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "input":  int(usage.get("input_tokens", 0)),
        "output": int(usage.get("output_tokens", 0)),
        "total":  int(usage.get("total_tokens", 0)),
    }


def _resolve_query(query: str, history: list[dict], registry: dict) -> tuple[str, dict]:
    settings = get_settings()
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        temperature=0,
        google_api_key=settings.gemini_api_key,
    )
    system = SYSTEM_PROMPT.format(
        history=_format_history(history),
        entity_context=_format_entity_context(registry),
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=query)])
    content = response.content
    if isinstance(content, list):
        content = "".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
    return content.strip(), _extract_token_usage(response)


def context_loader_node(state: GraphState) -> GraphState:
    query = state["user_query"]
    history = state.get("conversation_history", [])
    entity_registry = dict(state.get("entity_registry") or {})

    role = state.get("user_role") or "ES"
    permitted_tables = get_permitted_tables(role)
    role_display = get_role_display(role)

    new_entities = _extract_entities(query)
    entity_registry = _update_entity_registry(entity_registry, new_entities)

    token_usage = dict(state.get("token_usage") or {})
    resolution_method = None

    if not _needs_resolution(query, history):
        resolved = query
        changed = False
        resolution_method = "none"
    else:
        resolved, registry_resolved = _resolve_from_registry(query, entity_registry)
        if registry_resolved:
            changed = resolved.lower().strip() != query.lower().strip()
            resolution_method = "entity_registry"
        else:
            relevant_history = _get_relevant_history(query, history, top_k=3)
            resolved, tok = _resolve_query(query, relevant_history, entity_registry)
            changed = resolved.lower().strip() != query.lower().strip()
            token_usage["Context Loader"] = tok
            resolution_method = "llm"

    resolved_entities = _extract_entities(resolved)
    entity_registry = _update_entity_registry(entity_registry, resolved_entities)

    glossary_matches = find_matches(resolved)
    glossary_terms = [m["term"] for m in glossary_matches]

    detail = []
    if changed:
        detail += [f"Original: {query}", f"Resolved: {resolved}"]
    if resolution_method and resolution_method != "none":
        detail.append(f"Resolution method: {resolution_method}")
    if new_entities:
        detail.append(f"Entities tracked: {', '.join(f'{k}={v}' for k, v in new_entities.items())}")
    if glossary_terms:
        detail.append(f"Glossary terms detected: {', '.join(glossary_terms)}")

    if not _needs_resolution(query, history) and not changed:
        summary = "No references detected — query is self-contained" if history else "First turn — no history yet"
    elif changed:
        summary = f"Query resolved via {resolution_method}"
    else:
        summary = "Query unchanged after resolution check"

    if glossary_terms:
        summary += f" · {len(glossary_terms)} glossary term(s) matched"
    summary += f" · role: {role} ({len(permitted_tables)} tables)"
    if new_entities:
        summary += f" · {len(new_entities)} entity(ies) tracked"

    detail.append(f"Role: {role_display} — {len(permitted_tables)} permitted tables")

    trace_entry = {
        "agent": "Context Loader",
        "status": "ok",
        "summary": summary,
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]
    return {
        **state,
        "resolved_query":   resolved,
        "glossary_matches": glossary_matches,
        "user_role":        role,
        "permitted_tables": permitted_tables,
        "entity_registry":  entity_registry,
        "agent_trace":      trace,
        "token_usage":      token_usage,
    }
