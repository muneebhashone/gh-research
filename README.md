# gh-research (`ghr`)

A CLI that conducts research over **GitHub Issues, Discussions, and repository
metadata** and returns AI-optimized JSON. It is a *deterministic data + analysis
engine* — it fetches, ranks, and aggregates (engagement/"hot" scoring, label
frequency, activity trends, pain-points, cross-repo aggregation) and leaves the
natural-language synthesis to the calling agent. Built for AI agents like Claude
Code, not humans, though it works fine for either.

It answers questions such as: *what repos are trending, what issues are people
commonly facing in a project (or a whole ecosystem), what are the hottest
discussions, is this project booming or dying, dig into project X.*

## Why not just use `gh`?

`gh` is built for humans and exposes raw endpoints. `ghr` adds an agent-friendly
contract on top: a two-tier command surface, deterministic ranking/aggregation
primitives, a uniform JSON envelope with machine-readable errors and exit codes,
safe result caps, a local response cache, and a [`SKILL.md`](./SKILL.md) that
teaches an agent how to drive it.

## Install

```bash
uv tool install gh-research      # or: pipx install gh-research
ghr --help
```

From a clone (development):

```bash
uv sync
uv run ghr --help
```

## Authentication

- REST features (issues, repos, search) work **unauthenticated** at low rate limits.
- **Discussions require a token** (GitHub's GraphQL API is auth-only).
- Token resolution order: `--token` > `GH_TOKEN` > `GITHUB_TOKEN` > `gh auth token`
  (if the GitHub CLI is installed and logged in) > stored config/keyring.

```bash
ghr auth status          # shows whether a token is found, and its source (never the token)
ghr auth login --token <PAT>   # optional: store one (keyring if available, else config)
```

## Quickstart

```bash
ghr research digest cli/cli                       # one-call repo overview
ghr research trending --language python --days 30 # recently-popular repos (stars/day)
ghr research pain-points facebook/react           # top-reacted open bug issues
ghr research hot-discussions vercel/next.js        # client-ranked hottest discussions
ghr research activity cli/cli                       # booming vs dying
ghr research common-issues --topic cli --language go

ghr issues search --repo microsoft/vscode --label bug --sort reactions --limit 5
ghr discussions list vercel/next.js --limit 10
ghr rate                                            # rate-limit budgets
```

Global flags go **before** the subcommand, e.g. `ghr --jq '.data.repos[].full_name' research trending`.

## Output contract

Every command prints one JSON object:

```json
{ "ok": true, "data": { "...": "..." }, "error": null,
  "meta": { "command": "...", "result_count": 8, "truncated": false,
            "cache": {"hits": 0, "misses": 1},
            "rate_limit": {"resource": "search", "remaining": 27, "limit": 30, "reset": 0} } }
```

Exit codes: `0` ok · `2` usage · `3` not-found · `4` auth-required · `5` rate-limited ·
`6` upstream · `7` partial/capped. See [`SKILL.md`](./SKILL.md) for the full agent guide.

## Safe caps & configuration

Sensible defaults (result limit 30, max 100/page, search auto-stops at the 1000-result
API cap, per-command request/time budgets) are all overridable via flags, `GHR_*`
environment variables, or a `config.toml` — precedence: **flag > env > config > default**.

## Development

```bash
uv run pytest          # tests (HTTP mocked with respx; no network)
uv run ruff check      # lint
uv run ruff format     # format
uv run mypy src/ghr    # types (strict)
```
