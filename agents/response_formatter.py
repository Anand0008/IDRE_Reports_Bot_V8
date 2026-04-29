"""
Response Formatter Agent — V6

V6 improvements over V5+:
1. Richer chart types — heatmap, funnel, scatter, stacked bar
2. Interactive drill-down — chart element click metadata for filtering
3. Narrative generation — multi-sentence insight paragraphs
4. Export as slide metadata — title/chart/explanation bundle for PPTX
"""
import re
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from tabulate import tabulate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import get_settings
from state.context import GraphState

MAX_TABLE_ROWS = 50

_DATE_COL_PATTERNS = re.compile(
    r"(date|time|_at|month|year|day|period|created|updated|closed|rendered|changed)",
    re.IGNORECASE,
)
_NUMERIC_TYPES = (int, float, Decimal)
_STATUS_KEYWORDS = {"status", "state", "phase", "stage", "step"}


def _is_numeric(val) -> bool:
    if isinstance(val, _NUMERIC_TYPES):
        return True
    if isinstance(val, str):
        try:
            float(val.replace(",", "").replace("$", ""))
            return True
        except ValueError:
            return False
    return False


def _is_date_col(col_name: str, values: list) -> bool:
    if _DATE_COL_PATTERNS.search(col_name):
        return True
    for v in values[:3]:
        if isinstance(v, (date, datetime)):
            return True
        if isinstance(v, str) and re.match(r"\d{4}-\d{2}", str(v)):
            return True
    return False


def _is_status_col(col_name: str) -> bool:
    tokens = {t.lower() for t in re.split(r"[_\-\s]+", col_name)}
    return bool(tokens & _STATUS_KEYWORDS)


def _select_chart(rows: list[dict], resolved_intent: str) -> tuple:
    if not rows:
        return "table", None

    row_count = len(rows)
    cols = list(rows[0].keys())
    col_count = len(cols)

    if row_count == 1 and col_count == 1:
        return "number", None

    date_cols = [c for c in cols if _is_date_col(c, [r.get(c) for r in rows])]
    numeric_cols = [c for c in cols if all(_is_numeric(r.get(c)) for r in rows[:10] if r.get(c) is not None)]
    categorical_cols = [c for c in cols if c not in numeric_cols and c not in date_cols]
    status_cols = [c for c in categorical_cols if _is_status_col(c)]

    intent_lower = resolved_intent.lower()
    wants_trend = any(w in intent_lower for w in ("trend", "over time", "by month", "monthly", "daily", "weekly", "over the"))
    wants_funnel = any(w in intent_lower for w in ("funnel", "pipeline", "stages", "conversion", "flow"))
    wants_heatmap = any(w in intent_lower for w in ("heatmap", "heat map", "matrix", "cross-tab", "crosstab"))
    wants_scatter = any(w in intent_lower for w in ("scatter", "correlation", "relationship", "vs", "versus"))

    if wants_heatmap and len(categorical_cols) >= 2 and numeric_cols:
        return "heatmap", {
            "type": "heatmap",
            "x_col": categorical_cols[0],
            "y_col": categorical_cols[1],
            "value_col": numeric_cols[0],
            "title": f"{numeric_cols[0]} by {categorical_cols[0]} × {categorical_cols[1]}",
        }

    if wants_funnel and status_cols and numeric_cols:
        return "funnel_chart", {
            "type": "funnel_chart",
            "stage_col": status_cols[0],
            "value_col": numeric_cols[0],
            "title": f"{numeric_cols[0]} by {status_cols[0]} stage",
        }

    if wants_scatter and len(numeric_cols) >= 2:
        label_col = categorical_cols[0] if categorical_cols else None
        return "scatter_plot", {
            "type": "scatter_plot",
            "x_col": numeric_cols[0],
            "y_col": numeric_cols[1],
            "label_col": label_col,
            "title": f"{numeric_cols[1]} vs {numeric_cols[0]}",
        }

    if date_cols and numeric_cols:
        if len(numeric_cols) >= 2:
            return "line_chart", {
                "type": "line_chart",
                "x_col": date_cols[0],
                "y_col": numeric_cols[:4],
                "title": f"Trends over {date_cols[0]}",
            }
        return "line_chart", {
            "type": "line_chart",
            "x_col": date_cols[0],
            "y_col": numeric_cols[0],
            "title": f"{numeric_cols[0]} over {date_cols[0]}",
        }

    if wants_trend and categorical_cols and numeric_cols:
        return "line_chart", {
            "type": "line_chart",
            "x_col": categorical_cols[0],
            "y_col": numeric_cols[0],
            "title": f"{numeric_cols[0]} trend",
        }

    if categorical_cols and numeric_cols and row_count <= MAX_TABLE_ROWS:
        cardinality = len({r.get(categorical_cols[0]) for r in rows})
        if cardinality <= 10:
            if len(numeric_cols) >= 2:
                return "stacked_bar", {
                    "type": "stacked_bar",
                    "x_col": categorical_cols[0],
                    "y_cols": numeric_cols[:4],
                    "title": f"Breakdown by {categorical_cols[0]}",
                    "drill_down": {
                        "filter_col": categorical_cols[0],
                        "description": f"Click a bar to filter by {categorical_cols[0]}",
                    },
                }
            if cardinality <= 5:
                return "pie_chart", {
                    "type": "pie_chart",
                    "label_col": categorical_cols[0],
                    "value_col": numeric_cols[0],
                    "title": f"{numeric_cols[0]} by {categorical_cols[0]}",
                    "drill_down": {
                        "filter_col": categorical_cols[0],
                        "description": f"Click a slice to filter by {categorical_cols[0]}",
                    },
                }
            return "bar_chart", {
                "type": "bar_chart",
                "x_col": categorical_cols[0],
                "y_col": numeric_cols[0],
                "title": f"{numeric_cols[0]} by {categorical_cols[0]}",
                "drill_down": {
                    "filter_col": categorical_cols[0],
                    "description": f"Click a bar to filter by {categorical_cols[0]}",
                },
            }

    if categorical_cols and len(numeric_cols) > 1:
        return "stacked_bar", {
            "type": "stacked_bar",
            "x_col": categorical_cols[0],
            "y_cols": numeric_cols,
            "title": f"Results by {categorical_cols[0]}",
        }

    return "table", None


