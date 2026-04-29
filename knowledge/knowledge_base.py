"""
Platform Knowledge Base — loads pre-processed code intelligence data
from the IDRE codebase (file summaries, repo map, module keywords)
and provides query interfaces for the reports bot pipeline.
"""
import json
import os
from functools import lru_cache
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@lru_cache(maxsize=1)
def load_file_summaries() -> list[dict]:
    path = os.path.join(DATA_DIR, "file_summaries.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_module_keywords() -> dict[str, list[str]]:
    path = os.path.join(DATA_DIR, "module_keywords.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_repo_map() -> str:
    path = os.path.join(DATA_DIR, "repo_map.txt")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=1)
def load_platform_rules() -> dict:
    path = os.path.join(DATA_DIR, "platform_rules.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def search_by_concepts(concepts: list[str], top_k: int = 10) -> list[dict]:
    """Find files whose domain_concepts overlap with the given concepts."""
    summaries = load_file_summaries()
    concepts_lower = {c.lower() for c in concepts}
    scored = []
    for s in summaries:
        file_concepts = {c.lower() for c in s.get("domain_concepts", [])}
        overlap = len(concepts_lower & file_concepts)
        if overlap > 0:
            scored.append((overlap, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:top_k]]


def get_files_for_module(module: str) -> list[dict]:
    summaries = load_file_summaries()
    return [s for s in summaries if s.get("module", "").lower() == module.lower()]


def get_api_routes() -> list[dict]:
    """Return all files that define API routes."""
    summaries = load_file_summaries()
    return [s for s in summaries if s.get("api_routes")]


def get_report_files() -> list[dict]:
    """Return files related to reporting functionality."""
    summaries = load_file_summaries()
    results = []
    for s in summaries:
        path = s.get("path", "").lower()
        concepts = [c.lower() for c in s.get("domain_concepts", [])]
        if ("report" in path or "analytics" in path or
            any("report" in c for c in concepts) or
            any("analytics" in c for c in concepts)):
            results.append(s)
    return results


def get_platform_context_for_query(query: str) -> str:
    """
    Build a compact platform context string relevant to the user's query.
    This is injected into the SQL Writer's prompt to improve accuracy.
    """
    rules = load_platform_rules()
    if not rules:
        return ""

    query_lower = query.lower()
    context_parts = []

    # Always include status enums and pricing if query mentions related terms
    status_keywords = ["status", "case", "open", "closed", "pending", "eligible",
                       "ineligible", "determination", "arbitration", "rfi", "default",
                       "closure", "payment", "dismissed"]
    if any(kw in query_lower for kw in status_keywords):
        statuses = rules.get("case_statuses", {})
        if statuses:
            lines = ["=== IDRE Case Status Reference ==="]
            for status, desc in statuses.items():
                lines.append(f"  {status}: {desc}")
            context_parts.append("\n".join(lines))

    payment_keywords = ["payment", "paid", "unpaid", "fee", "refund", "amount",
                        "invoice", "payout", "disbursement", "balance", "allocation",
                        "p=0", "p=1", "p=2", "overdue", "outstanding"]
    if any(kw in query_lower for kw in payment_keywords):
        payment_rules = rules.get("payment_rules", {})
        if payment_rules:
            lines = ["=== IDRE Payment & Pricing Rules ==="]
            for key, val in payment_rules.items():
                if isinstance(val, dict):
                    lines.append(f"  {key}:")
                    for k2, v2 in val.items():
                        lines.append(f"    {k2}: {v2}")
                else:
                    lines.append(f"  {key}: {val}")
            context_parts.append("\n".join(lines))

    report_keywords = ["report", "analytics", "dashboard", "export", "csv",
                       "daily", "fund", "transaction", "performance", "team",
                       "due date", "variance", "balance"]
    if any(kw in query_lower for kw in report_keywords):
        reports = rules.get("existing_reports", [])
        if reports:
            lines = ["=== IDRE Existing Reports (what the platform generates) ==="]
            for r in reports:
                lines.append(f"  {r['name']}: {r['description']}")
                if r.get("key_metrics"):
                    lines.append(f"    Key metrics: {', '.join(r['key_metrics'])}")
            context_parts.append("\n".join(lines))

    role_keywords = ["role", "access", "permission", "admin", "arbitrator",
                     "specialist", "accounting", "manager"]
    if any(kw in query_lower for kw in role_keywords):
        roles = rules.get("platform_roles", {})
        if roles:
            lines = ["=== IDRE Platform Roles ==="]
            for role, desc in roles.items():
                lines.append(f"  {role}: {desc}")
            context_parts.append("\n".join(lines))

    # Business logic for specific calculations
    calc_keywords = ["processing time", "duration", "how long", "average time",
                     "days", "deadline", "due date", "overdue", "sla"]
    if any(kw in query_lower for kw in calc_keywords):
        calcs = rules.get("calculations", {})
        if calcs:
            lines = ["=== IDRE Business Calculations ==="]
            for name, formula in calcs.items():
                lines.append(f"  {name}: {formula}")
            context_parts.append("\n".join(lines))

    org_keywords = ["organization", "org", "provider", "health plan", "party",
                    "initiating", "non-initiating", "ip", "nip", "member"]
    if any(kw in query_lower for kw in org_keywords):
        org_rules = rules.get("organization_rules", {})
        if org_rules:
            lines = ["=== IDRE Organization & Party Rules ==="]
            for key, val in org_rules.items():
                lines.append(f"  {key}: {val}")
            context_parts.append("\n".join(lines))

    arb_keywords = ["arbitrat", "decision", "determination", "award", "winner",
                    "split", "ruling"]
    if any(kw in query_lower for kw in arb_keywords):
        arb_rules = rules.get("arbitration_rules", {})
        if arb_rules:
            lines = ["=== IDRE Arbitration Rules ==="]
            for key, val in arb_rules.items():
                lines.append(f"  {key}: {val}")
            context_parts.append("\n".join(lines))

    if not context_parts:
        # Provide minimal context for any query
        summary = rules.get("platform_summary", "")
        if summary:
            context_parts.append(f"=== Platform Summary ===\n{summary}")

    return "\n\n".join(context_parts)
