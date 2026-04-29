"""
Debugger Agent — V6

V6 improvements over V5+:
1. LLM-assisted error analysis — classify UNKNOWN errors via a single LLM call
2. Retry strategy selection — suggest alternative exits (add filter, simplify, metric card)
3. Error knowledge base — log error+fix pairs, use history for smarter retry instructions
4. Progressive retry escalation — retry 1: fix error, retry 2: simplify, retry 3: metric card fallback
"""
import json
import os
import re
import time
from typing import NamedTuple
from state.context import GraphState

MAX_RETRIES = 3

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_ERROR_KB_PATH = os.path.join(_DATA_DIR, "error_knowledge_base.json")


class DebugResult(NamedTuple):
    error_type: str
    failing_element: str
    retry_instruction: str
    retry_strategy: str


_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"Unknown column ['\"]?([^'\"]+)['\"]?", re.IGNORECASE),
        "HALLUCINATED_COLUMN",
        "Column '{element}' does not exist. Re-examine the schema context and use only "
        "columns listed there. Do not invent column names.",
    ),
    (
        re.compile(r"Table ['\"]?[^'\"]*\.['\"]?([^'\"]+)['\"]? doesn't exist", re.IGNORECASE),
        "HALLUCINATED_TABLE",
        "Table '{element}' does not exist in the database. Use only tables listed in the "
        "schema context. Check spelling carefully.",
    ),
    (
        re.compile(r"Unknown table\(s\) referenced[:\s]+\[([^\]]+)\]", re.IGNORECASE),
        "HALLUCINATED_TABLE",
        "Table(s) {element} do not exist. Use only the exact table names in the schema "
        "context — no invented or abbreviated names.",
    ),
    (
        re.compile(r"Hallucinated column\(s\) detected.*?Column `(\w+)`\.`(\w+)` does not exist", re.IGNORECASE | re.DOTALL),
        "HALLUCINATED_COLUMN",
        "The SQL Writer used column '{element}' which does not exist. "
        "Check the VERIFIED COLUMNS block in the schema context for the actual column names. "
        "Do NOT guess or fabricate column names — use only verified columns.",
    ),
    (
        re.compile(r"Column ['\"]?([^'\"]+)['\"]? in (?:field list|where clause|order clause|group statement) is ambiguous", re.IGNORECASE),
        "AMBIGUOUS_COLUMN",
        "Column '{element}' is ambiguous — it exists in multiple tables in the query. "
        "Qualify every column reference with its table name (e.g., `case`.`{element}`).",
    ),
    (
        re.compile(r"You have an error in your SQL syntax", re.IGNORECASE),
        "SYNTAX_ERROR",
        "The SQL has a syntax error. Verify: (1) all table names are backtick-quoted "
        "(especially `case`), (2) commas and parentheses are balanced, "
        "(3) subqueries are properly closed, (4) no trailing commas before FROM/WHERE.",
    ),
    (
        re.compile(r"Query execution was interrupted.*maximum statement execution time exceeded", re.IGNORECASE),
        "TIMEOUT",
        "The query timed out (exceeded 30 s). Rewrite with a more restrictive WHERE clause "
        "to reduce the scanned rows. Consider: (1) adding a date range filter on createdAt, "
        "(2) avoiding full-table scans, (3) replacing correlated subqueries with JOINs.",
    ),
    (
        re.compile(r"Division by zero", re.IGNORECASE),
        "DIVISION_BY_ZERO",
        "Division by zero detected. Wrap the denominator in NULLIF(expr, 0) so that "
        "zero denominators return NULL instead of erroring.",
    ),
    (
        re.compile(r"Incorrect (?:datetime|date|time) value[:\s]+['\"]?([^'\"]+)['\"]?", re.IGNORECASE),
        "TYPE_MISMATCH",
        "Invalid date/time value '{element}'. Use MySQL date functions: CURDATE(), NOW(), "
        "DATE_FORMAT(), DATE_SUB(). Do not use string literals for dates unless the column "
        "type is VARCHAR. Example: WHERE createdAt >= DATE_FORMAT(CURDATE(), '%Y-%m-01').",
    ),
    (
        re.compile(r"Incorrect integer value|Truncated incorrect|Data too long|Out of range value", re.IGNORECASE),
        "TYPE_MISMATCH",
        "Data type mismatch. Re-check the column type in the schema context and ensure the "
        "value being compared or inserted matches that type.",
    ),
    (
        re.compile(r"Blocked keyword ['\"]?(\w+)['\"]?", re.IGNORECASE),
        "SAFETY_VIOLATION",
        "The keyword '{element}' is not allowed. Only SELECT statements are permitted. "
        "Remove all DDL/DML keywords.",
    ),
    (
        re.compile(r"Query must be a SELECT statement", re.IGNORECASE),
        "WRONG_STATEMENT_TYPE",
        "Only SELECT queries are allowed. Rewrite as a SELECT statement.",
    ),
    (
        re.compile(r"Lock wait timeout exceeded", re.IGNORECASE),
        "LOCK_TIMEOUT",
        "A lock timeout occurred (transient). Simplify the query or reduce the number of "
        "rows it touches to avoid lock contention.",
    ),
]

