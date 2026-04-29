"""
V8 MCP Tools — Static knowledge tools for the SQL writer agent.

These tools replace embedding-based RAG retrieval with direct function calls.
The SQL writer (Gemini) calls these tools on-demand via function calling
to get the exact information it needs for SQL generation.
"""
import json
import os
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge", "data")
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
SCHEMA_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "schema_catalog.json")


def _load_json(path: str) -> dict | list:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_report_cards_cache = None
_schema_catalog_cache = None
_glossary_cache = None
_platform_rules_cache = None


def _get_report_cards() -> list[dict]:
    global _report_cards_cache
    if _report_cards_cache is None:
        data = _load_json(os.path.join(DATA_DIR, "report_reference_cards.json"))
        _report_cards_cache = data.get("reports", []) if isinstance(data, dict) else []
    return _report_cards_cache


def _get_schema_catalog() -> list[dict]:
    global _schema_catalog_cache
    if _schema_catalog_cache is None:
        data = _load_json(SCHEMA_CATALOG_PATH)
        if isinstance(data, list):
            _schema_catalog_cache = data
        elif isinstance(data, dict):
            tables = data.get("tables", {})
            if isinstance(tables, dict):
                _schema_catalog_cache = [
                    {"table_name": k, **v} if isinstance(v, dict) else {"table_name": k}
                    for k, v in tables.items()
                ]
            else:
                _schema_catalog_cache = tables
        else:
            _schema_catalog_cache = []
    return _schema_catalog_cache


def _get_glossary() -> list[dict]:
    global _glossary_cache
    if _glossary_cache is None:
        data = _load_json(os.path.join(CONFIG_DIR, "business_glossary.json"))
        _glossary_cache = data.get("terms", []) if isinstance(data, dict) else []
    return _glossary_cache


def _get_platform_rules() -> dict:
    global _platform_rules_cache
    if _platform_rules_cache is None:
        _platform_rules_cache = _load_json(os.path.join(DATA_DIR, "platform_rules.json"))
    return _platform_rules_cache


# ─── Tool 1: Report Reference Card ──────────────────────────────────

def get_report_reference(report_name: str) -> str:
    """Get the ground-truth query logic for a known IDRE report.

    Args:
        report_name: Report identifier. One of: due-dates, case-analytics,
            case-balance, outstanding-payments, cms-payments, dashboard-stats,
            team-performance, unpaid-disputes, idre-payouts, daily-funds,
            daily-transactions, recent-activity, payment-variance.

    Returns:
        Formatted reference card with tables, columns, WHERE logic,
        JOINs, and reference SQL. Returns 'Not found' if no match.
    """
    cards = _get_report_cards()
    name_lower = report_name.lower().strip()

    for card in cards:
        if card.get("id", "").lower() == name_lower:
            return json.dumps({
                "name": card.get("name"),
                "tables": card.get("tables"),
                "key_columns": card.get("key_columns"),
                "where_logic": card.get("where_logic"),
                "critical_detail": card.get("critical_detail"),
                "joins": card.get("joins"),
                "order_by": card.get("order_by"),
                "reference_sql": card.get("bot_sql_equivalent"),
            }, indent=2)

    available = [c.get("id") for c in cards]
    return f"Report '{report_name}' not found. Available: {', '.join(available)}"


# ─── Tool 2: Table Schema ───────────────────────────────────────────

def get_table_schema(table_name: str) -> str:
    """Get the full schema definition for a database table.

    Args:
        table_name: MySQL table name (e.g. 'case', 'payment',
            'case_payment_allocation').

    Returns:
        JSON with table description, columns (name, type, nullable),
        foreign keys, and indexes. Returns 'Not found' if no match.
    """
    catalog = _get_schema_catalog()
    name_lower = table_name.lower().strip()

    for table in catalog:
        tbl_name = table.get("table_name", table.get("name", "")).lower()
        if tbl_name == name_lower:
            return json.dumps(table, indent=2, default=str)

    available = sorted(set(
        t.get("table_name", t.get("name", "")).lower() for t in catalog
    ))
    return f"Table '{table_name}' not found. Available: {', '.join(available)}"


# ─── Tool 3: Enum Values ────────────────────────────────────────────

def get_enum_values(column_path: str) -> str:
    """Get valid enum values for a column from platform rules.

    Args:
        column_path: Dot-notation column reference.
            Examples: 'case.status', 'payment.type', 'payment.status',
            'payment.direction', 'case.typeOfDispute'.

    Returns:
        JSON object with enum values and their descriptions.
    """
    rules = _get_platform_rules()
    path_lower = column_path.lower().strip()

    mappings = {
        "case.status": rules.get("case_statuses", {}),
        "payment.type": rules.get("payment_rules", {}).get("payment_types", {}),
        "payment.status": rules.get("payment_rules", {}).get("payment_statuses", {}),
        "payment.direction": rules.get("payment_rules", {}).get("payment_directions", {}),
        "case.typeofdispute": rules.get("dispute_types", {}),
        "case.closurereason": rules.get("closure_reasons", {}),
    }

    for key, values in mappings.items():
        if path_lower == key:
            return json.dumps(values, indent=2)

    return f"No enum mapping for '{column_path}'. Available: {', '.join(mappings.keys())}"


