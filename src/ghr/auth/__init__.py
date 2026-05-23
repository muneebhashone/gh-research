"""Layered auth/token resolution and persistence for ``ghr``.

The raw token is never logged, printed, or stored in the cache; :func:`mask`
in :mod:`ghr.auth.resolver` is the only sanctioned display path.
"""

from __future__ import annotations
