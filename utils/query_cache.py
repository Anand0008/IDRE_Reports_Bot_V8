"""
Query Result Cache

In-memory LRU cache for (resolved_query + user_role) → full pipeline result.
Avoids re-running LLM + DB for identical queries within the TTL window.

TTL tiers:
  - Live-data queries ("today", "now", "right now"):  2 min
  - MTD / this-week / this-month queries:             10 min
  - All other queries:                                30 min
"""
import re
import time
from collections import OrderedDict
from threading import Lock

_TTL_LIVE    = 2  * 60   # seconds
_TTL_MTD     = 10 * 60
_TTL_DEFAULT = 30 * 60
_MAX_ENTRIES = 200

_LIVE_RE = re.compile(
    r"\b(today|right now|just now|at this moment|currently open|live)\b",
    re.IGNORECASE,
)
_MTD_RE = re.compile(
    r"\b(this month|this week|mtd|month to date|week to date|wtd|this year|ytd)\b",
    re.IGNORECASE,
)


def _ttl_for(query: str) -> int:
    if _LIVE_RE.search(query):
        return _TTL_LIVE
    if _MTD_RE.search(query):
        return _TTL_MTD
    return _TTL_DEFAULT


class QueryCache:
    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._lock = Lock()
        self._max = max_entries

    def _key(self, resolved_query: str, user_role: str) -> str:
        return f"{user_role}::{resolved_query.strip().lower()}"

    def get(self, resolved_query: str, user_role: str) -> dict:
        key = self._key(resolved_query, user_role)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() > entry["expires_at"]:
                del self._store[key]
                return None
            # LRU: move to end
            self._store.move_to_end(key)
            return entry["payload"]

    def put(self, resolved_query: str, user_role: str, payload: dict) -> None:
        key = self._key(resolved_query, user_role)
        ttl = _ttl_for(resolved_query)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = {
                "payload":    payload,
                "expires_at": time.time() + ttl,
                "ttl":        ttl,
            }
            # Evict oldest when over capacity
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def invalidate(self, resolved_query: str, user_role: str) -> None:
        key = self._key(resolved_query, user_role)
        with self._lock:
            self._store.pop(key, None)

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            alive = sum(1 for e in self._store.values() if now <= e["expires_at"])
            return {"entries": len(self._store), "alive": alive}


# Module-level singleton
_cache = QueryCache()


def get_cached(resolved_query: str, user_role: str) -> dict:
    return _cache.get(resolved_query, user_role)


def put_cached(resolved_query: str, user_role: str, payload: dict) -> None:
    _cache.put(resolved_query, user_role, payload)


def cache_stats() -> dict:
    return _cache.stats()
