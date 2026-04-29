"""
Glossary Matcher  (Story 4.2 — Business Glossary Term Detection)

Scans a user query against config/business_glossary.json and returns
all matched glossary entries.

Matching strategy (in priority order):
  1. Exact phrase match (case-insensitive) against term + all aliases
  2. Substring match for multi-word aliases inside the query

Returns a deduplicated list of matched GlossaryEntry dicts, sorted by
specificity (longer matching phrase first, so "pending second payment"
beats "pending payment" when both would match).
"""
import json
import os
import re
from typing import List, Dict, Any

GLOSSARY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "business_glossary.json")

_glossary_cache: List[Dict[str, Any]] = None


def _load_glossary() -> List[Dict[str, Any]]:
    global _glossary_cache
    if _glossary_cache is None:
        with open(GLOSSARY_PATH) as f:
            data = json.load(f)
        _glossary_cache = data.get("terms", [])
    return _glossary_cache


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for matching."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\$=]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def find_matches(query: str) -> List[Dict[str, Any]]:
    """
    Return a list of matched glossary entries for the given query.
    Each entry is the full glossary term dict (term, sql_filter, etc.).
    Entries are deduplicated by `term` and sorted longest-match-first.
    """
    terms = _load_glossary()
    norm_query = _normalize(query)

    matched: Dict[str, tuple] = {}  # term_name -> (entry, match_length)

    for entry in terms:
        # All candidates: the primary term + all aliases
        candidates = [entry["term"]] + entry.get("aliases", [])

        best_match_len = 0
        for phrase in candidates:
            norm_phrase = _normalize(phrase)
            if not norm_phrase:
                continue
            # Use word-boundary aware search so "P=1" doesn't match "P=10"
            pattern = r"(?<!\w)" + re.escape(norm_phrase) + r"(?!\w)"
            if re.search(pattern, norm_query):
                if len(norm_phrase) > best_match_len:
                    best_match_len = len(norm_phrase)

        if best_match_len > 0:
            term_name = entry["term"]
            # Keep the entry with the longest matching phrase if seen again
            existing = matched.get(term_name)
            if existing is None or best_match_len > existing[1]:
                matched[term_name] = (entry, best_match_len)

    # Sort by match length descending (most specific first)
    sorted_matches = sorted(matched.values(), key=lambda x: x[1], reverse=True)
    return [entry for entry, _ in sorted_matches]


def format_glossary_context(matches: List[Dict[str, Any]]) -> str:
    """
    Produces a compact glossary block for injection into LLM prompts.
    Only includes non-time-range terms that carry sql_filter fragments.
    """
    if not matches:
        return ""

    lines = ["GLOSSARY TERMS DETECTED IN THIS QUERY (SQL filters MUST be applied verbatim):"]
    for entry in matches:
        if not entry.get("sql_filter"):
            continue
        lines.append(f'- "{entry["term"]}": {entry["definition"]}')
        lines.append(f'  SQL filter: {entry["sql_filter"]}')
        if entry.get("requires_join") and entry.get("join_table"):
            lines.append(f'  Required table: {entry["join_table"]} (must be included in FROM/JOIN)')
    return "\n".join(lines)
