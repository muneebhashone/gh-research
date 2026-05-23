---
name: gh-research
description: >
  Research GitHub Issues & Discussions (and repo discovery) and answer questions
  about real projects: what's trending, common problems in a project or ecosystem,
  the hottest/most-contentious discussions, whether a project is booming or dying,
  and deep-dives into a single repo. Use when the user asks to "dig into project X",
  "what are people complaining about in <type> projects", "what's trending", "hot
  discussions in X", "is X still active". Backed by the `ghr` CLI: a deterministic
  data + analysis engine that returns compact JSON — YOU write the narrative.
---

# gh-research (`ghr`)

`ghr` is a CLI that fetches, ranks, and **aggregates** GitHub Issues, Discussions,
and repo metadata into compact JSON. It does **no** LLM reasoning of its own — it
hands you deterministic aggregates (engagement ranking, label frequency, activity
trends) and **you** synthesize the answer.

- **Use it for:** issues, discussions, repo health/discovery, "what's hot / common /
  booming / broken", single-repo deep dives, cross-repo ecosystem scans.
- **Not for:** reading source code, PRs-as-code-review, commits, or CI. (Issues &
  Discussions + repo discovery only.)

## Invocation rules (read first)

1. **Global flags go BEFORE the subcommand.** `ghr --json --jq '.data' repo view cli/cli` ✅,
   not `ghr repo view cli/cli --jq ...` ❌ (that errors).
2. **Output is JSON when piped/non-TTY** (i.e., whenever you run it). Every command
   returns one object: `{ "ok": bool, "data": ..., "error": {code,message,suggestion}|null, "meta": {...} }`.
3. **Always check `error` and the exit code** before trusting `data`.
4. Run as `uv run ghr …` from the project, or `ghr …` once installed (clone the repo, then `uv tool install .`).

## Exit codes

| code | meaning | what to do |
|------|---------|-----------|
| 0 | success | use `data` |
| 2 | usage error | fix flags/arguments |
| 3 | not found | check owner/repo or number |
| 4 | auth required | a Discussions command without a token — set `GH_TOKEN` or `gh auth login` |
| 5 | rate limited | back off until `meta.rate_limit.reset`; or authenticate for higher limits |
| 6 | upstream error | GitHub 5xx / GraphQL error — retry later |
| 7 | partial / capped | `data` is usable but incomplete (see `meta.truncated`); tell the user |

## Auth & rate limits

- REST (issues, repos, search) works **unauthenticated** but at 60 req/hr and 10
  searches/min. **Discussions require a token** (GitHub GraphQL is auth-only) — without
  one, `discussions *` and `research hot-discussions` exit **4**.
- `ghr auth status` shows whether a token is available and its source. `ghr rate` shows
  per-bucket budgets. Read `meta.rate_limit.remaining` and don't fan out blindly.
- The Search API hard-caps at **1000 results**; when hit, `meta.truncated.reason ==
  "search_cap"` and `meta.truncated.total_count` tells you how many matched. Narrow the
  query (dates, labels) rather than expecting everything.
- Responses are cached locally (TTL'd); re-running a query is cheap. Add `--refresh` to
  force-refresh, `--no-cache` to bypass.

## Two-tier model — start high, then drill

**Tier 1 (`research *`)** = one opinionated call that returns a useful bundle. **Start here.**
**Tier 2** (`issues`/`discussions`/`repo`) = granular primitives to steer once you know what to look at.

| The user wants… | Run |
|---|---|
| "Summarize / dig into repo X" | `ghr research digest X` |
| "What's trending / hot new repos" | `ghr research trending --language L --topic T` |
| "What's broken / pain in X" | `ghr research pain-points X` |
| "Hottest discussions in X" | `ghr research hot-discussions X` |
| "Booming or dying?" | `ghr research activity X` |
| "Common issues across <type> projects" | `ghr research common-issues --topic T --language L` |
| A specific author/label/date slice | `ghr issues search …` / `ghr discussions search …` |
| One item's full detail + comments | `ghr issues view X N --comments 20` / `ghr discussions view X N` |

## Reading the output

- Read `meta.headline_metrics` / `result_count` and top-K arrays **first**; they're compact.
- Scores are reproducible; `meta.scoring` gives the weights if you must explain "why hot".
- Item bodies are **omitted** from lists/searches and **trimmed to 500 chars** in views.
  Pass `--full` (global) for an item you must quote verbatim, or `--with-body` on list/search.
- `--quiet-meta` (global) drops `meta` to save tokens on follow-up calls.

## Command reference

```
research digest <owner/repo>            health + top issues + hot discussions + labels + activity
research trending [--language --topic --days --min-stars --limit]
research pain-points <owner/repo> [--labels --top]      top-reacted open (bug) issues
research hot-discussions <owner/repo> [--window --top]  (needs token)
research activity <owner/repo> [--bucket day|week|month --windows]
research common-issues --topic T --language L [--repos --issues-per-repo]

repo search [--language --topic --min-stars --created --pushed --sort]
repo view <owner/repo>            repo topics <owner/repo>

issues search [--repo --org --author --label --language --state --in --created --updated
               --min-comments --min-reactions --sort --order --with-body --limit]
issues list <owner/repo> [--state --labels --sort --since]
issues view <owner/repo> <number> [--comments N]
issues analyze <owner/repo> [--what hot,labels --window --top]

discussions search <query>        discussions list <owner/repo> [--order]
discussions view <owner/repo> <number> [--comments]   discussions categories <owner/repo>
discussions analyze <owner/repo> [--window --top]      (all need a token)

auth status | login | logout       cache stats | clear | path       rate
```

Global flags (before the subcommand): `--json/--no-json --jq <expr> --quiet-meta --full
--body-chars N --limit N --no-cache --refresh --token-source none|auto --max-requests N
--time-budget-ms N --config PATH`.

## Recipes (the common questions → exact commands)

1. **What repos are trending?** → `ghr research trending --language python --days 30 --limit 20`
   then read `data.repos[].stars_per_day`. (Approximation via Search API, not github.com/trending.)
2. **Figure out the issues in project X** → `ghr research digest X` (read `common_labels`,
   `top_issues`), then `ghr research pain-points X` for the open-defect ranking.
3. **Hottest discussions in X** → `ghr auth status` (ensure a token) → `ghr research
   hot-discussions X --top 10` → `ghr discussions view X <n> --comments 20` for the spiciest.
4. **Common issues in <type> projects** → `ghr research common-issues --topic <t> --language
   <l> --repos 10` → synthesize themes from `aggregate_labels` + per-repo `hottest_issue`.
5. **What's booming and what's broken?** → booming: `ghr research trending` and/or
   `ghr research activity X` (verdict). broken: `ghr research pain-points X` +
   `ghr research activity X` (verdict `dying`).
6. **Dig into project X** → `ghr research digest X` (one call), then drill with
   `pain-points` / `hot-discussions` / `issues view` on the items it surfaced.

## Gotchas

- "Trending" = a stars-per-day approximation via the Search API; say so when reporting.
- `common-issues` "themes" are **label** aggregates, not semantic clusters — cluster them yourself.
- Global flags must precede the subcommand.
- `research activity` counts **issues only** in v1 (not discussions).
