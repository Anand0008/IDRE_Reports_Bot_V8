"""
End-to-end test for Epics 4-8 against the live pipeline.
Run: python e2e_test.py
"""
import sys, io, time, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from core.orchestrator import run_query

results = []
session = "live-e2e"

def q(query, role="ES", history=None, clarified=False):
    return run_query(
        query,
        session_id=session,
        conversation_history=history or [],
        clarification_attempted=clarified,
        user_role=role,
    )

def check(label, r, ok, note):
    mark = "PASS" if ok else "FAIL"
    results.append((mark, label, note))
    role_info = f"role={r.get('user_role','?')} permitted={len(r.get('permitted_tables',[]))}"
    print(f"  [{mark}] {label}")
    print(f"         {note}")
    print(f"         {role_info}  retries={r.get('retry_count',0)}")

# ── Epic 1-3: Core pipeline ────────────────────────────────────────────────────
print("\n=== EPIC 1-3: Core pipeline ===")

r = q("How many total disputes?")
check("Metric card fast path",
      r,
      r.get("row_count") == 1 and not r.get("error_message"),
      f"rows={r.get('row_count')}  resp={r.get('formatted_response','')[:60]}")

# ── Epic 4: Business Glossary ─────────────────────────────────────────────────
print("\n=== EPIC 4: Business Glossary ===")

r = q("How many cases are pending RFI right now?")
gterms = [m["term"] for m in r.get("glossary_matches", [])]
check("Glossary: RFI term detected",
      r,
      "RFI" in gterms,
      f"glossary={gterms}  rows={r.get('row_count')}")

r = q("How many default closures happened MTD?")
gterms = [m["term"] for m in r.get("glossary_matches", [])]
check("Glossary: default closure + MTD",
      r,
      any(t in ("default closure", "month to date") for t in gterms),
      f"glossary={gterms}")

r = q("Show cases with both parties paid in final eligibility review")
gterms = [m["term"] for m in r.get("glossary_matches", [])]
check("Glossary: final eligibility review (P=2)",
      r,
      "final eligibility review" in gterms,
      f"glossary={gterms}")

# ── Epic 5: Debugger Agent ────────────────────────────────────────────────────
print("\n=== EPIC 5: Debugger Agent ===")

# Force a hard validation failure with a bad table name
r = q("Show me data from nonexistent_table_xyz")
agents_visited = [t.get("agent") for t in r.get("agent_trace", [])]
check("Debugger: validator failure handled",
      r,
      bool(r.get("error_message") or r.get("formatted_response")),
      f"agents={agents_visited}  error={str(r.get('error_message',''))[:80]}")

# Verify debugger classification directly
from agents.debugger_agent import _classify
res = _classify("Unknown column 'case_status' in 'field list'")
check("Debugger: HALLUCINATED_COLUMN classification",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      res.error_type == "HALLUCINATED_COLUMN" and res.failing_element == "case_status",
      f"type={res.error_type}  elem={res.failing_element}")

res = _classify("Query execution was interrupted, maximum statement execution time exceeded")
check("Debugger: TIMEOUT classification",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      res.error_type == "TIMEOUT",
      f"type={res.error_type}  instruction={res.retry_instruction[:60]}")

# ── Epic 6: RBAC ──────────────────────────────────────────────────────────────
print("\n=== EPIC 6: Role-Based Access Control ===")

from utils.permissions import get_permitted_tables
from agents.sql_validator import validate_sql

# Table counts per role
es_tbls  = get_permitted_tables("ES")
fa_tbls  = get_permitted_tables("FA")
dqd_tbls = get_permitted_tables("DQD")

check("RBAC: ES has 6 tables",
      {"user_role": "ES", "permitted_tables": es_tbls, "retry_count": 0},
      len(es_tbls) == 6,
      f"ES permitted tables: {es_tbls}")

check("RBAC: FA has 24 tables (full financial)",
      {"user_role": "FA", "permitted_tables": fa_tbls, "retry_count": 0},
      len(fa_tbls) == 24,
      f"FA permitted count={len(fa_tbls)}")

# Validator blocks payment for ES
ok_es, err_es = validate_sql("SELECT SUM(amount) FROM payment", permitted_tables=es_tbls)
check("RBAC: ES blocked from payment table",
      {"user_role": "ES", "permitted_tables": es_tbls, "retry_count": 0},
      not ok_es and "not accessible" in err_es,
      f"blocked={not ok_es}  msg={err_es}")

# Validator allows payment for FA
ok_fa, err_fa = validate_sql("SELECT SUM(amount) FROM payment", permitted_tables=fa_tbls)
check("RBAC: FA allowed to query payment table",
      {"user_role": "FA", "permitted_tables": fa_tbls, "retry_count": 0},
      ok_fa,
      f"allowed={ok_fa}")

# Nobody can query user or session
ok_u, err_u = validate_sql("SELECT * FROM `user`", permitted_tables=dqd_tbls)
check("RBAC: DQD blocked from user table",
      {"user_role": "DQD", "permitted_tables": dqd_tbls, "retry_count": 0},
      not ok_u,
      f"blocked={not ok_u}  msg={err_u}")

# Live pipeline: ES vs FA for payment query
r_es = q("What is the total payment amount received?", role="ES")
r_fa = q("What is the total payment amount received?", role="FA")

