"""
Ambiguity Scorer Agent — V6

V6 improvements over V5+:
1. Adaptive thresholds per user — adjust based on clarification acceptance rate
2. Domain-specific ambiguity patterns — IDRE-specific: closure types, payment types, party references
3. Confidence calibration — log scores for future calibration analysis
"""
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from state.context import GraphState

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CALIBRATION_LOG = os.path.join(_DATA_DIR, "ambiguity_calibration.jsonl")
_IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_THRESHOLD = 0.30


@dataclass
class Flag:
    key: str
    label: str
    description: str
    weight: float


_FLAGS: list[Flag] = [
    Flag("vague_time", "Vague time reference",
         "No specific period — e.g. 'recent', 'lately', 'current' without a date range", 0.35),
    Flag("vague_quantity", "Vague quantity",
         "Imprecise quantity word used as a filter — e.g. 'many', 'few', 'several'", 0.20),
    Flag("unresolved_pronoun", "Unresolved pronoun",
         "Pronoun with no prior conversation history to resolve against", 0.45),
    Flag("broad_entity", "Broad entity — no filter",
         "Mentions cases/payments/disputes with no status, date, amount, or org qualifier", 0.25),
    Flag("ambiguous_metric", "Ambiguous metric",
         "'Amount' or 'total' used without specifying paid, pending, requested, or approved", 0.45),
    Flag("incomplete_range", "Incomplete date range",
         "Range expression is missing its end (e.g. 'between X and ?', 'from X to ?')", 0.60),
    # V6: domain-specific flags
    Flag("ambiguous_closure_type", "Ambiguous closure type",
         "'Closed' without specifying closure reason — IDRE has 5+ CLOSED_* statuses "
         "(default, IP, NIP, administrative, split, dismissal)", 0.30),
    Flag("ambiguous_payment_type", "Ambiguous payment type",
         "'Payment' without specifying type — IDRE has 8+ payment types "
         "(case payment, refund, CMS invoice, capitol bridge fee, etc.)", 0.35),
    Flag("ambiguous_party_reference", "Ambiguous party reference",
         "'Party' without specifying initiating vs non-initiating, or PROVIDER vs HEALTH_PLAN", 0.25),
]

_FLAG_BY_KEY = {f.key: f for f in _FLAGS}

# ── Patterns ──────────────────────────────────────────────────────────────────

_VAGUE_TIME_RE = re.compile(
    r"\b(recent(ly)?|lately|just|not long ago|a while(?: ago)?|"
    r"past few|last few|these days|soon|sometime|at some point|"
    r"currently|presently|nowadays)\b", re.IGNORECASE)

_CURRENT_VAGUE_RE = re.compile(
    r"\bcurrent\b(?!\s+(?:month|week|year|quarter|day|date|fiscal))", re.IGNORECASE)

_VAGUE_QTY_RE = re.compile(
    r"(?<!how )\b(many|few|several|a lot(?: of)?|handful(?: of)?|"
    r"numerous|a number of|some(?! of the)|a few)\b", re.IGNORECASE)

_PRONOUN_RE = re.compile(
    r"\b(it|its|they|them|their|those|these|that|such cases?|"
    r"the same|same ones?|those ones?)\b", re.IGNORECASE)

_ENTITY_RE = re.compile(r"\b(cases?|payments?|disputes?|invoices?|refunds?)\b", re.IGNORECASE)

_QUALIFIER_RE = re.compile(
    r"\b(status|paid|unpaid|pending|closed|open|ineligible|eligible|"
    r"defaulted?|arbitrat|month|week|year|day|date|amount|total|"
    r"organisation|organization|org|insurer|provider|name|"
    r"greater|less|more than|at least|before|after|between|since|"
    r"mtd|ytd|q[1-4])\b"
    r"|[A-Z]{2,}(?:_[A-Z]+)+", re.IGNORECASE)

_AMBIGUOUS_METRIC_RE = re.compile(
    r"\b(payment\s+amounts?|amounts?\s+(?:of|for|by)|sum\s+of|total\s+(?:payment|amount))\b"
    r"|\bamounts?\b", re.IGNORECASE)

