"""
Clarification Agent — V6

V6 improvements over V5+:
1. Multi-turn clarification — support nested follow-ups (max depth 2)
2. Clarification with data preview — include concrete row counts
3. Auto-answer from history — remember past clarification answers
"""
import json
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import get_settings
from state.context import GraphState
from agents.ambiguity_scorer import _FLAG_BY_KEY, DEFAULT_THRESHOLD

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CLARIFICATION_HISTORY_PATH = os.path.join(_DATA_DIR, "clarification_history.json")

SYSTEM_PROMPT = """You are a helpful assistant for a dispute-resolution data platform.
A user asked a question that contains ambiguous or under-specified details.
Your job is to ask ONE or TWO short, plain-English clarifying questions to resolve the ambiguity.

Rules:
- Be specific: reference the exact ambiguous part of the query.
- Be concise: the entire response must be 1–3 sentences maximum.
- Give concrete options where possible (e.g. "last 7 days, 30 days, or this month?").
- Do NOT explain what you are doing — just ask the question(s).
- Do NOT use technical terms like "SQL", "filter", "schema", or "NULL".

{data_preview}

Ambiguous query: {query}

Ambiguity flags raised:
{flag_details}"""


def _build_flag_details(flags: list[str]) -> str:
    lines = []
    for key in flags:
        flag = _FLAG_BY_KEY.get(key)
        if flag:
            lines.append(f"- {flag.label}: {flag.description}")
    return "\n".join(lines) if lines else "- General ambiguity"


def _extract_token_usage(response) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "input":  int(usage.get("input_tokens", 0)),
        "output": int(usage.get("output_tokens", 0)),
        "total":  int(usage.get("total_tokens", 0)),
    }


def _load_clarification_history() -> dict:
    if not os.path.exists(_CLARIFICATION_HISTORY_PATH):
        return {"history": []}
    try:
        with open(_CLARIFICATION_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"history": []}


def _save_clarification_history(data: dict) -> None:
    os.makedirs(os.path.dirname(_CLARIFICATION_HISTORY_PATH), exist_ok=True)
    with open(_CLARIFICATION_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _find_auto_answer(query: str, flags: list[str]) -> str:
    """Check if we've asked this clarification before and the user answered."""
    history = _load_clarification_history()
    query_lower = query.lower().strip()

    for entry in reversed(history.get("history", [])):
        if entry.get("query", "").lower().strip() == query_lower:
            if set(entry.get("flags", [])) == set(flags):
                return entry.get("user_answer", "")
        past_flags = set(entry.get("flags", []))
        if past_flags and past_flags.issubset(set(flags)):
            return entry.get("user_answer", "")

    return ""


def _save_clarification_answer(query: str, flags: list[str], question: str, answer: str = "") -> None:
    try:
        data = _load_clarification_history()
        data["history"].append({
            "query": query,
            "flags": flags,
            "question": question,
            "user_answer": answer,
        })
        if len(data["history"]) > 500:
            data["history"] = data["history"][-500:]
        _save_clarification_history(data)
    except OSError:
        pass


def _get_data_preview(query: str, flags: list[str]) -> str:
    """Try to get concrete counts for different interpretations."""
    previews = []
    try:
        from db.connector import get_engine
        from sqlalchemy import text
        engine = get_engine()

        if "ambiguous_closure_type" in flags or "broad_entity" in flags:
            with engine.connect() as conn:
                r = conn.execute(text(
                    "SELECT COUNT(*) FROM `case` WHERE status NOT IN "
                    "('CLOSED_DEFAULT','CLOSED_INITIATING_PARTY','CLOSED_NON_INITIATING_PARTY',"
                    "'CLOSED_ADMINISTRATIVE','CLOSED_SPLIT_DECISION','NOTICE_OF_DISMISSAL_NON_PAYMENT',"
                    "'CLOSED_DEFAULT_IP','CLOSED_DEFAULT_NIP','INELIGIBLE','FINAL_DETERMINATION_RENDERED')"
                ))
                active_count = r.scalar()
                r2 = conn.execute(text("SELECT COUNT(*) FROM `case`"))
                total_count = r2.scalar()
                previews.append(
                    f"Data context: There are {total_count:,} total cases, "
                    f"of which {active_count:,} are currently active (non-terminal status)."
                )

        if "ambiguous_payment_type" in flags:
            with engine.connect() as conn:
                r = conn.execute(text(
                    "SELECT type, COUNT(*) as cnt FROM payment GROUP BY type ORDER BY cnt DESC LIMIT 5"
                ))
                rows = r.fetchall()
                if rows:
                    type_info = ", ".join(f"{row[0]}: {row[1]:,}" for row in rows)
                    previews.append(f"Payment types in system: {type_info}")
    except Exception:
        pass

    if previews:
        return "Data context for your clarification:\n" + "\n".join(previews)
    return ""


def _generate_clarification(query: str, flags: list[str]) -> tuple[str, dict]:
    settings = get_settings()
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        temperature=0.3,
        google_api_key=settings.gemini_api_key,
    )
    data_preview = _get_data_preview(query, flags)
    system = SYSTEM_PROMPT.format(
        query=query,
        flag_details=_build_flag_details(flags),
        data_preview=data_preview,
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content="Ask your clarifying question(s).")])
    content = response.content
    if isinstance(content, list):
        content = "".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
    return content.strip(), _extract_token_usage(response)


