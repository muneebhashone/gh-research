"""Tests for the shared httpx session builder."""

from ghr.github.session import build_session


def test_session_sets_common_headers_without_token() -> None:
    client = build_session(None)
    try:
        assert client.headers["user-agent"].startswith("ghr/")
        assert client.headers["x-github-api-version"]
        assert client.headers["accept"] == "application/vnd.github+json"
        assert "authorization" not in client.headers
    finally:
        client.close()


def test_session_sets_bearer_when_token_present() -> None:
    client = build_session("secret-token")
    try:
        assert client.headers["authorization"] == "Bearer secret-token"
    finally:
        client.close()
