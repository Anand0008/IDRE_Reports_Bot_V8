"""
Feedback Store

Persists per-response feedback records to data/feedback_log.jsonl.
Mirrors the audit_writer.py pattern: append-only JSONL, background thread writes,
thread-safe lock, IST timestamps.

Each record captures everything needed to reproduce and analyse a pipeline run —
designed to be consumed by a future analytics or replay agent.
"""
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

FEEDBACK_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "feedback_log.jsonl")

_write_lock = threading.Lock()
_IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class FeedbackRecord:
    # ── Identity ───────────────────────────────────────────────────────────────
    feedback_id:            str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id:             str = ""
    msg_key:                str = ""       # key of the specific assistant message
    user_identity:          str = ""       # handle from post-auth prompt
    user_role:              str = "ES"
    timestamp_ist:          str = field(default_factory=lambda: datetime.now(_IST).isoformat())

    # ── Attestation ────────────────────────────────────────────────────────────
    is_correct:             bool = True
    error_categories:       list = field(default_factory=list)   # multi-select options
    user_notes:             str = ""

    # ── Original query context ─────────────────────────────────────────────────
    user_query:             str = ""
    resolved_query:         str = ""
    conversation_history:   list = field(default_factory=list)

    # ── Clarification Q&A ──────────────────────────────────────────────────────
    clarification_asked:    bool = False
    clarification_question: str = ""

    # ── Glossary + schema ──────────────────────────────────────────────────────
    glossary_terms_matched: list = field(default_factory=list)
    relevant_tables:        list = field(default_factory=list)
    schema_context:         str = ""      # exact schema text the SQL Writer saw

    # ── SQL ────────────────────────────────────────────────────────────────────
    generated_sql:          str = ""
    validated_sql:          str = ""
    assumptions:            list = field(default_factory=list)

    # ── Execution ──────────────────────────────────────────────────────────────
    query_result:           list = field(default_factory=list)   # full rows
    row_count:              int = 0

    # ── Response ───────────────────────────────────────────────────────────────
    formatted_response:     str = ""
    response_format:        str = "table"
    query_explanation:      str = ""
    proactive_suggestions:  list = field(default_factory=list)

    # ── Tracing ────────────────────────────────────────────────────────────────
    agent_trace:            list = field(default_factory=list)
    token_usage:            dict = field(default_factory=dict)
    ambiguity_score:        float = 0.0
    retry_count:            int = 0
    execution_status:       str = "success"

    # ── Reproducibility ────────────────────────────────────────────────────────
    is_feedback_retry:      bool = False
    parent_feedback_id:     str = ""    # "" for originals; set on retry records


def _write_sync(record: FeedbackRecord) -> None:
    os.makedirs(os.path.dirname(FEEDBACK_LOG_PATH), exist_ok=True)
    line = json.dumps(asdict(record), default=str) + "\n"
    with _write_lock:
        with open(FEEDBACK_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)


def write_feedback(record: FeedbackRecord) -> None:
    """Fire-and-forget: write feedback record in a background thread."""
    t = threading.Thread(target=_write_sync, args=(record,), daemon=True)
    t.start()


def build_feedback_record(
    msg: dict,
    session_state: dict,
    pipeline_result: dict,
    attestation: bool,
    notes: str,
    error_categories: list,
    parent_feedback_id: str = "",
) -> FeedbackRecord:
    """
    Construct a FeedbackRecord from the stored message dict, session state,
    and the original pipeline result. Called from the Streamlit UI context.
    """
    glossary_terms = [
        m.get("term", "") for m in pipeline_result.get("glossary_matches", [])
    ]

    # Derive execution status from result fields
    if pipeline_result.get("execution_error") or pipeline_result.get("error_message"):
        status = "error"
    elif pipeline_result.get("needs_clarification"):
        status = "clarification"
    else:
        status = "success"

    return FeedbackRecord(
        session_id=session_state.get("session_id", ""),
        msg_key=msg.get("key", ""),
        user_identity=session_state.get("user_identity", ""),
        user_role=session_state.get("user_role", "ES"),
        is_correct=attestation,
        error_categories=error_categories,
        user_notes=notes,
        user_query=pipeline_result.get("user_query", msg.get("content", "")),
        resolved_query=pipeline_result.get("resolved_query", ""),
        conversation_history=session_state.get("conversation_history", []),
        clarification_asked=bool(pipeline_result.get("needs_clarification")),
        clarification_question=pipeline_result.get("clarification_question", ""),
        glossary_terms_matched=glossary_terms,
        relevant_tables=pipeline_result.get("relevant_tables", []),
        schema_context=pipeline_result.get("schema_context", ""),
        generated_sql=pipeline_result.get("generated_sql", ""),
        validated_sql=pipeline_result.get("validated_sql", ""),
        assumptions=pipeline_result.get("assumptions", []),
        query_result=(pipeline_result.get("query_result") or [])[:50],
        row_count=int(pipeline_result.get("row_count", 0)),
        formatted_response=msg.get("content", ""),
        response_format=pipeline_result.get("response_format", "table"),
        query_explanation=pipeline_result.get("query_explanation", ""),
        proactive_suggestions=pipeline_result.get("proactive_suggestions", []),
        agent_trace=msg.get("trace", []),
        token_usage=msg.get("token_usage", {}),
        ambiguity_score=float(pipeline_result.get("ambiguity_score", 0.0)),
        retry_count=int(pipeline_result.get("retry_count", 0)),
        execution_status=status,
        is_feedback_retry=bool(pipeline_result.get("is_feedback_retry")),
        parent_feedback_id=parent_feedback_id,
    )


def load_feedback(limit: int = 500) -> list[dict]:
    """Load the most recent N feedback records."""
    if not os.path.exists(FEEDBACK_LOG_PATH):
        return []
    records = []
    with open(FEEDBACK_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records[-limit:]


def load_feedback_by_user(user_handle: str) -> list[dict]:
    """Return all feedback records for a specific user identity."""
    return [r for r in load_feedback(limit=5000) if r.get("user_identity") == user_handle]


def load_incorrect_feedback() -> list[dict]:
    """Return all records where is_correct=False."""
    return [r for r in load_feedback(limit=5000) if not r.get("is_correct", True)]
