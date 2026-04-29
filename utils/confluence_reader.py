"""
Confluence Reader — read-only access to IDRE documentation via Confluence REST API.
Fetches pages from configured spaces (SD, IDRE, ADS) and caches them locally.
STRICTLY READ-ONLY: no writes, no modifications, no comments.
"""
import json
import os
import re
import logging
from functools import lru_cache
from typing import Optional
import requests
from config.settings import get_settings

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "confluence_cache")
CACHE_INDEX_PATH = os.path.join(CACHE_DIR, "_index.json")
MAX_PAGES_PER_SPACE = 50


def _auth() -> tuple[str, str]:
    settings = get_settings()
    return (settings.confluence_username, settings.confluence_api_token)


def _base_url() -> str:
    settings = get_settings()
    url = settings.confluence_url.rstrip("/")
    return url


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.confluence_url and settings.confluence_username and settings.confluence_api_token)


def _strip_html(html_content: str) -> str:
    """Strip HTML tags and decode entities for plain text."""
    text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_cache_index() -> dict:
    if os.path.exists(CACHE_INDEX_PATH):
        with open(CACHE_INDEX_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"pages": {}}


def _save_cache_index(index: dict):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def _cache_page(page_id: str, title: str, space: str, content: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe_name = re.sub(r"[^\w\-]", "_", title)[:80]
    filename = f"{page_id}_{safe_name}.txt"
    filepath = os.path.join(CACHE_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    index = _load_cache_index()
    index["pages"][page_id] = {
        "title": title,
        "space": space,
        "filename": filename,
    }
    _save_cache_index(index)


def _get_cached_page(page_id: str) -> Optional[str]:
    index = _load_cache_index()
    entry = index.get("pages", {}).get(page_id)
    if not entry:
        return None
    filepath = os.path.join(CACHE_DIR, entry["filename"])
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    return None


def fetch_space_pages(space_key: str, max_pages: int = MAX_PAGES_PER_SPACE) -> list[dict]:
    """Fetch page listing from a Confluence space. Returns [{id, title, space}]."""
    if not is_configured():
        return []

    try:
        url = f"{_base_url()}/rest/api/content"
        params = {
            "spaceKey": space_key,
            "type": "page",
            "limit": max_pages,
            "expand": "metadata.labels",
        }
        resp = requests.get(url, auth=_auth(), params=params, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"Confluence API {resp.status_code} for space {space_key}")
            return []

        pages = []
        for item in resp.json().get("results", []):
            pages.append({
                "id": item["id"],
                "title": item["title"],
                "space": space_key,
            })
        return pages
    except Exception as e:
        logger.error(f"Confluence space listing error: {e}")
        return []


def fetch_page_content(page_id: str) -> Optional[str]:
    """Fetch a single page's content as plain text. Caches locally."""
    cached = _get_cached_page(page_id)
    if cached:
        return cached

    if not is_configured():
        return None

    try:
        url = f"{_base_url()}/rest/api/content/{page_id}"
        params = {"expand": "body.storage,space"}
        resp = requests.get(url, auth=_auth(), params=params, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"Confluence page fetch {resp.status_code} for {page_id}")
            return None

        data = resp.json()
        title = data.get("title", "")
        space = data.get("space", {}).get("key", "")
        html_body = data.get("body", {}).get("storage", {}).get("value", "")
        text = _strip_html(html_body)

        full_content = f"Title: {title}\nSpace: {space}\n\n{text}"
        _cache_page(page_id, title, space, full_content)
        return full_content
    except Exception as e:
        logger.error(f"Confluence page content error: {e}")
        return None


def search_confluence(query: str, max_results: int = 10) -> list[dict]:
    """Search across all configured Confluence spaces. Returns [{id, title, space, excerpt}]."""
    if not is_configured():
        return []

    settings = get_settings()
    spaces = settings.confluence_spaces
    space_clause = " OR ".join(f'space="{s}"' for s in spaces)
    cql = f'({space_clause}) AND text ~ "{query}"'

    try:
        url = f"{_base_url()}/rest/api/content/search"
        params = {"cql": cql, "limit": max_results, "expand": "space"}
        resp = requests.get(url, auth=_auth(), params=params, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"Confluence search API {resp.status_code}")
            return []

        results = []
        for item in resp.json().get("results", []):
            results.append({
                "id": item["id"],
                "title": item["title"],
                "space": item.get("space", {}).get("key", ""),
                "excerpt": item.get("excerpt", "")[:200],
            })
        return results
    except Exception as e:
        logger.error(f"Confluence search error: {e}")
        return []


def get_all_cached_pages() -> list[dict]:
    """Return all locally cached page entries (no API call)."""
    index = _load_cache_index()
    return [
        {"id": pid, **info}
        for pid, info in index.get("pages", {}).items()
    ]


def build_confluence_context(query: str, max_pages: int = 3) -> str:
    """
    Search Confluence for pages relevant to the query and return
    a compact text context suitable for injection into LLM prompts.
    """
    results = search_confluence(query, max_results=max_pages)
    if not results:
        return ""

    context_parts = ["=== Relevant Confluence Documentation ==="]
    for r in results:
        content = fetch_page_content(r["id"])
        if content:
            # Truncate to keep context manageable
            truncated = content[:2000]
            context_parts.append(f"\n--- {r['title']} ({r['space']}) ---\n{truncated}")

    return "\n".join(context_parts) if len(context_parts) > 1 else ""
