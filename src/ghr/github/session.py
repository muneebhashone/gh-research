"""The shared ``httpx.Client`` used by both the REST and GraphQL clients."""

from __future__ import annotations

import httpx

from ghr.constants import API_BASE, API_VERSION, USER_AGENT


def build_session(token: str | None, *, base_url: str = API_BASE) -> httpx.Client:
    """Create one pooled client with GitHub's required headers and sane timeouts.

    The ``Authorization`` header is set only when a token is available; the rest
    of the tool degrades to unauthenticated REST access when it is not.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    return httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
