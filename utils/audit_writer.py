"""
Audit Trail Writer — V6

V6 improvements over V5+:
1. Token usage capture — persist token_usage from pipeline state for cost tracking
2. Anomaly detection — flag spikes in failures, repeated queries, clarification loops
3. Query complexity and self-verification results in audit record
4. V6 metadata fields (entity_registry, pricing_era, debug strategy)
"""
import json
import os
import threading
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "audit_log.jsonl")
_ANOMALY_WINDOW_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "anomaly_window.json")

_write_lock = threading.Lock()
_IST = timezone(timedelta(hours=5, minutes=30))

_ANOMALY_THRESHOLDS = {
    "failure_spike_per_hour": 10,
    "same_query_repeated": 15,
    "clarification_loop_count": 5,
}


@dataclass
class AuditEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    user_role: str = "ES"
    user_identity: str = ""
    timestamp_ist: str = field(
        default_factory=lambda: datetime.now(_IST).isoformat()
    )

    user_query: str = ""
    resolved_query: str = ""
    ambiguity_score: float = 0.0
    glossary_terms_matched: list[str] = field(default_factory=list)

    relevant_tables: list[str] = field(default_factory=list)

    generated_sql: str = ""
    validated_sql: str = ""

    execution_status: str = "success"
    execution_error: str = ""
    retry_count: int = 0
    row_count: int = 0
    response_format: str = "table"

    total_pipeline_ms: int = 0
    agent_timings: dict[str, int] = field(default_factory=dict)

    clarification_asked: bool = False
    permission_violation: bool = False
    assumptions_count: int = 0
    is_feedback_retry: bool = False
    feedback_record_id: str = ""

    token_usage: dict[str, dict] = field(default_factory=dict)
    total_tokens: int = 0

    query_complexity: dict = field(default_factory=dict)
    self_verification: dict = field(default_factory=dict)
    entity_registry: dict = field(default_factory=dict)
    debug_error_type: str = ""
    debug_retry_strategy: str = ""

    anomalies_detected: list[str] = field(default_factory=list)


def _write_sync(event: AuditEvent) -> None:
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    record = asdict(event)
    line = json.dumps(record, default=str) + "\n"
    with _write_lock:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)


def log_event(event: AuditEvent) -> None:
    t = threading.Thread(target=_write_sync, args=(event,), daemon=True)
    t.start()


def _derive_status(state: dict[str, Any]) -> str:
    if state.get("needs_clarification"):
        return "clarification"
    if state.get("permission_violation"):
        return "permission_denied"
    err = state.get("error_message", "")
    if err and "not accessible for your role" in err:
        return "permission_denied"
    if err:
        return "validation_failed"
    if state.get("execution_error"):
        retry = state.get("retry_count", 0)
        from core.orchestrator import MAX_RETRIES
        return "max_retries_exceeded" if retry >= MAX_RETRIES else "execution_error"
    return "success"


def _detect_anomalies(state: dict[str, Any], status: str) -> list[str]:
    anomalies = []
    try:
        window = _load_anomaly_window()
        now = datetime.now(_IST)
        hour_key = now.strftime("%Y-%m-%d-%H")

        if "hourly_failures" not in window:
            window["hourly_failures"] = {}
        if "query_counts" not in window:
            window["query_counts"] = {}
        if "clarification_counts" not in window:
            window["clarification_counts"] = {}

        if status in ("validation_failed", "execution_error", "max_retries_exceeded"):
            window["hourly_failures"][hour_key] = window["hourly_failures"].get(hour_key, 0) + 1
            if window["hourly_failures"][hour_key] >= _ANOMALY_THRESHOLDS["failure_spike_per_hour"]:
                anomalies.append(
                    f"Failure spike: {window['hourly_failures'][hour_key]} failures this hour"
                )

        query_key = (state.get("user_query", "") or "")[:100]
        session = state.get("session_id", "")
        combo_key = f"{session}:{query_key}"
        window["query_counts"][combo_key] = window["query_counts"].get(combo_key, 0) + 1
        if window["query_counts"][combo_key] >= _ANOMALY_THRESHOLDS["same_query_repeated"]:
            anomalies.append(
                f"Repeated query: same query run {window['query_counts'][combo_key]}x in session"
            )

        if state.get("needs_clarification"):
            window["clarification_counts"][session] = window["clarification_counts"].get(session, 0) + 1
            if window["clarification_counts"][session] >= _ANOMALY_THRESHOLDS["clarification_loop_count"]:
                anomalies.append(
                    f"Clarification loop: {window['clarification_counts'][session]} clarifications in session"
                )

        old_hours = [k for k in window.get("hourly_failures", {}) if k < (now - timedelta(hours=2)).strftime("%Y-%m-%d-%H")]
        for k in old_hours:
            del window["hourly_failures"][k]

        _save_anomaly_window(window)
    except Exception:
        pass
    return anomalies


def _load_anomaly_window() -> dict:
    try:
        if os.path.exists(_ANOMALY_WINDOW_PATH):
            with open(_ANOMALY_WINDOW_PATH, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_anomaly_window(window: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_ANOMALY_WINDOW_PATH), exist_ok=True)
        with open(_ANOMALY_WINDOW_PATH, "w", encoding="utf-8") as f:
            json.dump(window, f)
    except OSError:
        pass


def _sum_tokens(token_usage: dict) -> int:
    total = 0
    for agent_tok in token_usage.values():
        if isinstance(agent_tok, dict):
            total += agent_tok.get("total", 0)
    return total


def build_and_log(state: dict[str, Any], total_ms: int) -> None:
    try:
        glossary_terms = [m["term"] for m in state.get("glossary_matches", [])]
        status = _derive_status(state)
        token_usage = state.get("token_usage", {})
        anomalies = _detect_anomalies(state, status)

        event = AuditEvent(
            session_id=state.get("session_id", ""),
            user_role=state.get("user_role", "ES"),
            user_identity=state.get("user_identity", ""),
            user_query=state.get("user_query", ""),
            resolved_query=state.get("resolved_query", ""),
            ambiguity_score=float(state.get("ambiguity_score", 0.0)),
            glossary_terms_matched=glossary_terms,
            relevant_tables=state.get("relevant_tables", []),
            generated_sql=state.get("generated_sql", ""),
            validated_sql=state.get("validated_sql", ""),
            execution_status=status,
            execution_error=str(state.get("execution_error") or state.get("error_message") or ""),
            retry_count=int(state.get("retry_count", 0)),
            row_count=int(state.get("row_count", 0)),
            response_format=state.get("response_format", "table"),
            total_pipeline_ms=total_ms,
            agent_timings=state.get("agent_timings", {}),
            clarification_asked=bool(state.get("needs_clarification")),
            permission_violation="not accessible for your role" in str(state.get("error_message", "")),
            assumptions_count=len(state.get("assumptions", [])),
            is_feedback_retry=bool(state.get("is_feedback_retry")),
            feedback_record_id=state.get("feedback_record_id", ""),
            token_usage=token_usage,
            total_tokens=_sum_tokens(token_usage),
            query_complexity=state.get("query_complexity") or {},
            self_verification=state.get("self_verification") or {},
            entity_registry=state.get("entity_registry") or {},
            debug_error_type=state.get("debug_error_type") or "",
            debug_retry_strategy=state.get("debug_retry_strategy") or "",
            anomalies_detected=anomalies,
        )
        log_event(event)
    except Exception:
        pass
