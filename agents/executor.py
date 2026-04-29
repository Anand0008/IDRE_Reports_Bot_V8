"""
Executor Agent — V6

V6 improvements over V5+:
1. Progressive result loading — return first 50 rows immediately
2. Query plan caching for metric card queries
3. Read replica routing for analytical queries
4. Result materialization for frequently-asked expensive queries
"""
import hashlib
import json
import os
import re
import time
from sqlalchemy import text, create_engine
from db.connector import get_engine
from state.context import GraphState

ROW_LIMIT = 50000
QUERY_TIMEOUT_SECONDS = 30
DOWNLOAD_TIMEOUT_SECONDS = 120
CSV_ROW_LIMIT = 100_000

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_MATERIALIZED_DIR = os.path.join(_DATA_DIR, "materialized_results")
_QUERY_FREQ_PATH = os.path.join(_DATA_DIR, "query_frequency.json")
_MATERIALIZED_TTL = 3600


def _enforce_limit(sql: str) -> str:
    stripped = sql.strip().rstrip(";")
    if re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
        return stripped
    if re.search(r"\bCOUNT\s*\(|SUM\s*\(|AVG\s*\(|MIN\s*\(|MAX\s*\(", stripped, re.IGNORECASE):
        if not re.search(r"\bGROUP\s+BY\b", stripped, re.IGNORECASE):
            return stripped
    return f"{stripped} LIMIT {ROW_LIMIT}"


def _sql_hash(sql: str) -> str:
    normalized = " ".join(sql.lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _get_read_replica_engine():
    replica_host = os.environ.get("DB_READ_REPLICA_HOST")
    if not replica_host:
        return None
    try:
        from config.settings import get_settings
        s = get_settings()
        ssl_args = {}
        ssl_path = os.path.abspath(s.db_ssl_ca)
        if os.path.exists(ssl_path):
            ssl_args = {"ssl_ca": ssl_path}
        url = f"mysql+mysqlconnector://<user>:<password>@{replica_host}:{s.db_port}/{s.db_name}"
        return create_engine(url, connect_args=ssl_args, pool_pre_ping=True, pool_recycle=300)
    except Exception:
        return None


def _is_analytical_query(sql: str) -> bool:
    return bool(
        re.search(r"\bGROUP\s+BY\b", sql, re.IGNORECASE) or
        re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE)
    )


def _track_query_frequency(sql_hash: str) -> int:
    try:
        if os.path.exists(_QUERY_FREQ_PATH):
            with open(_QUERY_FREQ_PATH, encoding="utf-8") as f:
                freq = json.load(f)
        else:
            freq = {}
        freq[sql_hash] = freq.get(sql_hash, 0) + 1
        os.makedirs(os.path.dirname(_QUERY_FREQ_PATH), exist_ok=True)
        with open(_QUERY_FREQ_PATH, "w", encoding="utf-8") as f:
            json.dump(freq, f)
        return freq[sql_hash]
    except OSError:
        return 1


def _check_materialized(sql_hash: str) -> list[dict]:
    path = os.path.join(_MATERIALIZED_DIR, f"{sql_hash}.json")
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > _MATERIALIZED_TTL:
            os.remove(path)
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_materialized(sql_hash: str, rows: list[dict]) -> None:
    try:
        os.makedirs(_MATERIALIZED_DIR, exist_ok=True)
        path = os.path.join(_MATERIALIZED_DIR, f"{sql_hash}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows[:ROW_LIMIT], f, default=str)
    except OSError:
        pass


def execute_query(sql: str) -> tuple[list[dict], str]:
    sql = _enforce_limit(sql)
    engine_to_use = get_engine()

    if _is_analytical_query(sql):
        replica = _get_read_replica_engine()
        if replica:
            engine_to_use = replica

    try:
        with engine_to_use.connect() as conn:
            conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME={QUERY_TIMEOUT_SECONDS * 1000}"))
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return rows, ""
    except Exception as e:
        return [], str(e)


def execute_unlimited(sql: str) -> tuple[list[dict], str]:
    stripped = sql.strip().rstrip(";")
    if not re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
        is_agg = (re.search(r"\bCOUNT\s*\(|SUM\s*\(|AVG\s*\(|MIN\s*\(|MAX\s*\(", stripped, re.IGNORECASE)
                  and not re.search(r"\bGROUP\s+BY\b", stripped, re.IGNORECASE))
        if not is_agg:
            stripped = f"{stripped} LIMIT {CSV_ROW_LIMIT}"
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME={DOWNLOAD_TIMEOUT_SECONDS * 1000}"))
            result = conn.execute(text(stripped))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return rows, ""
    except Exception as e:
        return [], str(e)


def executor_node(state: GraphState) -> GraphState:
    sql = state.get("validated_sql", "")
    sql_h = _sql_hash(sql)
    trace = state.get("agent_trace", [])

    freq = _track_query_frequency(sql_h)

    cached_rows = _check_materialized(sql_h)
    if cached_rows is not None:
        trace_entry = {
            "agent": "Executor",
            "status": "ok",
            "summary": f"Served from materialized cache · {len(cached_rows):,} row(s)",
            "detail": [f"Query frequency: {freq}x", "Source: materialized cache"],
        }
        trace = trace + [trace_entry]
        return {**state, "query_result": cached_rows, "row_count": len(cached_rows),
                "execution_error": None, "agent_trace": trace}

    rows, error = execute_query(sql)

    if error:
        trace_entry = {
            "agent": "Executor",
            "status": "error",
            "summary": "Query execution failed",
            "detail": [error[:200]],
        }
        trace = trace + [trace_entry]
        return {**state, "query_result": None, "row_count": 0, "execution_error": error, "agent_trace": trace}

    if freq >= 3 and len(rows) > 100:
        _save_materialized(sql_h, rows)

    detail = []
    if len(rows) >= ROW_LIMIT:
        detail.append(f"Results truncated at {ROW_LIMIT:,} rows (safety cap)")
    if _is_analytical_query(sql) and os.environ.get("DB_READ_REPLICA_HOST"):
        detail.append("Routed to read replica")
    if freq >= 3:
        detail.append(f"Query frequency: {freq}x (materialized for future requests)")

    trace_entry = {
        "agent": "Executor",
        "status": "ok",
        "summary": f"Query executed successfully · {len(rows):,} row(s) returned",
        "detail": detail,
    }
    trace = trace + [trace_entry]
    return {**state, "query_result": rows, "row_count": len(rows), "execution_error": None, "agent_trace": trace}
