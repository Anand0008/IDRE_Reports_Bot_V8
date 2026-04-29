"""
SQL Validator Agent — V6

V6 improvements over V5+:
1. SQL cost estimation based on table row counts and join complexity
2. Semantic validation — check SQL logically matches the question
3. Enhanced injection detection (OR 1=1, UNION SELECT, encoded variants)
4. Type compatibility checking for WHERE comparisons
"""
import re
import json
import os
from state.context import GraphState

SCHEMA_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "schema_catalog.json")
_catalog_cache = None

BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|CALL|GRANT|REVOKE|LOAD|OUTFILE|DUMPFILE)\b",
    re.IGNORECASE,
)

_INJECTION_PATTERNS = [
    re.compile(r"\bOR\s+1\s*=\s*1\b", re.IGNORECASE),
    re.compile(r"\bOR\s+'[^']*'\s*=\s*'[^']*'", re.IGNORECASE),
    re.compile(r"\bUNION\s+(?:ALL\s+)?SELECT\b", re.IGNORECASE),
    re.compile(r";\s*DROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r";\s*DELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),
    re.compile(r"/\*.*?\*/", re.DOTALL),
    re.compile(r"%27|%3B|%23|%2D%2D", re.IGNORECASE),
    re.compile(r"(?:CHAR|CHR)\s*\(\s*\d+\s*\)", re.IGNORECASE),
    re.compile(r"SLEEP\s*\(\s*\d+\s*\)", re.IGNORECASE),
    re.compile(r"BENCHMARK\s*\(", re.IGNORECASE),
]


def _get_catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        with open(SCHEMA_CATALOG_PATH) as f:
            _catalog_cache = json.load(f)
    return _catalog_cache


def _get_known_tables() -> set:
    return set(_get_catalog()["tables"].keys())


def _get_table_columns(table_name: str) -> set:
    info = _get_catalog()["tables"].get(table_name, {})
    return {c["name"] for c in info.get("columns", [])}


def _get_table_column_types(table_name: str) -> dict[str, str]:
    info = _get_catalog()["tables"].get(table_name, {})
    return {c["name"]: c["type"] for c in info.get("columns", [])}


def _get_table_row_count(table_name: str) -> int:
    info = _get_catalog()["tables"].get(table_name, {})
    return info.get("row_count_approx", 0)


def _extract_table_names(sql: str) -> list[str]:
    normalized = sql.replace("`", "")
    pattern = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)", re.IGNORECASE)
    return pattern.findall(normalized)


_TABLE_DOT_COL_RE = re.compile(r"`?(\w+)`?\s*\.\s*`?(\w+)`?")
_ALIAS_RE = re.compile(r"\b(?:FROM|JOIN)\s+`?(\w+)`?\s+(?:AS\s+)?`?(\w+)`?", re.IGNORECASE)


def _extract_column_refs(sql: str, referenced_tables: list[str]) -> list[tuple[str, str]]:
    return _TABLE_DOT_COL_RE.findall(sql.replace("`", ""))


