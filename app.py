"""
IDRE Reports Bot — Streamlit Frontend
Run with: streamlit run app.py
"""
import html
import io
import os
import sys
import uuid
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(
    page_title="IDRE Reports Bot",
    page_icon="📊",
    layout="wide",
)

# ── Authentication Gate ────────────────────────────────────────────────────────
_APP_PASSWORD = os.getenv("APP_PASSWORD")
if not _APP_PASSWORD:
    st.error("🔒 **SECURITY LOCKDOWN:** 'APP_PASSWORD' is not set in the .env file. The application refuses to start.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 IDRE Security Gate")
    st.markdown("This instance contains a clone of production data. Access is strictly controlled.")
    pwd_input = st.text_input("Application Password", type="password")
    if st.button("Unlock Dashboard", type="primary"):
        if pwd_input == _APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

# ── Identity prompt (one-time per session, after auth) ─────────────────────────
if st.session_state.get("user_identity") is None:
    st.title("👋 Who are you?")
    st.markdown("Your name is used to tag feedback and audit records. No extra password needed.")
    handle = st.text_input("Your name or handle", placeholder="e.g. your first name or team handle")
    if st.button("Continue →", type="primary"):
        st.session_state["user_identity"] = handle.strip() if handle.strip() else "anonymous"
        st.rerun()
    st.stop()


def _safe_error_message(error_text: str) -> str:
    """Format an error message safely — escape HTML and wrap in code block."""
    escaped = html.escape(error_text[:500])  # Limit length
    return f"Sorry, I couldn't answer that.\n\n**Error:**\n```\n{escaped}\n```"


def _extract_summary(formatted_response: str, max_len: int = 120) -> str:
    """Pull a short human-readable summary from a formatted pipeline response."""
    for line in formatted_response.splitlines():
        line = line.strip()
        if not line or line.startswith("|") or line.startswith("-") or line.startswith("```") or line.startswith("**SQL"):
            continue
        line = line.replace("**", "")
        return line[:max_len] + ("…" if len(line) > max_len else "")
    return formatted_response[:max_len]


# ── Agent trace styling ────────────────────────────────────────────────────────
AGENT_META = {
    "Cache":              {"icon": "⚡", "color": "#1ABC9C"},
    "Context Loader":     {"icon": "🧠", "color": "#E67E22"},
    "Ambiguity Scorer":   {"icon": "🎯", "color": "#E74C3C"},
    "Clarification Agent":{"icon": "❓", "color": "#F39C12"},
    "Schema Mapper":      {"icon": "🔍", "color": "#4A90D9"},
    "Platform Context":   {"icon": "🏥", "color": "#3498DB"},
    "Post-Processor":     {"icon": "🔄", "color": "#1ABC9C"},
    "SQL Writer":         {"icon": "✍️",  "color": "#9B59B6"},
    "SQL Validator":      {"icon": "🛡️",  "color": "#27AE60"},
    "Executor":           {"icon": "⚡",  "color": "#E67E22"},
    "Debugger":           {"icon": "🔧", "color": "#C0392B"},
    "Response Formatter": {"icon": "📋",  "color": "#16A085"},
    "Output Formatter":   {"icon": "🎨",  "color": "#2980B9"},
    "Feedback Injector":  {"icon": "🔁",  "color": "#8E44AD"},
    "Schema Verifier":    {"icon": "🔬",  "color": "#2ECC71"},
}
STATUS_COLOR = {"ok": "#27AE60", "warn": "#F39C12", "error": "#E74C3C"}
STATUS_ICON  = {"ok": "✓", "warn": "⚠", "error": "✗"}