# ─── Tool 4: Business Term Lookup ───────────────────────────────────

def lookup_business_term(term: str) -> str:
    """Look up a business term in the IDRE glossary.

    Args:
        term: Business term to look up (e.g. 'CMS payment',
            'outstanding payment', 'entity fee', 'split decision').

    Returns:
        JSON with definition, sql_filter, applies_to_tables, and category.
    """
    glossary = _get_glossary()
    term_lower = term.lower().strip()

    for entry in glossary:
        synonyms = [s.lower() for s in entry.get("synonyms", [])]
        entry_term = entry.get("term", "").lower()
        if term_lower == entry_term or term_lower in synonyms:
            return json.dumps({
                "term": entry.get("term"),
                "definition": entry.get("definition"),
                "sql_filter": entry.get("sql_filter"),
                "applies_to_tables": entry.get("applies_to_tables"),
                "category": entry.get("category"),
            }, indent=2)

    return f"Term '{term}' not found in glossary."


# ─── Tool 5: List Available Reports ─────────────────────────────────

def list_available_reports() -> str:
    """List all known IDRE report endpoints with descriptions.

    Returns:
        JSON array of report summaries (id, name, tables used).
    """
    cards = _get_report_cards()
    summaries = [
        {"id": c.get("id"), "name": c.get("name"), "tables": c.get("tables", [])}
        for c in cards
    ]
    return json.dumps(summaries, indent=2)


# ─── Tool 6: Pricing Info ───────────────────────────────────────────

def get_pricing_info() -> str:
    """Get IDRE fee structure and pricing rules.

    Returns:
        JSON with entity fees, CMS admin fees, refund amounts,
        and internal payout amounts for Halo/VeraTru/Capitol Bridge.
    """
    rules = _get_platform_rules()
    payment_rules = rules.get("payment_rules", {})
    pricing = {
        "single_bundled": payment_rules.get("pricing_single_bundled", {}),
        "batched": payment_rules.get("pricing_batched", {}),
        "refund_amounts": payment_rules.get("refund_amounts", {}),
        "internal_payouts_single_bundled": payment_rules.get("internal_payouts_single_bundled", {}),
        "internal_payouts_batched": payment_rules.get("internal_payouts_batched", {}),
    }
    return json.dumps(pricing, indent=2)


# ─── Tool Definitions for Gemini Function Calling ────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_report_reference",
        "description": "Get the ground-truth query logic for a known IDRE report. Call this FIRST when the user asks about any of the 13 IDRE reports (due-dates, case-analytics, case-balance, outstanding-payments, cms-payments, dashboard-stats, team-performance, unpaid-disputes, idre-payouts, daily-funds, daily-transactions, recent-activity, payment-variance). The response includes the exact tables, JOINs, WHERE clauses, and reference SQL that IDRE uses.",
        "parameters": {
            "type": "object",
            "properties": {
                "report_name": {
                    "type": "string",
                    "description": "Report identifier: due-dates, case-analytics, case-balance, outstanding-payments, cms-payments, dashboard-stats, team-performance, unpaid-disputes, idre-payouts, daily-funds, daily-transactions, recent-activity, payment-variance"
                }
            },
            "required": ["report_name"]
        }
    },
    {
        "name": "get_table_schema",
        "description": "Get the full schema for a database table including columns, types, foreign keys, and indexes. Call this when you need to know what columns exist in a table or how tables relate to each other.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "MySQL table name (e.g. 'case', 'payment', 'case_payment_allocation', 'organization')"
                }
            },
            "required": ["table_name"]
        }
    },
    {
        "name": "get_enum_values",
        "description": "Get valid enum values for a database column. Call this when you need the exact set of valid values for status fields, type fields, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "column_path": {
                    "type": "string",
                    "description": "Dot-notation column path: case.status, payment.type, payment.status, payment.direction, case.typeOfDispute, case.closureReason"
                }
            },
            "required": ["column_path"]
        }
    },
    {
        "name": "lookup_business_term",
        "description": "Look up a business/domain term in the IDRE glossary. Call this when the user uses domain-specific terms you're not sure about.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "Business term to look up (e.g. 'CMS payment', 'entity fee', 'split decision')"
                }
            },
            "required": ["term"]
        }
    },
    {
        "name": "list_available_reports",
        "description": "List all 13 known IDRE reports with their names and tables. Call this when you're not sure which report the user is asking about.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_pricing_info",
        "description": "Get IDRE fee structure including entity fees, CMS admin fees, refund amounts, and internal payouts to Halo/VeraTru/Capitol Bridge. Call this for payment amount calculations.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
]

TOOL_DISPATCH = {
    "get_report_reference": get_report_reference,
    "get_table_schema": get_table_schema,
    "get_enum_values": get_enum_values,
    "lookup_business_term": lookup_business_term,
    "list_available_reports": list_available_reports,
    "get_pricing_info": get_pricing_info,
}
