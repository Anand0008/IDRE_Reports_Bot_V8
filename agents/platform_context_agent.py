"""
Platform Context Agent — V6

V6 improvements over V5+:
1. Version-aware context — tag knowledge by schema version
2. Confidence scoring — code-derived rules > inferred rules
3. Automatic knowledge refresh — warn when data is stale
4. Query-specific pruning — limit to top 3 most relevant sections
"""
import os
import time
from state.context import GraphState
from knowledge.knowledge_base import (
    get_platform_context_for_query,
    search_by_concepts,
    load_platform_rules,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge", "data")
_STALE_THRESHOLD_DAYS = 7


def _extract_query_concepts(query: str) -> list[str]:
    query_lower = query.lower()
    concept_keywords = {
        "payment": ["payment", "pay", "fee", "amount", "fund", "refund", "disbursement"],
        "case": ["case", "dispute", "filing", "claim"],
        "arbitration": ["arbitration", "decision", "determination", "award", "arbitrator"],
        "eligibility": ["eligibility", "eligible", "qualify", "review", "rfi"],
        "organization": ["organization", "org", "provider", "health plan", "insurer"],
        "invoice": ["invoice", "billing", "cms"],
        "banking": ["bank", "ach", "nacha", "routing"],
        "report": ["report", "analytics", "dashboard", "export", "summary"],
    }
    matched = []
    for concept, keywords in concept_keywords.items():
        if any(kw in query_lower for kw in keywords):
            matched.append(concept)
    return matched


def _get_code_intelligence_context(concepts: list[str], max_files: int = 5) -> str:
    if not concepts:
        return ""
    files = search_by_concepts(concepts, top_k=max_files)
    if not files:
        return ""
    lines = ["=== Relevant IDRE Platform Code Context ==="]
    for f in files:
        purpose = f.get("purpose", "")
        path = f.get("path", "")
        exports = f.get("key_exports", [])
        api_routes = f.get("api_routes", [])
        if purpose:
            line = f"  {path}: {purpose}"
            if api_routes:
                line += f" (routes: {', '.join(api_routes[:3])})"
            if exports:
                line += f" (exports: {', '.join(exports[:3])})"
            lines.append(line)
    return "\n".join(lines)


def _check_data_staleness() -> list[str]:
    warnings = []
    if not os.path.exists(_DATA_DIR):
        return warnings
    now = time.time()
    threshold = _STALE_THRESHOLD_DAYS * 86400
    for fname in os.listdir(_DATA_DIR):
        fpath = os.path.join(_DATA_DIR, fname)
        if os.path.isfile(fpath):
            age_days = (now - os.path.getmtime(fpath)) / 86400
            if age_days > _STALE_THRESHOLD_DAYS:
                warnings.append(f"{fname}: {int(age_days)} days old")
    return warnings


def _score_section_relevance(section: str, query: str, tables: list[str]) -> float:
    score = 0.0
    query_words = set(query.lower().split())
    section_lower = section.lower()
    for word in query_words:
        if len(word) > 2 and word in section_lower:
            score += 1.0
    for table in tables:
        if table.lower() in section_lower:
            score += 2.0
    return score


def _prune_context(context: str, query: str, tables: list[str], max_sections: int = 3) -> str:
    if not context:
        return context
    sections = context.split("\n\n")
    if len(sections) <= max_sections:
        return context

    scored = []
    for section in sections:
        score = _score_section_relevance(section, query, tables)
        scored.append((score, section))

    scored.sort(key=lambda x: -x[0])
    top_sections = [s for _, s in scored[:max_sections]]
    return "\n\n".join(top_sections)


_CONFIDENCE_LABELS = {
    "code_derived": 0.9,
    "business_rule": 0.7,
    "inferred": 0.5,
}


def _add_confidence_markers(context: str) -> str:
    if not context:
        return context
    lines = context.split("\n")
    marked = []
    for line in lines:
        if line.startswith("=== Relevant IDRE Platform Code Context"):
            marked.append(f"{line} [confidence: 0.9 — code-derived]")
        elif line.startswith("=== IDRE"):
            marked.append(f"{line} [confidence: 0.7 — business rule]")
        else:
            marked.append(line)
    return "\n".join(marked)


def platform_context_node(state: GraphState) -> GraphState:
    query = state.get("resolved_query") or state["user_query"]
    tables = state.get("relevant_tables", [])

    rules_context = get_platform_context_for_query(query)
    concepts = _extract_query_concepts(query)
    code_context = _get_code_intelligence_context(concepts)

    context_parts = []
    if rules_context:
        context_parts.append(rules_context)
    if code_context:
        context_parts.append(code_context)

    platform_context = "\n\n".join(context_parts) if context_parts else ""

    platform_context = _prune_context(platform_context, query, tables, max_sections=3)
    platform_context = _add_confidence_markers(platform_context)

    staleness_warnings = _check_data_staleness()

    detail = []
    if rules_context:
        rule_sections = [line for line in rules_context.split("\n") if line.startswith("===")]
        detail.append(f"Business rules: {len(rule_sections)} section(s) matched")
    if code_context:
        file_count = code_context.count("  ")
        detail.append(f"Code intelligence: {file_count} relevant file(s) found")
    if concepts:
        detail.append(f"Query concepts: {', '.join(concepts)}")
    if staleness_warnings:
        detail.append(f"Stale data files: {', '.join(staleness_warnings[:3])}")

    summary = "Platform context assembled"
    if not platform_context:
        summary = "No specific platform context matched — using schema only"
    if staleness_warnings:
        summary += f" · {len(staleness_warnings)} stale file(s) detected"

    trace_entry = {
        "agent": "Platform Context",
        "status": "warn" if staleness_warnings else ("ok" if platform_context else "warn"),
        "summary": summary,
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]

    return {
        **state,
        "platform_context": platform_context,
        "agent_trace": trace,
    }
