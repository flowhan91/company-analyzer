# company-analyzer

JD-aware company intelligence. This phase builds the company side only:
turn a pilot company's real documents into an evidence-backed **Timeline**
of canonical events and **Threads** connecting related events over time,
with a human review workflow and a web explorer. JD matching is a later
phase (see `.claude/plans/cached-crunching-avalanche.md` for the full plan).

## How it works

```
Documents (DART live / manual drop-in / Naver News live)
  -> source-aware chunking
  -> LLM event + evidence extraction (pluggable provider, mock by default)
  -> evidence validation (exact/fuzzy match back to source, offset recovery)
  -> hybrid duplicate detection (rule-based pre-filter + LLM classification)
  -> canonical events -> Company Timeline
  -> hybrid threading (same mechanism, wider time window)
  -> Web Explorer: timeline, threads, evidence inspection, review queue
```

Every extracted event keeps a validated link back to the exact source text
it came from. Uncertain LLM decisions (low-confidence evidence matches,
ambiguous duplicate/thread calls) are queued for human review instead of
silently applied.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # or .venv\Scripts\activate on cmd.exe
pip install -e ".[dev]"
cp .env.example .env
```

The database is **Supabase Postgres**. Add `SUPABASE_DB_URL` to `.env`:
Supabase dashboard -> your project -> **Connect** -> **"Direct connection"**
tab -> copy the URI, fill in your DB password, use port `5432` (not a
pooler endpoint). This is different from the API URL / anon / service_role
keys shown on the other tabs of that dialog - those are for Supabase's
REST/Auth client SDK, not usable for a direct SQL connection.

```bash
cana init-db   # creates the schema in your Supabase project if it doesn't exist yet
```

`LLM_PROVIDER=mock` (the default) needs no API key and is enough to run the
whole pipeline mechanically - useful for development and tests. To ingest
real documents you'll need:

- `OPENDART_API_KEY` - free registration at https://opendart.fss.or.kr, for `ingest-dart`.
- `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` - free registration at https://developers.naver.com, for `ingest-news`.

Real extraction quality also needs a real LLM provider (`LLM_PROVIDER=anthropic`
or `openai` plus the matching API key) - the `AnthropicProvider`/`OpenAIProvider`
classes in `src/company_analyzer/llm/` have the interface wired but the
request bodies still need implementing once a vendor is chosen.

## Running the pipeline

```bash
cana init-db

# 1. Ingest + process official sources first
cana ingest-manual --company NAVER --path fixtures/naver   # or your own data/raw/naver
cana ingest-dart --company NAVER --days 365                # needs OPENDART_API_KEY
cana run-all --company NAVER   # chunk -> extract -> validate-evidence -> cluster-events -> build-threads

# 2. Only now does news ingestion have something to search for: it queries
#    "<company> <entity>" per distinct entity already found in canonical_events -
#    not a blind company-name search, and it errors clearly if you run it too early.
cana ingest-news --company NAVER   # needs NAVER_CLIENT_ID/SECRET
cana run-all --company NAVER       # re-run: picks up only the new news documents

# Inspect
cana show-timeline --company NAVER
cana show-threads --company NAVER

# Human review queue
cana review summary --company NAVER
cana review list-evidence --company NAVER
cana review list-duplicates
cana review list-threads
cana review approve-duplicate <relationship_id> --as your-name
```

## Web explorer

```bash
cana serve
```

Then open http://127.0.0.1:8000 for the timeline, thread, and review-queue
views (approve/reject buttons update in place via HTMX).

## Manual document drop-in

For IR decks, press releases, tech blog posts, and CEO letters (no live
scraper for these - curate them yourself), drop a markdown file with
front-matter into `data/raw/<company lowercased>/<source_type>/<slug>.md`:

```markdown
---
title: Q2 2025 Business Report Excerpt
source_type: ir
url: https://example.com/ir/q2-2025
published_date: 2025-08-01
---
Document body text goes here...
```

`source_type` must be one of `dart`, `ir`, `press_release`, `tech_blog`,
`ceo_letter`, `news`. See `fixtures/naver/` for worked examples.

## Tests

```bash
pytest
```

Tests run against your real Supabase project (needs `SUPABASE_DB_URL` in
`.env` and network access) but never touch real data: each test creates its
own throwaway Postgres schema and drops it on teardown. LLM calls stay free
via the mock provider - the full pipeline test (`tests/test_pipeline_e2e.py`)
proves mechanics end-to-end with zero LLM API keys, using the fixture
documents in `fixtures/naver/`.
