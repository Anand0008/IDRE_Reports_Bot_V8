"""
SQL Writer Agent — V8 (MCP + Tool-Use)

V8 replaces RAG-based context injection with Gemini function calling.
The LLM decides what information it needs and calls tools on-demand:
- get_report_reference: Ground-truth IDRE report query logic
- get_table_schema: Live table definitions
- get_enum_values: Valid values for status/type columns
- lookup_business_term: Glossary definitions
- list_available_reports: Report catalog
- get_pricing_info: Fee structure

No embedding model, no ChromaDB, no vector search.
"""
import json
import os
import re
import google.generativeai as genai
from config.settings import get_settings
from state.context import GraphState
from tools.idre_tools import TOOL_DEFINITIONS, TOOL_DISPATCH

METRIC_CARDS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "metric_cards.json")
SQL_TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "sql_templates.json")
SUCCESSFUL_QUERIES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "successful_queries.json")

SYSTEM_PROMPT = """You are a MySQL expert writing SELECT queries for the IDRE (Independent Dispute Resolution Entity) platform — a healthcare dispute resolution system under the No Surprises Act.

You have access to tools that provide accurate information about the IDRE database and reports.
ALWAYS call get_report_reference FIRST if the user's question relates to any known IDRE report.
Use get_table_schema to verify column names before writing SQL.
Use get_enum_values to get correct status/type values.

=== CRITICAL DISPLAY RULES ===
1. NEVER return `case`.id as the dispute identifier — it is an internal UUID useless to users.
   ALWAYS SELECT `case`.shortId AS dispute_number. The UI displays this as "DISP-<shortId>".
   When a user searches by "DISP-XXXXXXX", filter: WHERE `case`.shortId = 'XXXXXXX' (strip the DISP- prefix).
2. When listing disputes, ALWAYS include: `case`.shortId AS dispute_number, `case`.status, `case`.createdAt.
3. When the query mentions an organization name (e.g. "UHC", "UnitedHealthcare", "HaloMD", "PacificHealth"):
   JOIN `organization` on the appropriate FK to filter by `organization`.name LIKE '%<name>%'.
4. For NIP info: JOIN `organization` ON `case`.nonInitiatingPartyOrganizationId = `organization`.id.
   For IP info: JOIN `organization` ON `case`.initiatingPartyOrganizationId = `organization`.id.
   IMPORTANT: `case_party`.partyType values are 'PROVIDER' or 'HEALTH_PLAN' — NOT 'INITIATING'/'NON_INITIATING'.
5. Exclude soft-deleted data: dispute_line_items WHERE status = 'ACTIVE' (not 'REMOVED').

=== SQL RULES ===
6. Only write SELECT statements — no INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, EXEC, or CALL.
7. Always backtick table names. `case` is a MySQL reserved word — always backtick it.
8. Do NOT add a LIMIT clause unless the user explicitly asks for "top N" / "first N" / "latest N".
9. Use human-readable column aliases (e.g., AS dispute_number, AS org_name, AS total_amount).
10. Use ONLY tables and columns confirmed by the get_table_schema tool.

=== PAYMENT KNOWLEDGE ===
- Payment type column is `type` (NOT paymentType). Use p.type for filtering.
- Join case to payments: `case_payment_allocation` cpa ON cpa.caseId = `case`.id, then `payment` p ON cpa.paymentId = p.id.
- cpa.partyType: 'INITIATING' or 'NON_INITIATING'.
- case_refunds.refundAmountCents is in CENTS (divide by 100).

Output format:
<SQL statement>

ASSUMPTIONS:
- <assumption 1>
"""

_BREAKDOWN_WORDS = re.compile(
    r"\b(by|per|group|breakdown|split|each|list|show|which|who|detail|"
    r"organisation|organization|region|status|type|category|compare|"
    r"between|versus|vs|trend|over time|monthly|daily|weekly)\b", re.IGNORECASE)
_COUNT_INTENT = re.compile(
    r"^(how many|what is the (total|count|number)|count of|total number|"
    r"number of|how much|what('s| is) the)", re.IGNORECASE)


