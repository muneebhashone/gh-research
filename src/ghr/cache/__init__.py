"""SQLite TTL cache with ETag-revalidation support.

A non-secret, content-addressed cache: the key is a sha256 digest of the
normalized request identity, bucketed by a non-reversible auth-scope hash so
authenticated and anonymous responses never collide. The raw token is never
hashed into anything reversible, never stored, and never logged here.
"""
