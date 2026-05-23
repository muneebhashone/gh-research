"""Pure, deterministic analysis primitives. No I/O, no network, no LLM.

Everything here is a pure function of already-fetched data so it is trivially
reproducible and unit-testable. This is the engine's differentiator over a raw
GitHub API wrapper.
"""