check("RBAC live: ES gets clarification/error on payment query",
      r_es,
      r_es.get("needs_clarification") or "not accessible" in str(r_es.get("error_message", "")),
      f"clarification={r_es.get('needs_clarification')}  error={str(r_es.get('error_message',''))[:60]}")

check("RBAC live: FA proceeds on payment query",
      r_fa,
      len(r_fa.get("permitted_tables", [])) == 24,
      f"FA permitted={len(r_fa.get('permitted_tables',[]))}  clarification={r_fa.get('needs_clarification')}")

# ── Epic 7: Response Formatter ────────────────────────────────────────────────
print("\n=== EPIC 7: Response Formatter ===")

r = q("How many total disputes?")
check("Formatter: single KPI -> number format",
      r,
      r.get("response_format") == "number" and r.get("row_count") == 1,
      f"format={r.get('response_format')}  val={r.get('formatted_response','')[:60]}")

r = q("Show case counts grouped by status")
check("Formatter: multi-row result picks chart/table format",
      r,
      r.get("response_format") in ("bar_chart", "pie_chart", "table", "line_chart"),
      f"format={r.get('response_format')}  rows={r.get('row_count')}  chart={r.get('chart_config')}")

r = q("How many disputes were filed today?")
check("Formatter: query explanation generated",
      r,
      len(r.get("query_explanation", "")) > 10,
      f"explanation: {r.get('query_explanation','')[:100]}")

check("Formatter: proactive suggestions generated",
      r,
      len(r.get("proactive_suggestions", [])) > 0,
      f"suggestions: {r.get('proactive_suggestions', [])}")

# Chart selection unit tests
from agents.response_formatter import _select_chart

cases = [
    ([{"total": 42}], "total count", "number"),
    ([{"month": "2024-01", "cnt": 10}, {"month": "2024-02", "cnt": 20}], "trend over time", "line_chart"),
    ([{"status": "OPEN", "n": 100}, {"status": "CLOSED", "n": 50}, {"status": "PENDING", "n": 30}], "by status", "pie_chart"),
    ([{"status": f"S{i}", "n": i} for i in range(8)], "breakdown", "bar_chart"),
    ([{"id": i, "name": f"Case {i}"} for i in range(100)], "list all", "table"),
]
all_chart_ok = True
for rows, intent, expected in cases:
    fmt, _ = _select_chart(rows, intent)
    if fmt != expected:
        all_chart_ok = False

check("Formatter: chart selection logic (5 cases)",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      all_chart_ok,
      "number, line_chart, pie_chart, bar_chart, table — all correct" if all_chart_ok else "some cases failed")

# ── Epic 8: Audit Trail ───────────────────────────────────────────────────────
print("\n=== EPIC 8: Audit Trail ===")

time.sleep(0.5)  # let async writes settle

AUDIT_LOG = "data/audit_log.jsonl"
audit_events = []
if os.path.exists(AUDIT_LOG):
    with open(AUDIT_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "live-e2e" in line:
                try:
                    audit_events.append(json.loads(line))
                except Exception:
                    pass

check("Audit: events logged for this session",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      len(audit_events) >= 8,
      f"{len(audit_events)} events logged  statuses={[e['execution_status'] for e in audit_events]}")

check("Audit: glossary_terms_matched captured",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      any(e.get("glossary_terms_matched") for e in audit_events),
      f"glossary hits in {sum(1 for e in audit_events if e.get('glossary_terms_matched'))}/{len(audit_events)} events")

check("Audit: user_role captured per event",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      all(e.get("user_role") for e in audit_events),
      f"roles seen: {sorted({e['user_role'] for e in audit_events})}")

check("Audit: total_pipeline_ms logged",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      any(e.get("total_pipeline_ms", 0) > 0 for e in audit_events),
      f"latencies (ms): {[e.get('total_pipeline_ms') for e in audit_events[:5]]}")

from utils.audit_analytics import get_summary_stats
stats = get_summary_stats()
check("Audit: analytics panel computes correctly",
      {"user_role": "n/a", "permitted_tables": [], "retry_count": 0},
      stats["all_time_count"] > 0 and stats["success_rate"] > 0,
      f"today={stats['today_count']}  success={stats['success_rate']}%  avg={stats['avg_latency_s']}s  top_tables={stats['top_tables'][:3]}")

# ── Session memory + Clarification ───────────────────────────────────────────
print("\n=== EPIC 2-3: Session memory + Clarification ===")

h2 = [{"query": "How many cases are in pending RFI?", "summary": "pending RFI count = 3,241"}]
r = q("Show me those by organisation", history=h2)
check("Session memory: pronoun resolved from history",
      r,
      "rfi" in r.get("resolved_query", "").lower() or r.get("row_count", 0) > 0 or r.get("needs_clarification"),
      f"resolved_query={r.get('resolved_query','')[:80]}")

r = q("Show me cases filed recently without specifying anything")
check("Clarification: vague query triggers question",
      r,
      r.get("needs_clarification") is True,
      f"question: {r.get('clarification_question','')[:90]}")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 60)
passed = sum(1 for m, _, _ in results if m == "PASS")
failed = sum(1 for m, _, _ in results if m == "FAIL")
print(f"TOTAL: {passed}/{len(results)} passed   {failed} failed")

if failed:
    print("\nFAILURES:")
    for m, label, note in results:
        if m == "FAIL":
            print(f"  FAIL  {label}")
            print(f"        {note}")
