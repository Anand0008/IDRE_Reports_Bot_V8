"""
Audit Analytics  (Story 8.3)

Reads audit_log.jsonl and computes lightweight statistics for the sidebar panel.
All functions are read-only and safe to call from the Streamlit main thread.
Returns empty/zero results gracefully if the log doesn't exist yet.
"""
import json
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "audit_log.jsonl")
_IST = timezone(timedelta(hours=5, minutes=30))


def _load_events(limit: int = 1000) -> list[dict]:
    """Load the most recent `limit` audit events."""
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    events = []
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    except Exception:
        pass
    return events


def _today_prefix() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def get_summary_stats() -> dict:
    """
    Returns a stats dict for display in the sidebar:
      total_today, success_rate_today, avg_latency_ms, top_tables, recent_errors
    """
    events = _load_events(2000)
    today = _today_prefix()

    today_events = [
        e for e in events
        if (e.get("timestamp_ist") or e.get("timestamp_utc", "")).startswith(today)
    ]
    all_time_count = len(events)
    today_count = len(today_events)

    # Success rate (today)
    if today_events:
        successes = sum(1 for e in today_events if e.get("execution_status") == "success")
        success_rate = round(successes / today_count * 100)
    else:
        success_rate = 0

    # Average latency (today, successful only)
    latencies = [
        e["total_pipeline_ms"]
        for e in today_events
        if e.get("execution_status") == "success" and e.get("total_pipeline_ms", 0) > 0
    ]
    avg_latency = round(sum(latencies) / len(latencies) / 1000, 1) if latencies else 0

    # Top queried tables (all time, last 1000 events)
    table_counter: Counter = Counter()
    for e in events:
        for t in e.get("relevant_tables", []):
            table_counter[t] += 1
    top_tables = table_counter.most_common(5)

    # Recent errors (last 5 non-success events)
    errors = [
        {
            "ts": (e.get("timestamp_ist") or e.get("timestamp_utc", ""))[:16].replace("T", " "),
            "status": e.get("execution_status", ""),
            "query": e.get("user_query", "")[:60],
        }
        for e in reversed(events)
        if e.get("execution_status") not in ("success", "clarification")
    ][:5]

    # Glossary utilisation (% of queries that matched at least one term)
    glossary_hits = sum(1 for e in events if e.get("glossary_terms_matched"))
    glossary_pct = round(glossary_hits / all_time_count * 100) if all_time_count else 0

    return {
        "today_count":    today_count,
        "all_time_count": all_time_count,
        "success_rate":   success_rate,
        "avg_latency_s":  avg_latency,
        "top_tables":     top_tables,
        "recent_errors":  errors,
        "glossary_pct":   glossary_pct,
    }
