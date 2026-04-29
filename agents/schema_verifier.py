"""
Schema Verifier Agent — V6

V6 improvements over V5+:
1. Proactive column suggestion via Levenshtein distance
2. Schema diff detection against cached snapshot
3. Index awareness — SHOW INDEX information for SQL Writer
4. Column usage frequency tracking
"""
import json
import os
import re
from sqlalchemy import text
from db.connector import get_engine
from state.context import GraphState

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SCHEMA_SNAPSHOT_PATH = os.path.join(_DATA_DIR, "schema_snapshot.json")
_COLUMN_USAGE_PATH = os.path.join(_DATA_DIR, "column_usage.json")

_column_cache: dict[str, list[dict]] = {}
_index_cache: dict[str, list[dict]] = {}


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def suggest_column(hallucinated: str, table: str) -> str:
    cols = _fetch_columns(table)
    if not cols:
        return ""
    best_match = ""
    best_dist = float("inf")
    for c in cols:
        dist = _levenshtein(hallucinated.lower(), c["name"].lower())
        if dist < best_dist:
            best_dist = dist
            best_match = c["name"]
    if best_dist <= 3:
        return best_match
    return ""


def _fetch_columns(table_name: str) -> list[dict]:
    if table_name in _column_cache:
        return _column_cache[table_name]
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"SHOW COLUMNS FROM `{table_name}`"))
            cols = []
            for row in result.fetchall():
                cols.append({
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "key": row[3] or "",
                })
            _column_cache[table_name] = cols
            return cols
    except Exception:
        return []


def _fetch_indexes(table_name: str) -> list[dict]:
    if table_name in _index_cache:
        return _index_cache[table_name]
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"SHOW INDEX FROM `{table_name}`"))
            indexes = []
            for row in result.fetchall():
                indexes.append({
                    "key_name": row[2],
                    "column_name": row[4],
                    "non_unique": row[1],
                })
            _index_cache[table_name] = indexes
            return indexes
    except Exception:
        return []


def _load_column_usage() -> dict[str, dict[str, int]]:
    if not os.path.exists(_COLUMN_USAGE_PATH):
        return {}
    try:
        with open(_COLUMN_USAGE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_schema_snapshot() -> dict:
    if not os.path.exists(_SCHEMA_SNAPSHOT_PATH):
        return {}
    try:
        with open(_SCHEMA_SNAPSHOT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_schema_snapshot(snapshot: dict) -> None:
    os.makedirs(os.path.dirname(_SCHEMA_SNAPSHOT_PATH), exist_ok=True)
    with open(_SCHEMA_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)


def _detect_schema_diff(table: str, current_cols: list[dict]) -> list[str]:
    snapshot = _load_schema_snapshot()
    cached = snapshot.get(table, [])
    if not cached:
        return []
    cached_names = {c["name"] for c in cached}
    current_names = {c["name"] for c in current_cols}
    added = current_names - cached_names
    removed = cached_names - current_names
    diffs = []
    if added:
        diffs.append(f"New columns in `{table}`: {', '.join(added)}")
    if removed:
        diffs.append(f"Removed columns from `{table}`: {', '.join(removed)}")
    return diffs


_COMMONLY_HALLUCINATED = {
    "case": [
        "paymentType", "partyType", "disputeId", "caseNumber",
        "closed_date", "closedDate", "closedAt", "amount",
        "totalAmount", "payment_status", "arbitratorId",
    ],
    "payment": ["paymentType", "caseId", "partyType", "disputeId"],
    "case_payment_allocation": ["amount", "paymentType", "status"],
    "case_party": ["partyType_INITIATING", "partyType_NON_INITIATING", "role", "organizationId"],
    "user": ["role"],
}


def build_verified_schema(tables: list[str]) -> str:
    blocks = []
    schema_diffs = []
    snapshot_update = {}
    column_usage = _load_column_usage()

    for table in tables:
        cols = _fetch_columns(table)
        if not cols:
            continue

        snapshot_update[table] = [{"name": c["name"], "type": c["type"]} for c in cols]
        diffs = _detect_schema_diff(table, cols)
        schema_diffs.extend(diffs)

        indexes = _fetch_indexes(table)
        indexed_cols = {idx["column_name"] for idx in indexes}
        usage = column_usage.get(table, {})

        col_names = {c["name"] for c in cols}
        col_lines = []
        for c in cols:
            key_info = f" [{c['key']}]" if c['key'] else ""
            null_info = " NULL" if c['nullable'] else " NOT NULL"
            annotations = []
            if c["name"] in indexed_cols:
                annotations.append("INDEXED")
            use_count = usage.get(c["name"], 0)
            if use_count >= 10:
                annotations.append(f"frequently used ({use_count}x)")
            ann_str = f" ({', '.join(annotations)})" if annotations else ""
            col_lines.append(f"  - {c['name']} ({c['type']}{null_info}{key_info}){ann_str}")

        block = f"=== VERIFIED COLUMNS: `{table}` ===\n"
        block += "\n".join(col_lines)

        if indexed_cols:
            block += f"\n  INDEXED columns: {', '.join(sorted(indexed_cols))}"
            block += "\n  TIP: Use indexed columns in WHERE clauses for better performance."

        hallucinated = _COMMONLY_HALLUCINATED.get(table, [])
        negatives = [h for h in hallucinated if h not in col_names]
        if negatives:
            block += f"\n  WARNING: `{table}` does NOT have columns: {', '.join(negatives)}"
            block += "\n  DO NOT use these column names — they will cause runtime errors."
            for neg in negatives:
                suggestion = suggest_column(neg, table)
                if suggestion:
                    block += f"\n  SUGGESTION: Instead of '{neg}', did you mean '{suggestion}'?"

        blocks.append(block)

    if snapshot_update:
        try:
            existing = _load_schema_snapshot()
            existing.update(snapshot_update)
            _save_schema_snapshot(existing)
        except OSError:
            pass

    if not blocks:
        return ""

    header = "--- LIVE SCHEMA (verified via SHOW COLUMNS) ---\n\n"
    if schema_diffs:
        header += "⚠ SCHEMA CHANGES DETECTED:\n" + "\n".join(f"  {d}" for d in schema_diffs) + "\n\n"

    return header + "\n\n".join(blocks)


def schema_verifier_node(state: GraphState) -> GraphState:
    tables = state.get("relevant_tables", [])
    if not tables:
        return state

    verified = build_verified_schema(tables)
    if not verified:
        trace_entry = {
            "agent": "Schema Verifier",
            "status": "warn",
            "summary": "Could not verify schema — DB may be unreachable",
            "detail": [],
        }
        trace = state.get("agent_trace", []) + [trace_entry]
        return {**state, "agent_trace": trace}

    existing_ctx = state.get("schema_context", "")
    enriched = verified + "\n\n" + existing_ctx

    negatives_count = verified.count("does NOT have")
    suggestions_count = verified.count("SUGGESTION:")
    index_count = verified.count("INDEXED columns:")
    schema_changes = verified.count("SCHEMA CHANGES DETECTED")

    detail = [f"Tables verified: {', '.join(tables)}"]
    if suggestions_count:
        detail.append(f"{suggestions_count} column suggestion(s) provided")
    if index_count:
        detail.append(f"Index info included for {index_count} table(s)")
    if schema_changes:
        detail.append("Schema changes detected since last snapshot")

    trace_entry = {
        "agent": "Schema Verifier",
        "status": "ok",
        "summary": f"Verified columns for {len(tables)} table(s) · {negatives_count} warning(s) · {suggestions_count} suggestion(s)",
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]

    return {**state, "schema_context": enriched, "agent_trace": trace}