def _build_alias_map(sql: str) -> dict[str, str]:
    alias_map = {}
    for match in _ALIAS_RE.finditer(sql.replace("`", "")):
        table, alias = match.group(1), match.group(2)
        if alias.upper() not in ("ON", "WHERE", "SET", "AND", "OR", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS"):
            alias_map[alias.lower()] = table.lower()
    return alias_map


def validate_columns(sql: str, referenced_tables: list[str]) -> list[str]:
    known_tables = _get_known_tables()
    alias_map = _build_alias_map(sql)
    refs = _extract_column_refs(sql, referenced_tables)
    warnings = []
    seen = set()
    for table_or_alias, col in refs:
        real_table = alias_map.get(table_or_alias.lower(), table_or_alias.lower())
        if real_table not in known_tables:
            continue
        key = (real_table, col)
        if key in seen:
            continue
        seen.add(key)
        valid_cols = _get_table_columns(real_table)
        if valid_cols and col not in valid_cols:
            warnings.append(f"Column `{real_table}`.`{col}` does not exist. Valid columns: {', '.join(sorted(valid_cols)[:15])}")
    return warnings


def _estimate_cost(sql: str, referenced_tables: list[str]) -> dict:
    total_rows = 0
    for table in referenced_tables:
        total_rows += _get_table_row_count(table)
    join_count = len(re.findall(r"\bJOIN\b", sql, re.IGNORECASE))
    complexity = max(1, join_count)
    estimated_scan = total_rows * complexity
    return {
        "total_rows": total_rows,
        "join_count": join_count,
        "estimated_scan": estimated_scan,
        "expensive": estimated_scan > 1_000_000,
    }


def _semantic_validation(sql: str, query: str) -> list[str]:
    warnings = []
    query_lower = query.lower()
    sql_upper = sql.upper()

    if re.search(r"\btop\s+\d+\b", query_lower) and "LIMIT" not in sql_upper:
        warnings.append("User asked for 'top N' but SQL has no LIMIT clause")

    if re.search(r"\bcount\b", query_lower) and not re.search(r"\bCOUNT\s*\(", sql, re.IGNORECASE):
        if not re.search(r"\bSUM\s*\(", sql, re.IGNORECASE):
            warnings.append("User asked for a count but SQL has no COUNT() or SUM() aggregate")

    if re.search(r"\bby\s+(month|week|day|year)\b", query_lower):
        if not re.search(r"\bGROUP\s+BY\b", sql, re.IGNORECASE):
            warnings.append("User asked for grouping by time period but SQL has no GROUP BY")

    if re.search(r"\bstatus\b", query_lower):
        if not re.search(r"\bstatus\b", sql, re.IGNORECASE):
            warnings.append("User mentioned 'status' but SQL doesn't reference status column")

    return warnings


def _check_injection(sql: str) -> str:
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(sql):
            return f"Potential SQL injection pattern detected: {pattern.pattern[:50]}"
    return ""


def _check_type_compatibility(sql: str, referenced_tables: list[str]) -> list[str]:
    warnings = []
    alias_map = _build_alias_map(sql)
    known_tables = _get_known_tables()

    like_matches = re.findall(r"`?(\w+)`?\s*\.\s*`?(\w+)`?\s+LIKE\b", sql, re.IGNORECASE)
    for table_or_alias, col in like_matches:
        real_table = alias_map.get(table_or_alias.lower(), table_or_alias.lower())
        if real_table in known_tables:
            col_types = _get_table_column_types(real_table)
            col_type = col_types.get(col, "").lower()
            if col_type and any(t in col_type for t in ("int", "decimal", "float", "double", "bigint")):
                warnings.append(f"LIKE used on numeric column `{real_table}`.`{col}` (type: {col_type})")

    return warnings


def validate_sql(sql: str, permitted_tables: list = None) -> tuple:
    if not sql or not sql.strip():
        return False, "Empty SQL generated."
    stripped = sql.strip()
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        return False, f"Query must be a SELECT statement. Got: {stripped[:60]}"
    match = BLOCKED_KEYWORDS.search(stripped)
    if match:
        return False, f"Blocked keyword '{match.group()}' found in query."

    injection = _check_injection(stripped)
    if injection:
        return False, injection

    if stripped.rstrip(";").count(";") > 0:
        return False, "Multiple SQL statements are not allowed."
    known = _get_known_tables()
    referenced = _extract_table_names(stripped)
    unknown = [t for t in referenced if t not in known]
    if unknown:
        return False, f"Unknown table(s) referenced: {unknown}. Check spelling or schema."
    if permitted_tables:
        unauthorized = [t for t in referenced if t not in permitted_tables]
        if unauthorized:
            return False, "Query references table(s) that are not accessible for your role."
    return True, ""


def sql_validator_node(state: GraphState) -> GraphState:
    sql = state.get("generated_sql", "")
    permitted = state.get("permitted_tables") or None
    query = state.get("resolved_query") or state.get("user_query", "")
    is_valid, error = validate_sql(sql, permitted_tables=permitted)
    trace = state.get("agent_trace", [])

    if is_valid:
        tables_used = _extract_table_names(sql)
        col_warnings = validate_columns(sql, tables_used)

        if col_warnings:
            col_error = "Hallucinated column(s) detected:\n" + "\n".join(col_warnings)
            trace_entry = {
                "agent": "SQL Validator",
                "status": "error",
                "summary": f"Column validation failed — {len(col_warnings)} hallucinated column(s)",
                "detail": col_warnings,
            }
            trace = trace + [trace_entry]
            return {**state, "validated_sql": "", "error_message": col_error, "agent_trace": trace}

        cost = _estimate_cost(sql, tables_used)
        semantic_warnings = _semantic_validation(sql, query)
        type_warnings = _check_type_compatibility(sql, tables_used)
        all_warnings = semantic_warnings + type_warnings

        detail = []
        if tables_used:
            detail.append(f"Tables in query: {', '.join(tables_used)}")
        if cost["expensive"]:
            detail.append(f"⚠ Expensive query: ~{cost['estimated_scan']:,} estimated row scans")
        if all_warnings:
            detail.extend([f"⚠ {w}" for w in all_warnings])

        status = "warn" if (cost["expensive"] or all_warnings) else "ok"
        summary = f"Passed all safety checks · {len(tables_used)} table(s) referenced"
        if cost["expensive"]:
            summary += " · ⚠ expensive query"
        if all_warnings:
            summary += f" · {len(all_warnings)} semantic warning(s)"

        trace_entry = {
            "agent": "SQL Validator",
            "status": status,
            "summary": summary,
            "detail": detail,
        }
        trace = trace + [trace_entry]

        return {
            **state,
            "validated_sql": sql,
            "error_message": "",
            "agent_trace": trace,
            "query_complexity": cost,
        }
    else:
        is_permission_violation = "not accessible for your role" in error
        trace_entry = {
            "agent": "SQL Validator",
            "status": "error",
            "summary": "Permission violation — query blocked" if is_permission_violation else "Validation failed — query blocked",
            "detail": [error],
        }
        trace = trace + [trace_entry]
        return {**state, "validated_sql": "", "error_message": error, "agent_trace": trace}