_EXPLAINER_PROMPT = """You are a data analyst explaining a SQL query to a non-technical business user.

Given the SQL query below, write ONE clear sentence (max 30 words) explaining what it does in plain English.
Focus on WHAT data is being retrieved and any key filters — not HOW the SQL works.

Do not use technical terms like JOIN, GROUP BY, subquery, or alias.
Do not start with "This query" — start with the action (e.g., "Counts...", "Shows...", "Lists...").

SQL:
{sql}

Reply with only the one-sentence explanation, nothing else."""


_NARRATIVE_PROMPT = """You are a business analytics assistant for an IDRE dispute resolution platform.

The user asked: "{intent}"
The result had {row_count} row(s) with columns: {columns}.
Here is a sample of the data (first 5 rows): {sample_data}

Write a concise analytical narrative (2-4 sentences) that:
1. Summarizes the key finding or trend in the data
2. Highlights any notable outliers, changes, or patterns
3. Provides actionable context (e.g., "This represents a 23% increase over last month")

Be specific and use numbers from the data. Write in business language, not technical language.
Do not mention SQL, queries, or databases. Write as if presenting findings to an executive.

Reply with only the narrative paragraph, nothing else."""


_INSIGHTS_PROMPT = """You are a business analytics assistant for an IDRE dispute resolution platform.

The user asked: "{intent}"
The result had {row_count} row(s) with columns: {columns}.

Suggest exactly 3 specific follow-up questions a business analyst might ask next.
Make them concrete and directly related to the result — not generic.
Each question must be answerable from the same database.

Return ONLY a JSON array of 3 strings, no explanation, no markdown fences.
Example: ["Question 1?", "Question 2?", "Question 3?"]"""


def _extract_token_usage(response) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    return {
        "input":  int(usage.get("input_tokens", 0)),
        "output": int(usage.get("output_tokens", 0)),
        "total":  int(usage.get("total_tokens", 0)),
    }


def _generate_explanation(sql: str) -> tuple[str, dict]:
    try:
        settings = get_settings()
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.1-pro-preview",
            temperature=0.0,
            google_api_key=settings.gemini_api_key,
        )
        prompt = _EXPLAINER_PROMPT.format(sql=sql[:800])
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
        return content.strip().strip('"').strip("'"), _extract_token_usage(response)
    except Exception:
        return "", {}


