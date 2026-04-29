"""
Feedback Analytics

Read-only analytics over feedback_log.jsonl for the developer panel.
All functions are safe to call even when the file doesn't exist yet.
"""
from collections import Counter
from utils.feedback_store import load_feedback


def get_feedback_summary() -> dict:
    """
    Returns aggregate stats for the developer panel.
    {
        total, correct, incorrect, accuracy_pct,
        by_user: [(handle, total, incorrect), ...],
        top_error_categories: [(category, count), ...]
    }
    """
    records = load_feedback(limit=5000)
    if not records:
        return {
            "total": 0, "correct": 0, "incorrect": 0, "accuracy_pct": 0,
            "by_user": [], "top_error_categories": [],
        }

    total = len(records)
    correct = sum(1 for r in records if r.get("is_correct", True))
    incorrect = total - correct
    accuracy_pct = round(correct / total * 100, 1) if total else 0

    # Per-user breakdown
    user_totals: dict[str, list] = {}
    for r in records:
        handle = r.get("user_identity") or "anonymous"
        if handle not in user_totals:
            user_totals[handle] = [0, 0]   # [total, incorrect]
        user_totals[handle][0] += 1
        if not r.get("is_correct", True):
            user_totals[handle][1] += 1

    by_user = sorted(
        [(h, v[0], v[1]) for h, v in user_totals.items()],
        key=lambda x: x[1],
        reverse=True,
    )

    # Top error categories
    all_cats = []
    for r in records:
        all_cats.extend(r.get("error_categories", []))
    top_error_categories = Counter(all_cats).most_common(5)

    return {
        "total": total,
        "correct": correct,
        "incorrect": incorrect,
        "accuracy_pct": accuracy_pct,
        "by_user": by_user,
        "top_error_categories": top_error_categories,
    }


def get_incorrect_by_user(user_handle: str) -> list[dict]:
    """Return all incorrect feedback records for a specific user."""
    from utils.feedback_store import load_feedback_by_user
    return [r for r in load_feedback_by_user(user_handle) if not r.get("is_correct", True)]