def _check_metric_cards(query: str) -> str:
    if not os.path.exists(METRIC_CARDS_PATH):
        return None
    word_count = len(query.split())
    if word_count > 12:
        return None
    if not _COUNT_INTENT.match(query.strip()):
        return None
    if _BREAKDOWN_WORDS.search(query):
        return None
    with open(METRIC_CARDS_PATH) as f:
        cards = json.load(f)
    query_lower = query.lower()
    for metric in cards.get("metrics", []):
        for trigger in metric.get("nl_triggers", []):
            if trigger.lower() in query_lower:
                return metric["sql"]
    return None


def _check_sql_templates(query: str) -> str:
    if not os.path.exists(SQL_TEMPLATES_PATH):
        return None
    try:
        with open(SQL_TEMPLATES_PATH, encoding="utf-8") as f:
            templates = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    query_lower = query.lower()
    for tmpl in templates.get("templates", []):
        pattern = tmpl.get("pattern", "")
        if pattern and re.search(pattern, query_lower, re.IGNORECASE):
            sql = tmpl.get("sql", "")
            params = tmpl.get("default_params", {})
            for key, val in params.items():
                sql = sql.replace(f"{{{key}}}", str(val))
            return sql
    return None


def save_successful_query(query: str, sql: str) -> None:
    try:
        if os.path.exists(SUCCESSFUL_QUERIES_PATH):
            with open(SUCCESSFUL_QUERIES_PATH, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"queries": []}

        data["queries"].append({"query": query, "sql": sql})
        if len(data["queries"]) > 200:
            data["queries"] = data["queries"][-200:]

        os.makedirs(os.path.dirname(SUCCESSFUL_QUERIES_PATH), exist_ok=True)
        with open(SUCCESSFUL_QUERIES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _parse_llm_response(raw: str) -> tuple[str, list[str]]:
    match = re.search(r"\nASSUMPTIONS\s*:\s*\n", raw, re.IGNORECASE)
    if not match:
        sql_part = raw.strip()
        sql_part = re.sub(r"\s*```\s*$", "", sql_part)
        return sql_part, []

    sql_part = raw[: match.start()].strip()
    sql_part = re.sub(r"\s*```\s*$", "", sql_part)
    assumptions_raw = raw[match.end():].strip()
    assumptions = []
    for line in assumptions_raw.splitlines():
        cleaned = line.strip().lstrip("-").lstrip("*").strip()
        if cleaned and not cleaned.startswith("```"):
            assumptions.append(cleaned)
    return sql_part, assumptions


def _build_gemini_tools() -> list[dict]:
    """Convert our tool definitions to Gemini function declaration format."""
    tools = []
    for defn in TOOL_DEFINITIONS:
        tools.append(genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=defn["name"],
                    description=defn["description"],
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            k: genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description=v.get("description", ""),
                            )
                            for k, v in defn["parameters"].get("properties", {}).items()
                        },
                        required=defn["parameters"].get("required", []),
                    ),
                )
            ]
        ))
    return tools


def _generate_sql_with_tools(
    query: str, error_context: str = "", max_tool_rounds: int = 5
) -> tuple[str, list[str], dict, list[dict]]:
    """Generate SQL using Gemini function calling with MCP tools.

    The LLM calls tools to gather information, then generates SQL.
    Returns (sql, assumptions, token_usage, tool_calls_log).
    """
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)

    model = genai.GenerativeModel(
        model_name="gemini-3.1-pro-preview",
        system_instruction=SYSTEM_PROMPT,
        tools=_build_gemini_tools(),
    )

    user_message = query
    if error_context:
        user_message += f"\n\n[Previous attempt failed: {error_context}]"

    chat = model.start_chat()
    response = chat.send_message(user_message)

    tool_calls_log = []
    total_tokens = {"input": 0, "output": 0, "total": 0}
    rounds = 0

    while rounds < max_tool_rounds:
        if not response.candidates:
            break

        candidate = response.candidates[0]

        if not candidate.content.parts:
            break

        has_function_call = False
        function_responses = []

        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call.name:
                has_function_call = True
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args) if part.function_call.args else {}

                tool_fn = TOOL_DISPATCH.get(fn_name)
                if tool_fn:
                    result = tool_fn(**fn_args)
                else:
                    result = f"Unknown tool: {fn_name}"

                tool_calls_log.append({
                    "tool": fn_name,
                    "args": fn_args,
                    "result_length": len(result),
                })

                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": result},
                        )
                    )
                )

        if not has_function_call:
            break

        response = chat.send_message(function_responses)
        rounds += 1

    if hasattr(response, 'usage_metadata'):
        usage = response.usage_metadata
        total_tokens = {
            "input": getattr(usage, 'prompt_token_count', 0),
            "output": getattr(usage, 'candidates_token_count', 0),
            "total": getattr(usage, 'total_token_count', 0),
        }

    final_text = ""
    if response.candidates:
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                final_text += part.text

    raw = final_text.strip()
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    sql, assumptions = _parse_llm_response(raw)

    return sql, assumptions, total_tokens, tool_calls_log


