"""
GitHub Code Reader — read-only access to the IDRE codebase via GitHub API.
Uses the PAT from .env to fetch file contents, search code, and get recent commits.
All operations are strictly read-only.
"""
import json
import base64
import logging
from functools import lru_cache
from typing import Optional
import requests
from config.settings import get_settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
CACHE_MAX = 200
_file_cache: dict[str, str] = {}


def _headers() -> dict:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_path() -> str:
    settings = get_settings()
    return f"{settings.github_repo_owner}/{settings.github_repo_name}"


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.github_token and settings.github_repo_owner and settings.github_repo_name)


def get_file_content(path: str, ref: str = "main") -> Optional[str]:
    """Fetch a single file's content from the repo. Returns None on error."""
    cache_key = f"{path}@{ref}"
    if cache_key in _file_cache:
        return _file_cache[cache_key]

    if not is_configured():
        return None

    try:
        url = f"{API_BASE}/repos/{_repo_path()}/contents/{path}"
        resp = requests.get(url, headers=_headers(), params={"ref": ref}, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"GitHub API {resp.status_code} for {path}")
            return None

        data = resp.json()
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            content = data.get("content", "")

        if len(_file_cache) < CACHE_MAX:
            _file_cache[cache_key] = content
        return content
    except Exception as e:
        logger.error(f"GitHub read error for {path}: {e}")
        return None


def search_code(query: str, max_results: int = 10) -> list[dict]:
    """Search for code in the IDRE repo. Returns list of {path, matches}."""
    if not is_configured():
        return []

    try:
        url = f"{API_BASE}/search/code"
        params = {
            "q": f"{query} repo:{_repo_path()}",
            "per_page": min(max_results, 30),
        }
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"GitHub search API {resp.status_code}")
            return []

        results = []
        for item in resp.json().get("items", []):
            results.append({
                "path": item.get("path", ""),
                "name": item.get("name", ""),
                "url": item.get("html_url", ""),
            })
        return results
    except Exception as e:
        logger.error(f"GitHub search error: {e}")
        return []


def get_directory_listing(path: str = "", ref: str = "main") -> list[dict]:
    """List files in a directory. Returns list of {name, path, type}."""
    if not is_configured():
        return []

    try:
        url = f"{API_BASE}/repos/{_repo_path()}/contents/{path}"
        resp = requests.get(url, headers=_headers(), params={"ref": ref}, timeout=15)
        if resp.status_code != 200:
            return []

        return [
            {"name": item["name"], "path": item["path"], "type": item["type"]}
            for item in resp.json()
            if isinstance(item, dict)
        ]
    except Exception as e:
        logger.error(f"GitHub directory listing error: {e}")
        return []


def get_recent_commits(path: Optional[str] = None, max_count: int = 10) -> list[dict]:
    """Get recent commits, optionally filtered to a specific file/directory."""
    if not is_configured():
        return []

    try:
        url = f"{API_BASE}/repos/{_repo_path()}/commits"
        params = {"per_page": max_count}
        if path:
            params["path"] = path
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code != 200:
            return []

        return [
            {
                "sha": c["sha"][:8],
                "message": c["commit"]["message"].split("\n")[0][:100],
                "date": c["commit"]["committer"]["date"][:10],
                "author": c["commit"]["author"]["name"],
            }
            for c in resp.json()
        ]
    except Exception as e:
        logger.error(f"GitHub commits error: {e}")
        return []


def get_report_source_code(report_name: str) -> Optional[str]:
    """
    Fetch the API route source code for a specific IDRE report.
    Tries common paths based on IDRE's report structure.
    """
    possible_paths = [
        f"app/api/reports/{report_name}/route.ts",
        f"lib/reports/{report_name}.ts",
        f"components/reports/{report_name}.tsx",
    ]
    for path in possible_paths:
        content = get_file_content(path)
        if content:
            return content
    return None
