"""Single-call entrypoint for harness use.

Wraps V8's existing core.orchestrator.run_query so the V10 test harness
can invoke V8 in-process without going through Streamlit.

Usage:
    from harness_entrypoint import run
    result = run("how many total cases are there")
    # → {"data": [...rows...], "sql": "...", "row_count": N, "agent_trace": [...]}
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
os.chdir(str(HERE))  # so config/settings.py finds .env
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def run(prompt: str, user_role: str = "MA") -> dict:
    """Run V8 pipeline once and return a dict result.

    user_role defaults to "MA" (master admin) so access-control doesn't
    filter table visibility for tests.
    """
    from core.orchestrator import run_query

    state = run_query(
        user_query=prompt,
        session_id="harness",
        user_role=user_role,
    )
    return {
        "data": state.get("query_result") or [],
        "sql": state.get("validated_sql") or state.get("generated_sql") or "",
        "row_count": state.get("row_count", 0),
        "agent_trace": state.get("agent_trace", []),
        "execution_error": state.get("execution_error"),
        "formatted_response": state.get("formatted_response", ""),
        "assumptions": state.get("assumptions", []),
    }


if __name__ == "__main__":
    # Smoke test
    import json
    r = run(sys.argv[1] if len(sys.argv) > 1 else "how many total cases are there")
    print(json.dumps({
        "row_count": r["row_count"],
        "sql": r["sql"][:200],
        "error": r["execution_error"],
    }, indent=2, default=str))
