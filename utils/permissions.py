"""
Permissions Utility  (Story 6.2 — Role-Based Access Control)

Loads access_control.json and resolves a user role → permitted_tables list.
Cached after first load.
"""
import json
import os
from typing import List

ACCESS_CONTROL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "access_control.json"
)

_acl_cache: dict = None


def _load_acl() -> dict:
    global _acl_cache
    if _acl_cache is None:
        with open(ACCESS_CONTROL_PATH) as f:
            _acl_cache = json.load(f)
    return _acl_cache


def get_permitted_tables(role: str) -> List[str]:
    """Return the list of tables the given role may query."""
    acl = _load_acl()
    roles = acl.get("roles", {})
    # Fall back to default_role if the requested role is unknown
    if role not in roles:
        role = acl.get("default_role", "VO")
    return roles[role]["permitted_tables"]


def get_role_display(role: str) -> str:
    acl = _load_acl()
    roles = acl.get("roles", {})
    if role not in roles:
        role = acl.get("default_role", "VO")
    return roles[role].get("display_name", role)


def get_all_roles() -> List[str]:
    acl = _load_acl()
    return list(acl.get("roles", {}).keys())
