"""
Output Formatter Agent — V6

V6 improvements over V5+:
1. User format preferences — per-session date/currency format overrides
2. Conditional formatting — cell-level styling metadata (red/green/bold)
3. Unit-aware formatting — auto-detect 0-1 vs 0-100 scale percentages
4. Locale support — US/EU/UK date and number formatting
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from state.context import GraphState


_CAMEL_SPLIT = re.compile(r"(?<!^)(?=[A-Z])")


def _tokenize(col_name: str) -> set:
    snake = _CAMEL_SPLIT.sub("_", col_name).lower()
    return {t for t in re.split(r"[_\-\s]+", snake) if t}


_CURRENCY_KEYWORDS = {
    "amount", "balance", "payment", "fee", "revenue", "cost", "price", "value",
    "disbursement", "refund", "charge", "paid", "owed", "earned",
    "dollar", "dollars", "usd", "money", "total", "subtotal", "grandtotal",
    "variance", "allocated", "expected",
}
_AMBIG_CURRENCY = {"total", "value", "expected"}

_DATE_KEYWORDS = {
    "date", "time", "created", "updated", "closed", "opened", "filed",
    "submitted", "received", "rendered", "changed", "month", "year",
    "period", "timestamp", "due", "scheduled", "paidat",
}
_DATE_SUFFIX_RE = re.compile(r"(?:_at|_on|At|On)$")
_DAYS_KEYWORDS = {"days", "duration", "elapsed", "turnaround", "lag"}
_PERCENTAGE_KEYWORDS = {"percent", "pct", "rate", "ratio", "proportion", "percentage", "win"}
_COUNT_KEYWORDS = {"count", "num", "qty", "quantity", "cnt", "total"}


_LOCALE_CONFIGS = {
    "US": {
        "date_format": "%b {day}, %Y",
        "date_format_with_time": "%b {day}, %Y %H:%M",
        "decimal_sep": ".",
        "thousands_sep": ",",
        "currency_prefix": "$",
    },
    "EU": {
        "date_format": "{day}. %b %Y",
        "date_format_with_time": "{day}. %b %Y %H:%M",
        "decimal_sep": ",",
        "thousands_sep": ".",
        "currency_prefix": "$",
    },
    "UK": {
        "date_format": "{day} %b %Y",
        "date_format_with_time": "{day} %b %Y %H:%M",
        "decimal_sep": ".",
        "thousands_sep": ",",
        "currency_prefix": "$",
    },
}


def _get_locale_config(preferences: dict) -> dict:
    locale = (preferences or {}).get("locale", "US")
    return _LOCALE_CONFIGS.get(locale, _LOCALE_CONFIGS["US"])


def _fmt_currency(val, preferences: dict = None) -> str:
    locale = _get_locale_config(preferences)
    no_cents = (preferences or {}).get("currency_no_cents", False)
    try:
        if isinstance(val, Decimal):
            f = float(val)
        elif isinstance(val, str):
            f = float(Decimal(val))
        else:
            f = float(val)
        if no_cents:
            formatted = f"{f:,.0f}"
        else:
            formatted = f"{f:,.2f}"
        if locale["decimal_sep"] != ".":
            formatted = formatted.replace(",", "TEMP").replace(".", locale["decimal_sep"]).replace("TEMP", locale["thousands_sep"])
        return f"{locale['currency_prefix']}{formatted}"
    except (TypeError, ValueError, InvalidOperation):
        return str(val)


def _fmt_date(val, preferences: dict = None) -> str:
    locale = _get_locale_config(preferences)
    custom_format = (preferences or {}).get("date_format")

    def _clean(dt: datetime) -> str:
        if custom_format:
            try:
                return dt.strftime(custom_format)
            except ValueError:
                pass
        day = dt.strftime("%d").lstrip("0")
        if dt.hour or dt.minute:
            return dt.strftime(locale["date_format_with_time"].replace("{day}", day))
        return dt.strftime(locale["date_format"].replace("{day}", day))

    if isinstance(val, datetime):
        return _clean(val)
    if isinstance(val, date):
        day = val.strftime("%d").lstrip("0")
        if custom_format:
            try:
                return val.strftime(custom_format)
            except ValueError:
                pass
        return val.strftime(locale["date_format"].replace("{day}", day))
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d", "%Y-%m"):
            try:
                dt = datetime.strptime(val.strip(), fmt)
                if fmt == "%Y-%m":
                    return dt.strftime("%b %Y")
                return _clean(dt)
            except ValueError:
                continue
    return str(val)


def _fmt_days(val) -> str:
    try:
        n = int(float(val))
        return f"{n:,} days"
    except (TypeError, ValueError):
        return str(val)


def _fmt_count(val) -> str:
    try:
        n = int(float(val))
        return f"{n:,}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_percentage(val, col_name: str = "", sample_vals: list = None) -> str:
    try:
        f = float(val)
        if sample_vals:
            non_null = [float(v) for v in sample_vals if v is not None]
            if non_null and all(0 <= v <= 1.0 for v in non_null[:5]):
                f = f * 100
        elif 0 < f < 1.0 and not str(val).endswith("%"):
            f = f * 100
        return f"{f:.2f}%"
    except (TypeError, ValueError):
        return str(val)


def _first_non_null(sample_vals: list):
    return next((v for v in sample_vals if v is not None), None)


def _name_says_currency(tokens: set, col_name: str) -> bool:
    hits = tokens & _CURRENCY_KEYWORDS
    if not hits:
        return False
    if hits <= _AMBIG_CURRENCY:
        return False
    return True


def _name_says_date(tokens: set, col_name: str) -> bool:
    if tokens & _DATE_KEYWORDS:
        return True
    return bool(_DATE_SUFFIX_RE.search(col_name))


def _detect_col_type(col_name: str, sample_vals: list) -> str:
    tokens = _tokenize(col_name)
    first_val = _first_non_null(sample_vals)

    if first_val is not None:
        if isinstance(first_val, (date, datetime)):
            return "date"
        if isinstance(first_val, bool):
            return "raw"
        if isinstance(first_val, int):
            if tokens & _DAYS_KEYWORDS:
                return "days"
            return "count"
        if isinstance(first_val, str):
            if _name_says_date(tokens, col_name):
                return "date"
            return "raw"

    numeric = isinstance(first_val, (Decimal, float))
    if isinstance(first_val, Decimal):
        _, _, exponent = first_val.as_tuple()
        if isinstance(exponent, int) and exponent < 0:
            if tokens & _DAYS_KEYWORDS:
                return "days"
            return "currency"

    if tokens & _PERCENTAGE_KEYWORDS:
        return "percentage"
    if _name_says_currency(tokens, col_name):
        return "currency"
    if _name_says_date(tokens, col_name):
        return "date"
    if tokens & _DAYS_KEYWORDS:
        return "days"
    if numeric and tokens & _AMBIG_CURRENCY:
        return "currency"
    if tokens & _COUNT_KEYWORDS:
        return "count"

    return "raw"


def _compute_conditional_format(col_name: str, col_type: str, val, formatted_val) -> dict:
    style = {}
    if val is None:
        return style
    tokens = _tokenize(col_name)
    if col_type == "currency":
        try:
            num = float(val) if not isinstance(val, (int, float)) else val
            if num < 0:
                style["color"] = "#E74C3C"
        except (TypeError, ValueError):
            pass
    if "urgency" in col_name.lower():
        val_str = str(val).lower()
        if val_str == "overdue":
            style["color"] = "#E74C3C"
            style["font-weight"] = "bold"
        elif val_str == "urgent":
            style["color"] = "#E67E22"
            style["font-weight"] = "bold"
        elif val_str == "warning":
            style["color"] = "#F39C12"
        elif val_str == "normal":
            style["color"] = "#27AE60"
    if "paid_in_full" in col_name.lower():
        if val is True:
            style["color"] = "#27AE60"
            style["font-weight"] = "bold"
        elif val is False:
            style["color"] = "#E74C3C"
    if col_name.endswith("_pct_change") and isinstance(formatted_val, str):
        if formatted_val.startswith("+"):
            style["color"] = "#27AE60"
        elif formatted_val.startswith("-"):
            style["color"] = "#E74C3C"
    return style


def _format_rows(rows: list, preferences: dict = None) -> tuple[list, dict, dict]:
    if not rows:
        return rows, {}, {}

    cols = list(rows[0].keys())
    col_types = {}
    for col in cols:
        sample = [r[col] for r in rows[:10] if r.get(col) is not None]
        col_types[col] = _detect_col_type(col, sample)

    cell_styles = {}
    formatted = []
    for row_idx, row in enumerate(rows):
        new_row = {}
        for col in cols:
            val = row.get(col)
            if val is None:
                new_row[col] = None
                continue
            ctype = col_types[col]
            if ctype == "percentage":
                sample = [r[col] for r in rows[:10] if r.get(col) is not None]
                new_row[col] = _fmt_percentage(val, col, sample)
            elif ctype == "currency":
                new_row[col] = _fmt_currency(val, preferences)
            elif ctype == "date":
                new_row[col] = _fmt_date(val, preferences)
            elif ctype == "days":
                new_row[col] = _fmt_days(val)
            elif ctype == "count":
                new_row[col] = _fmt_count(val)
            else:
                new_row[col] = val
            cond_style = _compute_conditional_format(col, ctype, val, new_row[col])
            if cond_style:
                cell_styles[f"{row_idx}:{col}"] = cond_style
        formatted.append(new_row)

    return formatted, col_types, cell_styles


def output_formatter_node(state: GraphState) -> GraphState:
    rows = state.get("query_result")
    if not rows:
        return state

    preferences = state.get("user_preferences") or {}
    formatted, col_types_summary, cell_styles = _format_rows(rows, preferences)

    applied = [f"{col}->{t}" for col, t in col_types_summary.items() if t != "raw"]

    detail = applied if applied else []
    if cell_styles:
        detail.append(f"Conditional formatting: {len(cell_styles)} styled cell(s)")
    locale = preferences.get("locale", "US")
    if locale != "US":
        detail.append(f"Locale: {locale}")

    trace_entry = {
        "agent": "Output Formatter",
        "status": "ok",
        "summary": (
            f"Formatted {len(applied)} column(s)" if applied
            else "No formatting needed — all columns are plain values"
        ) + (f" · {len(cell_styles)} conditional style(s)" if cell_styles else ""),
        "detail": detail,
    }

    return {
        **state,
        "query_result": formatted,
        "cell_styles": cell_styles,
        "agent_trace": state.get("agent_trace", []) + [trace_entry],
    }