_METRIC_QUALIFIER_RE = re.compile(
    r"\b(paid|unpaid|pending|approved|requested|refunded|allocated|settled|disbursed)\b", re.IGNORECASE)

_INCOMPLETE_RANGE_RE = re.compile(
    r"\band\s+\?|\bto\s+\?|\bfrom\s+\S.*\bto\s*$|\bbetween\b.*\band\s*$", re.IGNORECASE)

# V6: domain-specific patterns
_CLOSURE_VAGUE_RE = re.compile(
    r"\bclosed?\b(?!\s*(?:_|default|initiating|non.initiating|administrative|split|dismissal))",
    re.IGNORECASE)
_CLOSURE_SPECIFIC_RE = re.compile(
    r"\b(CLOSED_DEFAULT|CLOSED_INITIATING_PARTY|CLOSED_NON_INITIATING_PARTY|"
    r"CLOSED_ADMINISTRATIVE|CLOSED_SPLIT_DECISION|NOTICE_OF_DISMISSAL|"
    r"closed by (?:system|user|admin)|settlement|default(?:ed)?)\b", re.IGNORECASE)

_PAYMENT_VAGUE_RE = re.compile(r"\bpayments?\b", re.IGNORECASE)
_PAYMENT_SPECIFIC_RE = re.compile(
    r"\b(CASE_PAYMENT|REFUND|CAPITOL_BRIDGE|CMS_INVOICE|THIRD_PARTY|PARTY_REFUND|"
    r"case fee|refund|payout|cms|nacha|ach|incoming|outgoing)\b", re.IGNORECASE)

_PARTY_VAGUE_RE = re.compile(r"\bpart(?:y|ies)\b", re.IGNORECASE)
_PARTY_SPECIFIC_RE = re.compile(
    r"\b(initiating|non.initiating|IP|NIP|provider|health.plan|claimant|respondent|"
    r"filing party)\b", re.IGNORECASE)


# ── Default resolutions ──────────────────────────────────────────────────────

_DEFAULT_RESOLUTIONS: dict[str, list[re.Pattern]] = {
    "vague_time": [re.compile(r"\b(cases?|disputes?|payments?)\b", re.IGNORECASE)],
    "broad_entity": [
        re.compile(r"\bhow many\b", re.IGNORECASE),
        re.compile(r"\btotal\b", re.IGNORECASE),
        re.compile(r"\bcount\b", re.IGNORECASE),
        re.compile(r"\blist\b", re.IGNORECASE),
        re.compile(r"\bshow\b", re.IGNORECASE),
        re.compile(r"\ball\b", re.IGNORECASE),
    ],
    "ambiguous_metric": [re.compile(r"\b(revenue|fees?|paid|collected|refund)\b", re.IGNORECASE)],
    "ambiguous_closure_type": [
        re.compile(r"\b(status|breakdown|by type|by reason)\b", re.IGNORECASE),
    ],
    "ambiguous_payment_type": [
        re.compile(r"\b(breakdown|by type|all types|each type)\b", re.IGNORECASE),
    ],
}

_VAGUE_TIME_SUPPRESS = re.compile(
    r"\b(this month|last month|this week|last week|this year|last year|"
    r"today|yesterday|mtd|ytd|q[1-4]|20\d{2}|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b", re.IGNORECASE)


def _should_suppress(flag_key: str, query: str, glossary_matches: list) -> bool:
    if flag_key == "vague_time" and _VAGUE_TIME_SUPPRESS.search(query):
        return True

    if glossary_matches:
        for match in glossary_matches:
            cat = match.get("category", "")
            if flag_key == "vague_time" and cat == "time_range":
                return True
            if flag_key == "broad_entity" and cat in ("case_status", "payment_status", "payment_type", "dispute_type"):
                return True
            if flag_key == "ambiguous_metric" and cat in ("payment_type", "payment_status"):
                return True

    patterns = _DEFAULT_RESOLUTIONS.get(flag_key, [])
    for pattern in patterns:
        if pattern.search(query):
            return True

    return False