def _generate_narrative(intent: str, rows: list[dict]) -> tuple[str, dict]:
    if not rows or len(rows) < 2:
        return "", {}
    try:
        settings = get_settings()
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.1-pro-preview",
            temperature=0.2,
            google_api_key=settings.gemini_api_key,
        )
        columns = ", ".join(list(rows[0].keys())[:8])
        sample = json.dumps(rows[:5], default=str)[:600]
        prompt = _NARRATIVE_PROMPT.format(
            intent=intent[:200],
            row_count=len(rows),
            columns=columns,
            sample_data=sample,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
        return content.strip(), _extract_token_usage(response)
    except Exception:
        return "", {}


def _generate_suggestions(intent: str, rows: list[dict]) -> tuple[list[str], dict]:
    if not rows:
        return [], {}
    try:
        settings = get_settings()
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.1-pro-preview",
            temperature=0.3,
            google_api_key=settings.gemini_api_key,
        )
        columns = ", ".join(list(rows[0].keys())[:6])
        prompt = _INSIGHTS_PROMPT.format(
            intent=intent[:200],
            row_count=len(rows),
            columns=columns,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(c.get("text", str(c)) if isinstance(c, dict) else str(c) for c in content)
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        suggestions = json.loads(content)
        if isinstance(suggestions, list):
            return [str(s) for s in suggestions[:3]], _extract_token_usage(response)
    except Exception:
        pass
    return [], {}


def _build_slide_metadata(
    chart_config: dict,
    explanation: str,
    narrative: str,
    rows: list[dict],
    intent: str,
) -> dict:
    if not chart_config:
        return {}
    return {
        "title": chart_config.get("title", intent[:60]),
        "subtitle": explanation or "",
        "chart_type": chart_config.get("type", "table"),
        "chart_config": chart_config,
        "narrative": narrative or "",
        "row_count": len(rows) if rows else 0,
        "data_snapshot": rows[:10] if rows else [],
    }


def _format_number(value) -> str:
    try:
        n = int(value)
        return f"{n:,}"
    except (TypeError, ValueError):
        return str(value)


def _format_assumptions(assumptions: list[str]) -> str:
    lines = "\n".join(f"> - {a}" for a in assumptions)
    return f"> **Assumptions made**\n{lines}"


def format_response(rows: list[dict], sql: str, assumptions: list[str]) -> str:
    parts = []
    if not rows:
        parts.append("No results found for your query.")
    elif len(rows) == 1 and len(rows[0]) == 1:
        col, val = next(iter(rows[0].items()))
        parts.append(f"**{col}:** {_format_number(val)}")
    elif len(rows) <= MAX_TABLE_ROWS:
        parts.append(tabulate(rows, headers="keys", tablefmt="github", floatfmt=".2f"))
        parts.append(f"\n*{len(rows)} row(s) returned.*")
    else:
        parts.append(tabulate(rows[:MAX_TABLE_ROWS], headers="keys", tablefmt="github", floatfmt=".2f"))
        parts.append(f"\n*Showing first {MAX_TABLE_ROWS} of {len(rows)} rows.*")
    if assumptions:
        parts.append("\n" + _format_assumptions(assumptions))
    parts.append(f"\n**SQL used:**\n```sql\n{sql}\n```")
    return "\n".join(parts)


def response_formatter_node(state: GraphState) -> GraphState:
    rows        = state.get("query_result")
    sql         = state.get("validated_sql", state.get("generated_sql", ""))
    assumptions = state.get("assumptions", [])
    intent      = state.get("resolved_query") or state.get("user_query", "")

    fmt, chart_config = _select_chart(rows or [], intent)
    if rows and len(rows) == 1 and len(rows[0]) == 1:
        fmt = "number"
        chart_config = None

    response = format_response(rows, sql, assumptions)

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_explain = pool.submit(_generate_explanation, sql) if sql else None
        fut_suggest = pool.submit(_generate_suggestions, intent, rows or []) if rows else None
        fut_narrative = pool.submit(_generate_narrative, intent, rows or []) if rows and len(rows) >= 2 else None

        explanation, tok_explain = fut_explain.result() if fut_explain else ("", {})
        suggestions, tok_suggest = fut_suggest.result() if fut_suggest else ([], {})
        narrative, tok_narrative = fut_narrative.result() if fut_narrative else ("", {})

    token_usage = dict(state.get("token_usage") or {})
    fmt_tokens: dict[str, int] = {"input": 0, "output": 0, "total": 0}
    for tok in (tok_explain, tok_suggest, tok_narrative):
        for k in fmt_tokens:
            fmt_tokens[k] += tok.get(k, 0)
    if fmt_tokens["total"] > 0:
        token_usage["Response Formatter"] = fmt_tokens

    slide_meta = _build_slide_metadata(chart_config, explanation, narrative, rows or [], intent)

    assumption_note = f" · {len(assumptions)} assumption(s) surfaced" if assumptions else ""
    insight_note    = f" · {len(suggestions)} suggestion(s)" if suggestions else ""
    narrative_note  = " · narrative generated" if narrative else ""

    detail = []
    if chart_config:
        detail.append(f"Chart: {chart_config.get('title', fmt)}")
        if chart_config.get("drill_down"):
            detail.append(f"Drill-down: {chart_config['drill_down']['description']}")
    if explanation:
        detail.append(f"Explanation: {explanation}")
    if narrative:
        detail.append(f"Narrative: {narrative[:100]}...")
    if assumptions:
        detail.extend(assumptions)
    if slide_meta:
        detail.append("Slide export metadata generated")

    trace_entry = {
        "agent": "Response Formatter",
        "status": "ok",
        "summary": (
            f"Formatted as {fmt}"
            + (f" · {len(rows):,} rows" if rows else "")
            + assumption_note
            + insight_note
            + narrative_note
        ),
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]

    return {
        **state,
        "formatted_response":    response,
        "response_format":       fmt,
        "chart_config":          chart_config,
        "query_explanation":     explanation,
        "query_narrative":       narrative,
        "proactive_suggestions": suggestions,
        "slide_metadata":        slide_meta,
        "agent_trace":           trace,
        "token_usage":           token_usage,
    }