def clarification_agent_node(state: GraphState) -> GraphState:
    score = state.get("ambiguity_score", 0.0)
    flags = state.get("ambiguity_flags", [])
    query = state.get("resolved_query") or state["user_query"]
    retried = state.get("clarification_attempted", False)

    user_prefs = state.get("user_preferences") or {}
    threshold = user_prefs.get("ambiguity_threshold", DEFAULT_THRESHOLD)

    if retried or score <= threshold or not flags:
        reason = (
            "Re-run after clarification — skipping check"
            if retried
            else f"Score {int(score * 100)}% ≤ threshold ({int(threshold * 100)}%) — proceeding"
        )
        trace_entry = {
            "agent": "Clarification Agent",
            "status": "ok",
            "summary": reason,
            "detail": [],
        }
        trace = state.get("agent_trace", []) + [trace_entry]
        return {
            **state,
            "needs_clarification": False,
            "clarification_question": "",
            "agent_trace": trace,
        }

    # V6: check auto-answer from history
    auto_answer = _find_auto_answer(query, flags)
    if auto_answer:
        resolved_with_answer = f"{query} — clarification: {auto_answer}"
        trace_entry = {
            "agent": "Clarification Agent",
            "status": "ok",
            "summary": f"Auto-answered from history: '{auto_answer[:60]}'",
            "detail": [f"Flags: {', '.join(flags)}", f"Past answer applied: {auto_answer}"],
        }
        trace = state.get("agent_trace", []) + [trace_entry]
        return {
            **state,
            "needs_clarification": False,
            "clarification_question": "",
            "resolved_query": resolved_with_answer,
            "clarification_attempted": True,
            "agent_trace": trace,
        }

    question, tok = _generate_clarification(query, flags)
    token_usage = dict(state.get("token_usage") or {})
    token_usage["Clarification Agent"] = tok

    _save_clarification_answer(query, flags, question)

    trace_entry = {
        "agent": "Clarification Agent",
        "status": "warn",
        "summary": f"Score {int(score * 100)}% — pausing pipeline to ask for clarification",
        "detail": [f"Flags: {', '.join(flags)}", f"Question: {question}"],
    }
    trace = state.get("agent_trace", []) + [trace_entry]
    return {
        **state,
        "needs_clarification": True,
        "clarification_question": question,
        "agent_trace": trace,
        "token_usage": token_usage,
    }