def _check_explain_plan(sql: str) -> dict:
    try:
        from db.connector import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(sa_text(f"EXPLAIN {sql[:2000]}"))
            rows = result.fetchall()
            total_rows_scanned = 0
            full_scan_tables = []
            for row in rows:
                row_count = row[8] if len(row) > 8 and row[8] else 0
                try:
                    row_count = int(row_count)
                except (TypeError, ValueError):
                    row_count = 0
                total_rows_scanned += row_count
                access_type = row[3] if len(row) > 3 else ""
                table_name = row[2] if len(row) > 2 else ""
                if access_type == "ALL" and row_count > 100000:
                    full_scan_tables.append(f"{table_name} ({row_count:,} rows)")

            return {
                "total_rows": total_rows_scanned,
                "full_scan_tables": full_scan_tables,
                "warning": bool(full_scan_tables),
            }
    except Exception:
        return {"total_rows": 0, "full_scan_tables": [], "warning": False}


def sql_writer_node(state: GraphState) -> GraphState:
    query = state.get("resolved_query") or state["user_query"]
    error_context = state.get("retry_context", "") or state.get("execution_error", "") or ""
    retry_count = state.get("retry_count", 0)

    if retry_count == 0:
        sql = _check_metric_cards(query)
        if sql:
            trace_entry = {
                "agent": "SQL Writer",
                "status": "ok",
                "summary": "Served from metric card (fast path — no LLM call needed)",
                "detail": [],
            }
            trace = state.get("agent_trace", []) + [trace_entry]
            return {**state, "generated_sql": sql, "assumptions": [], "agent_trace": trace}

        sql = _check_sql_templates(query)
        if sql:
            trace_entry = {
                "agent": "SQL Writer",
                "status": "ok",
                "summary": "Served from SQL template (fast path — no LLM call needed)",
                "detail": [],
            }
            trace = state.get("agent_trace", []) + [trace_entry]
            return {**state, "generated_sql": sql, "assumptions": [], "agent_trace": trace}

    sql, assumptions, tok, tool_calls = _generate_sql_with_tools(query, error_context)

    token_usage = dict(state.get("token_usage") or {})
    writer_key = "SQL Writer" if retry_count == 0 else f"SQL Writer (retry {retry_count})"
    token_usage[writer_key] = tok

    explain = _check_explain_plan(sql)

    label = "Retry" if retry_count > 0 else "Attempt 1"
    detail = []
    if error_context:
        detail.append(f"Previous error: {error_context[:120]}")
    if tool_calls:
        tool_names = [tc["tool"] for tc in tool_calls]
        detail.append(f"Tools called: {', '.join(tool_names)}")
    if assumptions:
        detail.append(f"{len(assumptions)} assumption(s) annotated")
    if explain.get("warning"):
        detail.append(f"Full table scan: {', '.join(explain['full_scan_tables'])}")

    trace_entry = {
        "agent": "SQL Writer",
        "status": "ok",
        "summary": f"SQL generated via Gemini + {len(tool_calls)} tool call(s) · {label}"
        + (f" · {len(assumptions)} assumption(s)" if assumptions else ""),
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]

    return {
        **state,
        "generated_sql": sql,
        "assumptions": assumptions,
        "agent_trace": trace,
        "execution_error": None,
        "token_usage": token_usage,
        "explain_plan": explain,
    }