def _get_adaptive_threshold(user_preferences: dict) -> float:
    if not user_preferences:
        return DEFAULT_THRESHOLD
    explicit = user_preferences.get("ambiguity_threshold")
    if explicit is not None:
        return float(explicit)
    acceptance_rate = user_preferences.get("clarification_acceptance_rate")
    if acceptance_rate is not None:
        rate = float(acceptance_rate)
        if rate < 0.3:
            return 0.20
        elif rate > 0.7:
            return 0.40
    return DEFAULT_THRESHOLD


def _log_calibration(query: str, score: float, flags: list[str]) -> None:
    try:
        os.makedirs(os.path.dirname(_CALIBRATION_LOG), exist_ok=True)
        entry = json.dumps({
            "timestamp": datetime.now(_IST).isoformat(),
            "query": query[:200],
            "score": score,
            "flags": flags,
        }, default=str)
        with open(_CALIBRATION_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except OSError:
        pass


def score_ambiguity(query: str, conversation_history: list[dict],
                    glossary_matches: list = None) -> tuple[float, list[str]]:
    glossary_matches = glossary_matches or []
    triggered: list[str] = []

    if _VAGUE_TIME_RE.search(query) or _CURRENT_VAGUE_RE.search(query):
        triggered.append("vague_time")

    if _VAGUE_QTY_RE.search(query):
        triggered.append("vague_quantity")

    if _PRONOUN_RE.search(query) and not conversation_history:
        triggered.append("unresolved_pronoun")

    if _ENTITY_RE.search(query) and not _QUALIFIER_RE.search(query):
        triggered.append("broad_entity")

    if _AMBIGUOUS_METRIC_RE.search(query) and not _METRIC_QUALIFIER_RE.search(query):
        triggered.append("ambiguous_metric")

    if _INCOMPLETE_RANGE_RE.search(query):
        triggered.append("incomplete_range")

    # V6: domain-specific flags
    if _CLOSURE_VAGUE_RE.search(query) and not _CLOSURE_SPECIFIC_RE.search(query):
        triggered.append("ambiguous_closure_type")

    if _PAYMENT_VAGUE_RE.search(query) and not _PAYMENT_SPECIFIC_RE.search(query):
        triggered.append("ambiguous_payment_type")

    if _PARTY_VAGUE_RE.search(query) and not _PARTY_SPECIFIC_RE.search(query):
        triggered.append("ambiguous_party_reference")

    triggered = [f for f in triggered if not _should_suppress(f, query, glossary_matches)]

    score = min(sum(_FLAG_BY_KEY[k].weight for k in triggered), 1.0)
    return round(score, 2), triggered


def ambiguity_scorer_node(state: GraphState) -> GraphState:
    query = state.get("resolved_query") or state["user_query"]
    history = state.get("conversation_history", [])
    glossary = state.get("glossary_matches", [])
    user_prefs = state.get("user_preferences") or {}

    score, flags = score_ambiguity(query, history, glossary_matches=glossary)
    threshold = _get_adaptive_threshold(user_prefs)

    _log_calibration(query, score, flags)

    if not flags:
        summary = "Query is unambiguous — no flags raised"
        status = "ok"
        detail = []
    else:
        pct = int(score * 100)
        summary = f"Ambiguity score: {pct}% · {len(flags)} flag(s) raised · threshold: {int(threshold * 100)}%"
        status = "warn" if score < 0.6 else "error"
        detail = [f"{_FLAG_BY_KEY[k].label}: {_FLAG_BY_KEY[k].description}" for k in flags]

    trace_entry = {
        "agent": "Ambiguity Scorer",
        "status": status,
        "summary": summary,
        "detail": detail,
    }
    trace = state.get("agent_trace", []) + [trace_entry]

    return {
        **state,
        "ambiguity_score": score,
        "ambiguity_flags": flags,
        "agent_trace": trace,
    }
