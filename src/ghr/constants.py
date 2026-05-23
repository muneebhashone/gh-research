"""Static defaults: API endpoints, safe-cap defaults, and cache TTLs.

Safe caps and weights are overridable via flags/env/config (see :mod:`ghr.config`);
the values here are the built-in defaults at the bottom of that precedence chain.
"""

from __future__ import annotations

from ghr import __version__

# --- API endpoints / headers ---
API_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
API_VERSION = "2022-11-28"
USER_AGENT = f"ghr/{__version__}"

# --- safe-cap defaults ---
DEFAULT_LIMIT = 30
MAX_LIMIT = 100  # one REST/search page; also the API per_page ceiling
MAX_PAGES = 10  # 10 * 100 == the Search API 1000-result hard cap
GRAPHQL_NODE_BUDGET = 5000
MAX_REQUESTS = 50
TIME_BUDGET_MS = 20_000
BODY_CHAR_CAP = 500
SEARCH_RESULT_CAP = 1000  # GitHub Search API hard limit (not configurable upstream)

# cross-repo (research common-issues)
CROSS_REPO_REPOS = 8
CROSS_REPO_REPOS_MAX = 25
CROSS_REPO_ISSUES_PER_REPO = 30

# --- cache TTLs (seconds), per resource type ---
TTL_BY_RESOURCE: dict[str, int] = {
    "issue": 900,
    "issue_list": 300,
    "search": 300,
    "discussion": 900,
    "repo": 3600,
}
TTL_DEFAULT = 600


def ttl_for(resource: str) -> int:
    """TTL in seconds for a cache ``resource`` bucket, with a safe fallback."""
    return TTL_BY_RESOURCE.get(resource, TTL_DEFAULT)