def render_agent_trace(trace: list[dict]):
    """Render structured agent trace as a visual pipeline timeline."""
    if not trace:
        return

    st.markdown(
        "<p style='font-size:13px; color:#888; margin-bottom:6px;'>Pipeline execution trace</p>",
        unsafe_allow_html=True,
    )

    for i, step in enumerate(trace):
        if isinstance(step, str):
            st.markdown(f"`{step}`")
            continue

        agent   = step.get("agent", "Agent")
        status  = step.get("status", "ok")
        summary = step.get("summary", "")
        detail  = step.get("detail", [])

        meta         = AGENT_META.get(agent, {"icon": "⚙️", "color": "#888"})
        agent_color  = meta["color"]
        agent_icon   = meta["icon"]
        status_color = STATUS_COLOR.get(status, "#888")
        status_mark  = STATUS_ICON.get(status, "·")
        is_last      = i == len(trace) - 1

        st.markdown(
            f"""
            <div style="display:flex; align-items:flex-start; gap:10px; margin-bottom:{'4px' if not is_last else '0'};">
              <div style="display:flex; flex-direction:column; align-items:center; min-width:32px;">
                <div style="
                  width:32px; height:32px; border-radius:50%;
                  background:{agent_color}22; border:2px solid {agent_color};
                  display:flex; align-items:center; justify-content:center;
                  font-size:15px; flex-shrink:0;">
                  {agent_icon}
                </div>
                {'<div style="width:2px; flex:1; min-height:12px; background:#e0e0e0; margin-top:2px;"></div>' if not is_last else ''}
              </div>
              <div style="flex:1; padding-bottom:{'10px' if not is_last else '0'};">
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:2px;">
                  <span style="font-weight:600; font-size:13px; color:{agent_color};">{agent}</span>
                  <span style="
                    font-size:11px; font-weight:600; color:{status_color};
                    background:{status_color}18; border:1px solid {status_color}44;
                    border-radius:10px; padding:1px 7px;">
                    {status_mark} {status.upper()}
                  </span>
                </div>
                <div style="font-size:13px; color:#444; line-height:1.4;">{summary}</div>
                {''.join(f'<div style="font-size:12px; color:#777; margin-top:3px; padding-left:8px; border-left:2px solid {agent_color}44;">· {d}</div>' for d in detail) if detail else ''}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _make_download_button(rows, response_text: str, key: str, validated_sql: str = ""):
    """Render CSV download button.

    The executor now returns the full result set (up to a 50,000-row safety cap).
    We simply dump the already-fetched rows to CSV — no extra DB round-trip —
    unless we hit the 50k cap, in which case we re-run without the cap to get
    the complete result for the user.
    """
    from agents.executor import ROW_LIMIT, execute_unlimited

    if rows:
        import pandas as pd

        hit_cap = len(rows) >= ROW_LIMIT and validated_sql

        if hit_cap:
            @st.cache_data(show_spinner=False, ttl=300)
            def _fetch_all(sql: str):
                all_rows, err = execute_unlimited(sql)
                if err or not all_rows:
                    return None
                buf = io.BytesIO()
                pd.DataFrame(all_rows).to_csv(buf, index=False, encoding="utf-8")
                return buf.getvalue(), len(all_rows)

            result = _fetch_all(validated_sql)
            if result:
                csv_data, total = result
                st.download_button(
                    label=f"⬇ Download CSV ({total:,} rows — full result)",
                    data=csv_data,
                    file_name="idre_result.csv",
                    mime="text/csv",
                    key=f"dl_all_{key}",
                )
                return

        # Normal path — dump already-fetched rows directly
        buf = io.BytesIO()
        pd.DataFrame(rows).to_csv(buf, index=False, encoding="utf-8")
        st.download_button(
            label=f"⬇ Download CSV ({len(rows):,} rows)",
            data=buf.getvalue(),
            file_name="idre_result.csv",
            mime="text/csv",
            key=f"dl_{key}",
        )
    elif response_text:
        st.download_button(
            label="⬇ Download TXT",
            data=response_text.encode("utf-8"),
            file_name="idre_result.txt",
            mime="text/plain",
            key=f"dl_{key}",
        )


# ── Session state init ─────────────────────────────────────────────────────────
_SS_DEFAULTS = {
    "messages":             [],
    "session_id":           str(uuid.uuid4()),
    "last_result":          {},
    "pending_query":        None,
    "conversation_history": [],
    "pending_clarification": None,
    # Developer mode toggles (stored in session_state so they survive reruns)
    "dev_show_sql":          False,
    "dev_show_trace":        False,
    "dev_show_explanation":  True,
    "dev_show_suggestions":  True,
    "dev_show_assumptions":  False,
    "dev_show_stats":        False,
    "dev_show_tokens":       False,
    "dev_feedback_mode":     False,
    # Identity (set by post-auth prompt, None = not asked yet)
    "user_identity":         None,
    # Feedback state keyed by msg_key
    "feedback_pending":      {},
    # Last pipeline result stored for feedback capture
    "last_pipeline_results": {},
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


st.title("📊 IDRE Reports Bot — V8 (MCP + Tools)")
st.caption("Ask questions about disputes, payments, and cases in plain English.")

# ── API Key check ──────────────────────────────────────────────────────────────
if not os.getenv("Gemini_API_Key"):
    st.error(
        "**Gemini API key not found.**\n\n"
        "Set it in your `.env` file:\n"
        "```\nGemini_API_Key=your_api_key_here\n```\n"
        "Then restart the app."
    )
    st.stop()

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    # Persona / role selector
    from utils.permissions import get_all_roles, get_role_display
    ROLE_OPTIONS = get_all_roles()
    ROLE_LABELS  = {r: f"{r} — {get_role_display(r)}" for r in ROLE_OPTIONS}
    selected_role = st.selectbox(
        "Your persona",
        options=ROLE_OPTIONS,
        format_func=lambda r: ROLE_LABELS[r],
        index=0,
        help="Controls which tables you can query. VO = read-only; MA = full access; DQD = debug.",
    )
    if st.session_state.get("user_role") != selected_role:
        st.session_state.user_role = selected_role

    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages             = []
        st.session_state.session_id           = str(uuid.uuid4())
        st.session_state.last_result          = {}
        st.session_state.conversation_history = []
        st.session_state.pending_clarification = None
        st.rerun()

    # ── Developer Options ────────────────────────────────────────────────────
    st.divider()
    with st.expander("🛠️ Developer Options", expanded=False):
        st.caption("Toggle technical details. Changes apply immediately to all messages.")

        st.session_state.dev_show_sql = st.toggle(
            "Show SQL",
            value=st.session_state.dev_show_sql,
            help="Display the generated SQL query with each response.",
        )
        st.session_state.dev_show_trace = st.toggle(
            "Show agent trace",
            value=st.session_state.dev_show_trace,
            help="Show the full pipeline execution timeline (all agent steps).",
        )
        st.session_state.dev_show_assumptions = st.toggle(
            "Show assumptions",
            value=st.session_state.dev_show_assumptions,
            help="Show interpretive decisions made when generating the query.",
        )
        st.session_state.dev_show_explanation = st.toggle(
            "Query explanation",
            value=st.session_state.dev_show_explanation,
            help="Show a plain-English description of what the SQL does.",
        )
        st.session_state.dev_show_suggestions = st.toggle(
            "Proactive suggestions",
            value=st.session_state.dev_show_suggestions,
            help="Show follow-up question chips after each response.",
        )
        st.session_state.dev_show_tokens = st.toggle(
            "Token usage",
            value=st.session_state.dev_show_tokens,
            help="Show input / output / total tokens consumed per LLM call.",
        )
        st.session_state.dev_show_stats = st.toggle(
            "Usage stats panel",
            value=st.session_state.dev_show_stats,
            help="Show queries/day, latency, top tables, and error log.",
        )
        st.session_state.dev_feedback_mode = st.toggle(
            "Query Feedback Mode",
            value=st.session_state.dev_feedback_mode,
            help="Show inline Yes/No feedback panel below every response.",
        )

        if st.session_state.dev_feedback_mode:
            st.divider()
            try:
                from utils.feedback_analytics import get_feedback_summary
                fb = get_feedback_summary()
                if fb["total"] == 0:
                    st.caption("No feedback submitted yet.")
                else:
                    col_a, col_b = st.columns(2)
                    col_a.metric("Total feedback", fb["total"])
                    col_b.metric("Accuracy", f"{fb['accuracy_pct']}%")
                    col_c, col_d = st.columns(2)
                    col_c.metric("Correct", fb["correct"])
                    col_d.metric("Incorrect", fb["incorrect"])
                    if fb["by_user"]:
                        st.markdown("**By user**")
                        for handle, total, wrong in fb["by_user"]:
                            st.markdown(
                                f"<div style='font-size:12px; color:#555;'>▪ {handle} "
                                f"— {total} total, {wrong} incorrect</div>",
                                unsafe_allow_html=True,
                            )
                    if fb["top_error_categories"]:
                        st.markdown("**Top error types**")
                        for cat, cnt in fb["top_error_categories"]:
                            st.markdown(
                                f"<div style='font-size:11px; color:#c0392b;'>"
                                f"▪ {cat} ({cnt})</div>",
                                unsafe_allow_html=True,
                            )
            except Exception:
                st.caption("Feedback stats unavailable.")

        if st.session_state.dev_show_stats:
            st.divider()
            try:
                from utils.audit_analytics import get_summary_stats
                stats = get_summary_stats()
                if stats["all_time_count"] == 0:
                    st.caption("No queries logged yet.")
                else:
                    col_a, col_b = st.columns(2)
                    col_a.metric("Queries today", stats["today_count"])
                    col_b.metric("Success rate",  f"{stats['success_rate']}%")
                    col_c, col_d = st.columns(2)
                    col_c.metric("Avg latency",   f"{stats['avg_latency_s']}s")
                    col_d.metric("Glossary hits",  f"{stats['glossary_pct']}%")
                    if stats["top_tables"]:
                        st.markdown("**Top tables queried**")
                        for tbl, cnt in stats["top_tables"]:
                            st.markdown(
                                f"<div style='font-size:12px; color:#555;'>▪ {tbl}"
                                f" &nbsp;<span style='color:#888;'>×{cnt}</span></div>",
                                unsafe_allow_html=True,
                            )
                    if stats["recent_errors"]:
                        st.markdown("**Recent errors**")
                        for err in stats["recent_errors"]:
                            st.markdown(
                                f"<div style='font-size:11px; color:#c0392b;'>"
                                f"{err['ts']} · {err['status']}<br>"
                                f"<span style='color:#666;'>{err['query']}</span></div>",
                                unsafe_allow_html=True,
                            )
            except Exception:
                st.caption("Stats unavailable.")

    # ── Saved queries panel ──────────────────────────────────────────────────
    st.divider()
    st.markdown("**📌 Saved Queries**")

    from utils.query_store import list_queries, delete_query as _delete_query

    saved = list_queries()
    if not saved:
        st.caption("No saved queries yet.\nType *save this as [name]* after any answer.")
    else:
        for q in saved:
            with st.container():
                col_text, col_run, col_del = st.columns([5, 2, 1])
                with col_text:
                    st.markdown(
                        f"<div style='font-size:13px; font-weight:600; line-height:1.2;'>{q['name']}</div>"
                        f"<div style='font-size:11px; color:#888; white-space:nowrap; overflow:hidden; "
                        f"text-overflow:ellipsis; max-width:140px;' title='{q['nl_query']}'>"
                        f"{q['nl_query'][:40]}{'…' if len(q['nl_query']) > 40 else ''}</div>",
                        unsafe_allow_html=True,
                    )
                with col_run:
                    if st.button("▶ Run", key=f"run_{q['name']}"):
                        st.session_state.pending_query = q["nl_query"]
                        st.rerun()
                with col_del:
                    if st.button("✕", key=f"del_{q['name']}", help="Delete this saved query"):
                        _delete_query(q["name"])
                        st.rerun()

    st.divider()
    st.caption("v8.0 · Gemini 2.0 Flash · MCP Tool-Use · No Embedding Model")


# ── Helpers: read current dev-mode prefs from session_state ───────────────────
def _show_sql():           return st.session_state.dev_show_sql
def _show_trace():         return st.session_state.dev_show_trace
def _show_explanation():   return st.session_state.dev_show_explanation
def _show_suggestions():   return st.session_state.dev_show_suggestions
def _show_assumptions():   return st.session_state.dev_show_assumptions
def _show_tokens():        return st.session_state.dev_show_tokens
def _feedback_mode():      return st.session_state.get("dev_feedback_mode", False)


_FEEDBACK_ERROR_OPTIONS = [
    "The answer or numbers shown were wrong",
    "A wrong assumption was made about my question",
    "The wrong table or data source was used",
    "The wrong columns or joins were applied",
    "The date range or filter was incorrect",
    "Other",
]


def _submit_feedback(msg: dict, notes: str, is_correct: bool, error_categories: list) -> str:
    """Write feedback record and return the new feedback_id."""
    from utils.feedback_store import build_feedback_record, write_feedback
    msg_key = msg.get("key", "")
    pipeline_result = st.session_state.get("last_pipeline_results", {}).get(msg_key, {})
    record = build_feedback_record(
        msg=msg,
        session_state=st.session_state,
        pipeline_result=pipeline_result,
        attestation=is_correct,
        notes=notes,
        error_categories=error_categories,
    )
    write_feedback(record)
    st.session_state.feedback_pending[msg_key] = {"phase": "submitted"}
    return record.feedback_id


def _submit_and_retry(msg: dict, notes: str, error_categories: list) -> None:
    """Write feedback record then rerun pipeline with correction injected."""
    from utils.feedback_store import build_feedback_record, write_feedback
    from core.orchestrator import run_query

    msg_key = msg.get("key", "")
    pipeline_result = st.session_state.get("last_pipeline_results", {}).get(msg_key, {})

    # Write the feedback record first so the original incorrect result is always preserved
    record = build_feedback_record(
        msg=msg,
        session_state=st.session_state,
        pipeline_result=pipeline_result,
        attestation=False,
        notes=notes,
        error_categories=error_categories,
    )
    write_feedback(record)
    st.session_state.feedback_pending[msg_key] = {"phase": "submitted"}

    original_prompt = pipeline_result.get("user_query") or msg.get("content", "")

    correction_context = {
        "original_query":          original_prompt,
        "error_categories":        error_categories,
        "free_text_note":          notes,
        "original_result_summary": msg.get("content", "")[:300],
        "feedback_record_id":      record.feedback_id,
    }

    # Show correction turn in chat
    correction_label = f"[Correction] {original_prompt}"
    st.session_state.messages.append({"role": "user", "content": correction_label})

    with st.chat_message("assistant"):
        with st.spinner("Retrying with your correction…"):
            try:
                result = run_query(
                    original_prompt,
                    session_id=st.session_state.session_id,
                    conversation_history=st.session_state.conversation_history,
                    clarification_attempted=False,
                    user_role=st.session_state.get("user_role", "VO"),
                    user_identity=st.session_state.get("user_identity", ""),
                    feedback_correction_context=correction_context,
                    is_feedback_retry=True,
                )
            except Exception as e:
                result = {"_pipeline_exception": str(e)}

    error = result.get("error_message") or result.get("execution_error") or result.get("_pipeline_exception")
    response_text = _safe_error_message(error) if error else result.get("formatted_response", "No response generated.")
    if not error and not _show_sql() and "**SQL used:**" in response_text:
        response_text = response_text[: response_text.index("**SQL used:**")].strip()

    new_key = str(uuid.uuid4())
    new_msg = {
        "role":          "assistant",
        "content":       response_text,
        "trace":         result.get("agent_trace", []),
        "rows":          result.get("query_result"),
        "validated_sql": result.get("validated_sql", ""),
        "explanation":   result.get("query_explanation", ""),
        "suggestions":   result.get("proactive_suggestions", []),
        "assumptions":   result.get("assumptions", []),
        "chart_config":  result.get("chart_config"),
        "token_usage":   result.get("token_usage", {}),
        "key":           new_key,
    }
    st.session_state.messages.append(new_msg)
    st.session_state.last_pipeline_results[new_key] = result
    st.rerun()


def _render_feedback_panel(msg: dict) -> None:
    """Inline Yes/No feedback panel rendered below each assistant response."""
    msg_key = msg.get("key", "")
    fb_state = st.session_state.feedback_pending.get(msg_key, {})
    phase = fb_state.get("phase", "awaiting")

    if phase == "submitted":
        st.markdown(
            "<div style='font-size:12px; color:#27AE60; margin-top:6px;'>"
            "✓ Feedback recorded. Thank you.</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        "<hr style='margin:10px 0; border-color:#eee;'>"
        "<div style='font-size:12px; color:#888; margin-bottom:4px;'>"
        "Did this answer your question correctly?</div>",
        unsafe_allow_html=True,
    )

    col_yes, col_no, _ = st.columns([1, 1, 4])
    with col_yes:
        yes_clicked = st.button("✓ Yes", key=f"fb_yes_{msg_key}", use_container_width=True)
    with col_no:
        no_clicked = st.button("✗ No", key=f"fb_no_{msg_key}", use_container_width=True)

    notes = st.text_area(
        "Notes",
        key=f"fb_notes_{msg_key}",
        height=60,
        placeholder="Any additional context…",
        label_visibility="collapsed",
    )

    if phase == "error_detail":
        st.markdown(
            "<div style='font-size:12px; color:#888; margin-top:6px;'>"
            "What was wrong? (select all that apply)</div>",
            unsafe_allow_html=True,
        )
        selected = []
        for opt in _FEEDBACK_ERROR_OPTIONS:
            if st.checkbox(opt, key=f"fb_err_{msg_key}_{hash(opt)}"):
                selected.append(opt)
        st.session_state.feedback_pending[msg_key]["selected_errors"] = selected

        col_sub, col_retry, _ = st.columns([2, 2, 2])
        with col_sub:
            if st.button("Submit Feedback", key=f"fb_submit_{msg_key}", type="primary"):
                errs = st.session_state.feedback_pending[msg_key].get("selected_errors", [])
                _submit_feedback(msg, notes, is_correct=False, error_categories=errs)
                st.rerun()
        with col_retry:
            if st.button("Retry with Correction", key=f"fb_retry_{msg_key}"):
                errs = st.session_state.feedback_pending[msg_key].get("selected_errors", [])
                _submit_and_retry(msg, notes, error_categories=errs)

    if yes_clicked:
        _submit_feedback(msg, notes, is_correct=True, error_categories=[])
        st.rerun()
    elif no_clicked:
        st.session_state.feedback_pending[msg_key] = {"phase": "error_detail", "selected_errors": []}
        st.rerun()


def _render_message_extras(msg: dict):
    """
    Render the developer-controlled extras for a stored message.
    Called both for history replay and for the live result.
    Reads dev prefs from session_state so toggling re-renders immediately.
    """
    rows        = msg.get("rows")
    trace       = msg.get("trace", [])
    explanation = msg.get("explanation", "")
    suggestions = msg.get("suggestions", [])
    assumptions = msg.get("assumptions", [])
    msg_key     = msg.get("key", str(hash(msg.get("content", ""))))

    # Chart (always shown — it's part of the data, not a dev detail)
    chart_config = msg.get("chart_config")
    if chart_config and rows:
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            ctype = chart_config.get("type")
            x_col = chart_config.get("x_col")
            y_col = chart_config.get("y_col")
            if ctype == "bar_chart" and x_col and y_col:
                cols_to_use = [y_col] if isinstance(y_col, str) else y_col
                st.bar_chart(df.set_index(x_col)[cols_to_use])
            elif ctype == "line_chart" and x_col and y_col:
                y_cols = [y_col] if isinstance(y_col, str) else y_col
                st.line_chart(df.set_index(x_col)[y_cols])
            elif ctype == "pie_chart":
                label_col = chart_config.get("label_col", x_col)
                value_col = chart_config.get("value_col", y_col)
                if label_col and value_col:
                    import altair as alt
                    pie = alt.Chart(df).mark_arc().encode(
                        theta=alt.Theta(field=value_col, type="quantitative"),
                        color=alt.Color(field=label_col, type="nominal"),
                        tooltip=[label_col, value_col],
                    ).properties(title=chart_config.get("title", ""))
                    st.altair_chart(pie, use_container_width=True)
            elif ctype == "stacked_bar" and x_col:
                y_cols = chart_config.get("y_cols", [])
                if y_cols:
                    st.bar_chart(df.set_index(x_col)[y_cols])
            elif ctype == "scatter_plot":
                sc_x = chart_config.get("x_col")
                sc_y = chart_config.get("y_col")
                if sc_x and sc_y:
                    import altair as alt
                    scatter = alt.Chart(df).mark_circle(size=60).encode(
                        x=sc_x, y=sc_y,
                        tooltip=list(df.columns[:5]),
                    ).properties(title=chart_config.get("title", ""))
                    st.altair_chart(scatter, use_container_width=True)
        except Exception:
            pass

    # Narrative (V6 — multi-sentence insight paragraph)
    narrative = msg.get("narrative", "")
    if narrative:
        st.markdown(
            f"<div style='font-size:13px; color:#444; background:#f8f9fa; "
            f"border-left:3px solid #3498DB; padding:8px 12px; margin-top:8px; "
            f"border-radius:4px;'>{narrative}</div>",
            unsafe_allow_html=True,
        )

    # Query explanation
    if _show_explanation() and explanation:
        st.markdown(
            f"<div style='font-size:13px; color:#666; margin-top:6px;'>ℹ️ {explanation}</div>",
            unsafe_allow_html=True,
        )

    # Assumptions
    if _show_assumptions() and assumptions:
        with st.expander("💡 Assumptions made", expanded=False):
            for a in assumptions:
                st.markdown(f"- {a}")

    # Proactive suggestions
    if _show_suggestions() and suggestions:
        st.markdown(
            "<div style='font-size:12px; color:#888; margin-top:10px; margin-bottom:4px;'>"
            "💡 You might also ask:</div>",
            unsafe_allow_html=True,
        )
        chip_cols = st.columns(len(suggestions))
        for col, suggestion in zip(chip_cols, suggestions):
            with col:
                if st.button(
                    suggestion,
                    key=f"sugg_{msg_key}_{hash(suggestion)}",
                    use_container_width=True,
                ):
                    st.session_state.pending_query = suggestion
                    st.rerun()

    # Agent trace
    if _show_trace() and trace:
        with st.expander("Pipeline trace", expanded=False):
            render_agent_trace(trace)

    # Token usage
    if _show_tokens():
        token_usage = msg.get("token_usage") or {}
        if token_usage:
            with st.expander("Token usage", expanded=True):
                total_in = total_out = total_all = 0
                rows_data = []
                for agent, tok in token_usage.items():
                    i, o, t = tok.get("input", 0), tok.get("output", 0), tok.get("total", 0)
                    total_in += i; total_out += o; total_all += t
                    rows_data.append({"Agent": agent, "Input": f"{i:,}", "Output": f"{o:,}", "Total": f"{t:,}"})
                rows_data.append({"Agent": "**TOTAL**", "Input": f"**{total_in:,}**", "Output": f"**{total_out:,}**", "Total": f"**{total_all:,}**"})
                import pandas as pd
                st.table(pd.DataFrame(rows_data).set_index("Agent"))

    # Download button (skip for clarification messages)
    if not msg.get("is_clarification"):
        _make_download_button(
            rows,
            msg.get("content", ""),
            key=msg_key,
            validated_sql=msg.get("validated_sql", ""),
        )

    # Feedback panel — only when dev_feedback_mode is ON and not a clarification
    if _feedback_mode() and not msg.get("is_clarification"):
        _render_feedback_panel(msg)


# ── Chat history ───────────────────────────────────────────────────────────────
st.title("IDRE Reports Bot — V8")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        # Strip SQL block from content if SQL toggle is off
        content = msg["content"]
        if msg["role"] == "assistant" and not _show_sql() and "**SQL used:**" in content:
            content = content[: content.index("**SQL used:**")].strip()
        st.markdown(content)
        if msg["role"] == "assistant":
            _render_message_extras(msg)


# ── Input handling ─────────────────────────────────────────────────────────────
from utils.query_store import detect_save_intent, detect_run_intent, save_query, get_query

raw_prompt = st.chat_input("Ask about disputes, payments, or cases…  |  save this as [name]  |  run [name]")
prompt = st.session_state.pending_query or raw_prompt

if st.session_state.pending_query:
    st.session_state.pending_query = None

if prompt:
    if not os.environ.get("Gemini_API_Key"):
        st.error("Please enter your Gemini API key in the sidebar.")
        st.stop()

    # ── Intent: save this as <name> ─────────────────────────────────────────
    save_name = detect_save_intent(prompt)
    if save_name:
        last = st.session_state.last_result
        if not last.get("validated_sql") and not last.get("generated_sql"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Nothing to save yet — ask a question first, then save the result.",
                "trace": [], "rows": None, "key": str(uuid.uuid4()),
            })
        else:
            save_query(
                name=save_name,
                nl_query=last.get("resolved_query") or last.get("user_query", ""),
                sql=last.get("validated_sql") or last.get("generated_sql", ""),
                assumptions=last.get("assumptions", []),
                session_id=st.session_state.session_id,
            )
            reply = f'Saved as **"{save_name}"**. You can run it anytime from the sidebar or by typing *run {save_name}*.'
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.messages.append({
                "role": "assistant", "content": reply, "trace": [], "rows": None,
                "key": str(uuid.uuid4()),
            })
        st.rerun()

    # ── Intent: run <name> ──────────────────────────────────────────────────
    run_name = detect_run_intent(prompt)
    if run_name:
        saved_q = get_query(run_name)
        if not saved_q:
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.messages.append({
                "role": "assistant",
                "content": f'No saved query named **"{run_name}"**. Check the sidebar for your saved queries.',
                "trace": [], "rows": None, "key": str(uuid.uuid4()),
            })
            st.rerun()
        else:
            prompt = saved_q["nl_query"]

    # ── Clarification reply ──────────────────────────────────────────────────
    clarification_attempted = False
    if st.session_state.pending_clarification:
        original_query = st.session_state.pending_clarification["original_query"]
        prompt = f"{original_query} — clarification: {prompt}"
        clarification_attempted = True
        st.session_state.pending_clarification = None

    # ── Normal pipeline run ─────────────────────────────────────────────────
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            result = {}
            try:
                from core.orchestrator import run_query
                result = run_query(
                    prompt,
                    session_id=st.session_state.session_id,
                    conversation_history=st.session_state.conversation_history,
                    clarification_attempted=clarification_attempted,
                    user_role=st.session_state.get("user_role", "VO"),
                    user_identity=st.session_state.get("user_identity", ""),
                )
                st.session_state.last_result = result
            except Exception as e:
                result = {"_pipeline_exception": str(e)}

        # ── Pipeline paused for clarification ───────────────────────────────
        if result.get("needs_clarification"):
            question = result["clarification_question"]
            st.session_state.pending_clarification = {
                "original_query": result.get("resolved_query") or result.get("user_query", prompt),
                "question":       question,
            }
            response_text = f"Before I run that query, I have a quick question:\n\n{question}"
            msg_key = str(uuid.uuid4())
            msg_dict = {
                "role": "assistant", "content": response_text,
                "trace": result.get("agent_trace", []),
                "rows": None, "explanation": "", "suggestions": [],
                "assumptions": [], "chart_config": None,
                "token_usage": result.get("token_usage", {}), "key": msg_key,
                "is_clarification": True,
            }
            st.markdown(response_text)
            _render_message_extras(msg_dict)
            st.session_state.messages.append(msg_dict)
            st.session_state.last_pipeline_results[msg_key] = result
            st.stop()

        # ── Pipeline exception ───────────────────────────────────────────────
        if result.get("_pipeline_exception"):
            response_text = _safe_error_message(result['_pipeline_exception'])
            msg_dict = {
                "role": "assistant", "content": response_text,
                "trace": [], "rows": None, "explanation": "", "suggestions": [],
                "assumptions": [], "chart_config": None, "key": str(uuid.uuid4()),
            }
            st.markdown(response_text)
            _render_message_extras(msg_dict)
            st.session_state.messages.append(msg_dict)
            st.stop()

        # ── Normal result ────────────────────────────────────────────────────
        error = result.get("error_message") or result.get("execution_error")
        rows  = result.get("query_result")

        if error:
            response_text = _safe_error_message(error)
            sql = result.get("generated_sql", "")
            if sql and _show_sql():
                response_text += f"\n\n**SQL attempted (for reference):**\n```sql\n{sql[:500]}\n```"
        else:
            response_text = result.get("formatted_response", "No response generated.")
            if not _show_sql() and "**SQL used:**" in response_text:
                response_text = response_text[: response_text.index("**SQL used:**")].strip()

        # Accumulate session history — only on clean successful runs
        if not error and not result.get("needs_clarification"):
            summary = _extract_summary(result.get("formatted_response", ""))
            st.session_state.conversation_history.append({
                "query":   prompt,
                "summary": summary,
            })

        msg_key = str(uuid.uuid4())
        msg_dict = {
            "role":           "assistant",
            "content":        response_text,
            "trace":          result.get("agent_trace", []),
            "rows":           rows,
            "explanation":    result.get("query_explanation", ""),
            "narrative":      result.get("query_narrative", ""),
            "suggestions":    result.get("proactive_suggestions", []),
            "assumptions":    result.get("assumptions", []),
            "chart_config":   result.get("chart_config"),
            "token_usage":    result.get("token_usage", {}),
            "slide_metadata": result.get("slide_metadata"),
            "tooltips":       result.get("computed_column_tooltips", {}),
            "cell_styles":    result.get("cell_styles", {}),
            "key":            msg_key,
        }

        st.markdown(response_text)
        _render_message_extras(msg_dict)
        st.session_state.messages.append(msg_dict)
        st.session_state.last_pipeline_results[msg_key] = result