_RETRY_STRATEGIES = {
    "HALLUCINATED_COLUMN":  "rewrite",
    "HALLUCINATED_TABLE":   "rewrite",
    "AMBIGUOUS_COLUMN":     "rewrite",
    "SYNTAX_ERROR":         "rewrite",
    "TIMEOUT":              "suggest_filter",
    "DIVISION_BY_ZERO":     "rewrite",
    "TYPE_MISMATCH":        "rewrite",
    "SAFETY_VIOLATION":     "abort",
    "WRONG_STATEMENT_TYPE": "abort",
    "LOCK_TIMEOUT":         "retry_as_is",
    "UNKNOWN":              "rewrite",
}


def _load_error_kb() -> dict:
    try:
        if os.path.exists(_ERROR_KB_PATH):
            with open(_ERROR_KB_PATH, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_error_fix(error_type: str, error_snippet: str, fix_description: str) -> None:
    try:
        kb = _load_error_kb()
        if error_type not in kb:
            kb[error_type] = []
        kb[error_type].append({
            "error_snippet": error_snippet[:200],
            "fix": fix_description[:200],
            "timestamp": time.time(),
            "success": None,
        })
        kb[error_type] = kb[error_type][-20:]
        os.makedirs(os.path.dirname(_ERROR_KB_PATH), exist_ok=True)
        with open(_ERROR_KB_PATH, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2)
    except OSError:
        pass


def mark_fix_success(error_type: str, success: bool) -> None:
    try:
        kb = _load_error_kb()
        entries = kb.get(error_type, [])
        if entries:
            entries[-1]["success"] = success
            with open(_ERROR_KB_PATH, "w", encoding="utf-8") as f:
                json.dump(kb, f, indent=2)
    except OSError:
        pass


def _kb_lookup(error_type: str) -> str:
    kb = _load_error_kb()
    entries = kb.get(error_type, [])
    successful = [e for e in entries if e.get("success") is True]
    if not successful:
        return ""
    best = successful[-1]
    return f"Knowledge base: similar error was fixed by: {best['fix']}"


def _llm_classify_error(error: str) -> tuple[str, str]:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
        from config.settings import get_settings
        settings = get_settings()
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.1-pro-preview",
            temperature=0.0,
            google_api_key=settings.gemini_api_key,
        )
        prompt = (
            "Classify this SQL/database error into one of these categories: "
            "HALLUCINATED_COLUMN, HALLUCINATED_TABLE, AMBIGUOUS_COLUMN, SYNTAX_ERROR, "
            "TIMEOUT, DIVISION_BY_ZERO, TYPE_MISMATCH, SAFETY_VIOLATION, LOCK_TIMEOUT, UNKNOWN.\n\n"
            f"Error: {error[:300]}\n\n"
            "Reply with ONLY a JSON object: {\"category\": \"...\", \"fix_suggestion\": \"...\"}"
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        parsed = json.loads(content)
        return parsed.get("category", "UNKNOWN"), parsed.get("fix_suggestion", "")
    except Exception:
        return "UNKNOWN", ""


def _classify(error: str, use_llm: bool = False) -> DebugResult:
    for pattern, error_type, template in _PATTERNS:
        m = pattern.search(error)
        if m:
            element = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
            instruction = template.replace("{element}", element)
            strategy = _RETRY_STRATEGIES.get(error_type, "rewrite")
            return DebugResult(error_type, element, instruction, strategy)

    if use_llm:
        llm_type, llm_suggestion = _llm_classify_error(error)
        if llm_type != "UNKNOWN" and llm_suggestion:
            strategy = _RETRY_STRATEGIES.get(llm_type, "rewrite")
            return DebugResult(llm_type, "", f"[LLM analysis] {llm_suggestion}", strategy)

    return DebugResult("UNKNOWN", "", f"Unclassified error: {error[:200]}", "rewrite")


def _escalated_instruction(base_instruction: str, attempt: int, error_type: str) -> str:
    if attempt == 1:
        return base_instruction
    elif attempt == 2:
        return (
            f"{base_instruction}\n\n"
            "ESCALATION (attempt 2): Simplify the query. Remove optional columns, "
            "reduce JOINs to only essential tables, and consider breaking a complex "
            "query into simpler parts. Prefer fewer columns over more."
        )
    else:
        return (
            f"{base_instruction}\n\n"
            "ESCALATION (attempt 3 — final): Write the simplest possible query that "
            "answers the core question. Use at most 2 tables, minimal columns, and "
            "basic WHERE clauses. If a metric card template exists for this query "
            "pattern, use it directly with parameter substitution. Avoid subqueries, "
            "HAVING clauses, and complex aggregations."
        )


def _build_retry_context(
    error: str,
    result: DebugResult,
    attempt: int,
    original_sql: str,
) -> str:
    escalated = _escalated_instruction(result.retry_instruction, attempt, result.error_type)
    kb_hint = _kb_lookup(result.error_type)

    lines = [
        f"RETRY ATTEMPT {attempt} — ERROR ANALYSIS:",
        f"Error type   : {result.error_type}",
        f"Strategy     : {result.retry_strategy}",
    ]
    if result.failing_element:
        lines.append(f"Failing item : {result.failing_element}")
    lines += [
        f"Raw error    : {error[:300]}",
        "",
        f"Fix instruction: {escalated}",
    ]
    if kb_hint:
        lines.append(f"\n{kb_hint}")
    lines += [
        "",
        "Previous SQL that failed:",
        original_sql[:600],
    ]
    return "\n".join(lines)


def debugger_node(state: GraphState) -> GraphState:
    error = state.get("execution_error") or state.get("error_message") or "Unknown error"
    original_sql = state.get("validated_sql") or state.get("generated_sql") or ""
    retry_count = state.get("retry_count", 0)
    attempt = retry_count + 1

    use_llm = attempt >= 2
    result = _classify(error, use_llm=use_llm)

    _save_error_fix(result.error_type, error[:200], result.retry_instruction[:200])

    retry_ctx = _build_retry_context(error, result, attempt, original_sql)

    detail = [result.retry_instruction[:200]]
    if result.retry_strategy != "rewrite":
        detail.append(f"Strategy: {result.retry_strategy}")
    if attempt >= 2:
        detail.append(f"Escalation level: {attempt}")
    kb_hint = _kb_lookup(result.error_type)
    if kb_hint:
        detail.append(kb_hint[:100])

    trace_entry = {
        "agent": "Debugger",
        "status": "warn",
        "summary": f"Error classified as {result.error_type}"
        + (f" · failing item: '{result.failing_element}'" if result.failing_element else "")
        + (f" · strategy: {result.retry_strategy}" if result.retry_strategy != "rewrite" else "")
        + (f" · escalation L{attempt}" if attempt >= 2 else ""),
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]

    return {
        **state,
        "retry_context": retry_ctx,
        "debug_error_type": result.error_type,
        "debug_retry_strategy": result.retry_strategy,
        "agent_trace": trace,
        "execution_error": None,
        "error_message": "",
    }
