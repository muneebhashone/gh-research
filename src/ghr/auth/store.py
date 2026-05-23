"""Token persistence: a plaintext TOML fallback and an optional OS keyring.

TOML is the discouraged-but-portable fallback (owner-only perms on POSIX);
the keyring backend is import-guarded so a missing/empty backend degrades to
"no token" rather than raising. The raw token is never logged here.
"""

from __future__ import annotations

import contextlib
import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import tomli_w

if TYPE_CHECKING:  # pragma: no cover - typing only
    from types import ModuleType

#: Service name for keyring entries (also the distribution name).
KEYRING_SERVICE = "gh-research"
#: Fixed account/username under which the token is stored in the keyring.
KEYRING_USERNAME = "token"


# --- TOML fallback ------------------------------------------------------


def _load_toml(config_path: Path) -> dict[str, Any]:
    """Parse an existing TOML file, or return an empty document if absent."""
    try:
        with config_path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}


def read_config_token(config_path: Path) -> str | None:
    """Return ``[auth].token`` from the TOML file, or ``None`` if absent."""
    data = _load_toml(config_path)
    auth = data.get("auth")
    if not isinstance(auth, dict):
        return None
    token = auth.get("token")
    return token if isinstance(token, str) else None


def write_config_token(config_path: Path, token: str) -> None:
    """Write/update ``[auth].token``, preserving any other existing tables.

    Creates the parent directory if needed and best-effort restricts the file
    to owner-only permissions on POSIX (ignored where unsupported).
    """
    data = _load_toml(config_path)
    auth = data.get("auth")
    if not isinstance(auth, dict):
        auth = {}
        data["auth"] = auth
    auth["token"] = token

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("wb") as fh:
        tomli_w.dump(data, fh)

    # best-effort owner-only perms; harmless/no-op on Windows
    with contextlib.suppress(OSError):
        os.chmod(config_path, 0o600)


def delete_config_token(config_path: Path) -> bool:
    """Remove ``[auth].token`` if present; return whether anything was removed."""
    data = _load_toml(config_path)
    auth = data.get("auth")
    if not isinstance(auth, dict) or "token" not in auth:
        return False
    del auth["token"]
    with config_path.open("wb") as fh:
        tomli_w.dump(data, fh)
    return True


# --- optional keyring backend (import-guarded) --------------------------


class _KeyringLike(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


def _import_keyring() -> ModuleType | _KeyringLike | None:
    """Return the ``keyring`` module, or ``None`` if it cannot be imported."""
    try:
        import keyring
    except Exception:
        return None
    return keyring


def keyring_get() -> str | None:
    """Read the stored token from the OS keyring, or ``None`` if unavailable."""
    backend = _import_keyring()
    if backend is None:
        return None
    try:
        return backend.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None


def keyring_set(token: str) -> bool:
    """Store ``token`` in the OS keyring; ``False`` if no backend / on error."""
    backend = _import_keyring()
    if backend is None:
        return False
    try:
        backend.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)
    except Exception:
        return False
    return True


def keyring_delete() -> bool:
    """Delete the stored token from the keyring; ``False`` if absent / on error."""
    backend = _import_keyring()
    if backend is None:
        return False
    try:
        backend.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return False
    return True
