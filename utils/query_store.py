"""
Query Store  (Story 2.3 — Cross-Session Saved Queries)

Persists named queries to data/saved_queries.json.
Each entry:  { name, nl_query, sql, assumptions, saved_at, session_id }
"""
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "saved_queries.json")


def _load() -> dict:
    if not os.path.exists(STORE_PATH):
        return {"queries": {}}
    with open(STORE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(store: dict) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


def _normalise(name: str) -> str:
    """Lowercase + collapse whitespace — used as the storage key."""
    return re.sub(r"\s+", " ", name.strip().lower())


def save_query(
    name: str,
    nl_query: str,
    sql: str,
    assumptions: list[str],
    session_id: str = "",
) -> None:
    store = _load()
    key = _normalise(name)
    store["queries"][key] = {
        "name": name.strip(),
        "nl_query": nl_query,
        "sql": sql,
        "assumptions": assumptions,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
    }
    _save(store)


def get_query(name: str) -> Optional[dict]:
    store = _load()
    return store["queries"].get(_normalise(name))


def delete_query(name: str) -> bool:
    """Returns True if the query existed and was deleted."""
    store = _load()
    key = _normalise(name)
    if key not in store["queries"]:
        return False
    del store["queries"][key]
    _save(store)
    return True


def list_queries() -> list[dict]:
    """Returns all saved queries sorted newest-first."""
    store = _load()
    return sorted(
        store["queries"].values(),
        key=lambda q: q.get("saved_at", ""),
        reverse=True,
    )


# ── Intent detection helpers (used by app.py) ────────────────────────────────

_SAVE_RE = re.compile(
    r"^(?:save(?:\s+this)?(?:\s+query)?|bookmark(?:\s+this)?)\s+as\s+['\"]?(.+?)['\"]?\s*$",
    re.IGNORECASE,
)

_RUN_RE = re.compile(
    r"^(?:run|execute|use|replay)(?:\s+(?:my|saved|the))?\s+['\"]?(.+?)['\"]?(?:\s+query)?\s*$",
    re.IGNORECASE,
)


def detect_save_intent(text: str) -> Optional[str]:
    """If the message is 'save this as <name>', returns the name. Else None."""
    m = _SAVE_RE.match(text.strip())
    return m.group(1).strip() if m else None


def detect_run_intent(text: str) -> Optional[str]:
    """If the message is 'run my <name>', returns the name. Else None."""
    m = _RUN_RE.match(text.strip())
    return m.group(1).strip() if m else None
