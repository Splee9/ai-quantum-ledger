# Ingestion contract — daily headline → ledger

How new announcements enter the ledger. The ledger is an **all-time, append-only tracker** where
**one row = one announcement**. A daily job scans AI/quantum funding headlines, extracts structured
candidate records, and stages them for review; a human (or a gated step) promotes vetted rows into
the canonical ledger. This doc is the contract between the *scanner* (which you build) and the
*write-path* (`ingest.py`, already built).

## Pipeline

```
 headlines / articles
        │   ① scan + extract   (scan.py — Google News RSS + Claude extraction)
        ▼
 candidates.jsonl  (records following data/schema.json)
        │   ② python3 ingest.py add candidates.jsonl   (scan.py run --add does ①+②)
        ▼
 data/ingest-queue.jsonl   (staging — nothing is live yet)
        │   ③ human review  (read the queue, check sources)
        │      python3 ingest.py list
        ▼
 data/government-commitments.jsonl   (the canonical ledger)
        │   ④ python3 ingest.py promote [id ...]
        ▼
 ⑤ python3 build.py   &&   git commit      (regenerate both pages, commit the diff)
```

The split matters: **the scanner proposes, review disposes.** `ingest.py` is deliberately dumb —
it validates, deduplicates, and appends, nothing more — so every accepted row is one `git diff`
away from a human's eyes. The scanner is where the cleverness (and the risk) lives; keep it on the
*other* side of the queue.

## The write-path (`ingest.py`)

```bash
python3 ingest.py validate candidates.jsonl     # dry-run: validate only, no write
python3 ingest.py add      candidates.jsonl     # validate + dedup -> append to the REVIEW QUEUE
python3 ingest.py add      candidates.jsonl --to-ledger   # straight to the ledger (vetted rows only)
python3 ingest.py list                          # show the review queue
python3 ingest.py promote                        # move ALL queue rows into the ledger
python3 ingest.py promote us-foo-2026 eu-bar-2026  # move specific rows by id
```

Input may be **JSONL** (one record per line) or a **JSON array**. The default `add` lands rows in
the queue, never the live ledger — use `--to-ledger` only for rows you have already vetted by hand.

## What a candidate record must contain

One record per announcement, following [`data/schema.json`](data/schema.json). Required fields
(ingestion rejects a record missing any of these):

| Field | Rule for the scanner |
|---|---|
| `id` | Stable unique slug, `country-program-year`, e.g. `jp-ai-strategy-2025`. Must be globally unique — a collision is a hard reject. |
| `jurisdiction` / `iso3` | Country/bloc name + ISO-3166 alpha-3 (or `EU`). Add a `data/denominators.json` row for any new `iso3` (a missing one is a *warning*, not a block). |
| `program` | Initiative / fund / package name. |
| `domain` | One of `ai · quantum · ai+quantum · semiconductor · compute`. |
| `currency` + `usd_approx` | Original ISO-4217 code and the USD conversion (a number). |
| `announced` | `YYYY-MM-DD` (preferred) or `YYYY-MM`. Drives the all-time ordering and the 7/30-day recency panel. |
| `actor_type` | `government_appropriated · government_outlay · state_fund · sovereign_wealth · mobilization_target · public_private · private`. Decides whether the money counts toward the public-outlay aggregate. |
| `verification_status` | **Auto-extracted rows: use `reported` (credible press) or `unconfirmed`. Never `verified`** — `verified` means a human traced a primary budget/official doc. |
| `confidence` | `high · medium · low`. Default `low`/`medium` for auto-extracted rows. |
| `source_name` | Publisher / issuing body. |
| `event_key` | Stable key grouping re-announcements of the **same** money (e.g. a pledge repeated at a later summit). This is the dedup axis — see below. |

Strongly encouraged (the ledger's whole value is the tagging — fill these when the source supports it):
`source_url` (the primary link), `headline_amount`, `fx_rate_to_usd`, `horizon_start_year` /
`horizon_end_year`, `public_outlay_usd` / `private_mobilized_usd` (kept **separate**, never summed),
`tradable_share`, and `notes` (caveats, overlaps, provenance of the extraction).

## Dedup rules

- **`id` collision → hard reject.** Same announcement, already ingested. The scanner should compute
  deterministic ids so re-runs are idempotent.
- **`event_key` collision → accepted with a warning.** A genuinely *new* announcement that re-commits
  the *same* money (a later summit, a re-up) is a valid new row, but it shares the prior `event_key`
  so the conservative outlay aggregate (and the jurisdiction group-by total) **dedup by `event_key`
  and never double-count it.** Use this instead of dropping re-announcements — the timeline should
  show them; the totals should not.

## The cardinal rule still governs

The scanner must **never** invent a row that sums headlines, and must keep public vs. private money in
separate fields. Big "mobilization" headlines (private capital, multi-year targets) are tagged
`mobilization_target` / `private` with the public portion (if any) in `public_outlay_usd` and the rest
in `private_mobilized_usd`. When unsure, prefer `unconfirmed` + `low` and let review decide — an honest
gap beats announcement inflation.

## The scanner (`scan.py`)

The discovery + extraction stages are built in `scan.py`. **Unlike `build.py` / `ingest.py` it is not
stdlib-only or offline** — it needs the network (discovery) and the Anthropic API (extraction), and it
writes only candidate files + the review queue, never the canonical ledger.

```bash
# Stage 1 only — Google News RSS, NO API key needed:
python3 scan.py discover --days 2 --out headlines.jsonl

# Stage 2 only — Claude extraction (needs ANTHROPIC_API_KEY):
python3 scan.py extract --headlines headlines.jsonl --out candidates.jsonl

# Both, and stage into the review queue in one shot:
python3 scan.py run --days 2 --add
#   -> discover -> extract -> ingest.py add  (lands in data/ingest-queue.jsonl)
```

- **Discovery** queries Google News RSS across a set of AI/quantum government-investment search terms
  (stdlib `urllib` + `xml`; verifies TLS via `certifi` when present). Tune the `QUERIES` list or add
  another source by editing `discover()`.
- **Extraction** calls Claude (default `claude-opus-4-8`; `--model claude-sonnet-4-6` for a cheaper
  daily run) with **structured outputs** so it returns schema-valid candidate records, and a system
  prompt that bakes in the rules above (reported/unconfirmed only, separate public/private, no headline
  summing, stable `id`/`event_key`). Install the SDK with `pip install anthropic`.

**Scheduling.** Wrap `python3 scan.py run --add` in a daily cron / GitHub Action / Cowork task. It is
idempotent on `id`, so re-runs don't create duplicates. A reviewer then works the queue
(`ingest.py list` → `promote`) and runs `build.py` + commit on whatever cadence they trust — the
human-review gate is deliberate and stays.
