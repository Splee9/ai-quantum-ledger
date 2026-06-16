# AI/Quantum Investment Ledger

A public, source-linked, **all-time tracker of national (and government-adjacent) AI and quantum
investment announcements — one row per announcement** — with a transparent normalization layer
(per-capita / %GDP / %GBARD), an FX-vs-PPP currency split, jurisdiction group-by, and a reviewed daily
ingestion path. Think *Layoffs.fyi × Our World in Data × OECD/JRC composite-indicator rigor*, for
government technology spend.

**The ledger is the product. A composite ranking index is a deliberately *later* layer — and only ever
on top of the raw, downloadable data.**

## Why this exists

No public tracker is a continuously-updated, transaction-level *ledger* of national AI/quantum
investment commitments with a transparent normalization layer. Existing efforts are annual reports
(Stanford HAI, OECD, McKinsey), capability/readiness indices (Tortoise, IMF, Oxford Insights), or
paywalled deal databases (PitchBook, Preqin, CB Insights). The defensible niche is the combination:
a live factual ledger + rigorous sourcing discipline + a documented, auditable methodology.

The hard part is **comparability, not collection**: announced commitments vs. disbursed outlays,
multi-year vs. annual figures, currency/PPP conversion, and rampant public+private "mobilization"
double-counting. Every figure is tagged on these axes **before** any comparison.

## Quick start

```bash
python3 build.py          # regenerates index.html from data/ (no dependencies)
open index.html           # or serve the folder with any static host
```

`index.html` is fully self-contained (data baked inline, no external libraries) — drop the folder on
GitHub Pages, Netlify, or any static host and it works.

## Folder layout

```
ai-quantum-ledger/
├── README.md                         # this file
├── LICENSE                           # MIT (covers the code / build.py + ingest.py)
├── methodology.md                    # the public methodology (how figures are tagged & normalized)
├── INGESTION.md                      # contract for the daily headline -> ledger pipeline
├── build.py                          # generator: validates data + bakes both pages (stdlib only)
├── ingest.py                         # ingestion write-path: validate + dedup + append (stdlib only)
├── scan.py                           # daily scanner: RSS discovery + Claude extraction (needs network + API key)
├── index.html                        # the ledger viewer (generated; hostable entry point)
├── composite-index.html              # Stage 4: provisional composite ranking w/ 90% rank CIs (generated)
└── data/
    ├── LICENSE                       # CC BY 4.0 (covers everything in data/)
    ├── schema.json                   # the record field contract (+ normalization & realization blocks)
    ├── government-commitments.jsonl  # canonical ledger (append-only, one announcement per line)
    ├── ingest-queue.jsonl            # staging for auto-extracted rows pending human review
    ├── denominators.json             # GDP / population / price-level / GBARD by ISO3 (normalization)
    ├── realizations.jsonl            # Stage 3: dated realization observations per event_key (append-only)
    └── index-weights.json            # Stage 4: indicators, fixed weights, Monte-Carlo seed/draws
```

## The cardinal rule: headlines are not additive

The biggest integrity threat is **"announcement inflation"** — summing headline numbers that are mostly
private capital, multi-year targets, or the same money re-announced. So:

- **Headline figures are never summed into a global total.** The "sum of headlines" figure exists only
  to convey scale and is labeled non-additive.
- **The only defensible aggregate is `public_outlay_usd` over appropriated/outlay actors, deduplicated
  by `event_key`** — the "appropriated public outlays" figure.
- **`public_outlay_usd` and `private_mobilized_usd` are separate fields, never combined** into one
  "government investment" number (the EU InvestAI / France €109B "mobilization" trap).

See `data/schema.json` for the full field contract and `methodology.md` for the reasoning.

## Normalization & the FX-vs-PPP split

The viewer joins each record to `data/denominators.json` on `iso3` and offers live toggles:

- **Currency:** Market FX vs **PPP-blended** = `tradable_share × FX + (1 − tradable_share) × PPP`.
  Globally-priced compute/hardware stays at market FX; non-tradable talent/operations convert at PPP.
  PPP is a **sensitivity scenario, never the default**.
- **View:** Absolute · Per-capita · % of GDP (national effort) · × GBARD (fiscal prioritization) ·
  **Realization** (Stage 3).

A **Recent announcements** panel at the top of the ledger surfaces commitments announced in the last
**7** and **30 days**, computed client-side against the viewer's date (so it stays current on a static
host) — a *what's-new* feed that populates as fresh commitments are added.

## Three views, country profiles & the credibility spine

The viewer offers three **Views**:

- **List** — every announcement, newest-first (the raw ledger).
- **By country** — collapsible per-country groups (count, distinct domains, latest date, dedup'd
  public-outlay sum — never summed headlines).
- **Compare** — a cross-country **normalization dashboard** on a *public-outlay-only spine*
  (appropriated/outlay actors, deduplicated by `event_key`), shown across four normalizers at once —
  absolute · % of GDP · per-capita · × government R&D budget — with **mobilized / SWF capital in a
  separate, non-comparable column**. This is the report's recommended dashboard: never rank on a
  single basis, and never pool leveraged/sovereign-fund money with fiscal outlays.

**Click any country name** (anywhere it appears) to open its **profile card**: a modal with the
country's normalized snapshot, theme-by-theme summaries (AI / Quantum / Semiconductors / Compute) with
the dedup'd public outlay per theme, and every commitment **citing and linking its primary source** —
filterable by theme and actor.

Two new per-row tags back the *credibility-first* promise:

- **`source_tier`** — the trust spine: **T1** primary/audited gov (budget docs, Commerce-OIG/NIST
  status reports), **T2** supranational (OECD/EU/IMF/EC), **T3** specialist tracker/think tank
  (CSIS, ITIF, Bruegel, Stanford HAI), **T4** tier-one press only (no budgetary backing). Shown as a
  badge and filterable; treat T4-only figures (Gulf mandates, unconfirmed buildouts) as provisional.
- **`status`** — the money's lifecycle, distinct from verification of the figure: *announced ·
  authorized* (legislated ceiling, **not** appropriated — e.g. the US CHIPS Science Division) ·
  *obligated* (awarded/milestone-gated, not paid) · *disbursed* (cash out) · *stalled* · *cancelled*
  (e.g. Intel Magdeburg). Surfaced as a badge and filterable, so "announced ≠ delivered" is visible
  at a glance.

## Commitment → outlay reconciliation (Stage 3)

Most rows are *announced commitments*, not verified disbursements. The **Realization** view tracks how
much of a pledge has actually landed, from dated observations in `data/realizations.jsonl` (keyed by
`event_key`, append-only):

- **`realization_rate`** = latest realized USD ÷ the event's committed headline.
- **`expected_rate`** = the fraction due by the observation date on a **linear horizon schedule**
  (`(as_of − start) ÷ (end − start)`).
- **`pace_status`** ∈ {ahead · on track · behind · stalled} — derived from realized-vs-expected, or set
  explicitly per observation via `pace_flag` when no dollar figure is yet public (e.g. **Stargate**,
  flagged *behind* on the SoftBank-reported slow start).
- **`realized_basis`** ∈ {obligated · disbursed · deployed · reported} — *obligated* awards are **not**
  *disbursed* cash, so the basis is always shown (e.g. CHIPS shows ~$25B **obligated** (Dec 2024), well above
  schedule, while cash out the door lags far behind).

Realization is an event-level fact and **nothing is summed across events** — the cardinal rule holds.
Coverage is a deliberately small, flagged seed: official outlay statistics lag 1–2 years, so most
pledges are simply *not yet tracked* rather than silently assumed realized.

## Composite index (Stage 4 — PROVISIONAL)

The *optional* ranking layer ships on its own page, **`composite-index.html`**, built to OECD/JRC
**Handbook on Constructing Composite Indicators** discipline and computed over the raw ledger:

- **Fixed transparent weights** (in `data/index-weights.json`): public-outlay effort (%GDP, 0.40),
  fiscal prioritization (×GBARD, 0.20), program breadth (0.15), evidence quality (0.25).
- **Geometric aggregation** over min-max-normalized indicators, limiting compensability.
- **Missing data is `n/a`, never imputed** — weights renormalize over what a jurisdiction has, and the
  indicator **coverage (k of N) is shown on every row**.
- **An independent Monte-Carlo audit publishes 90% rank confidence intervals** (2000 draws, fixed seed →
  byte-identical builds), jittering both the indicator values (by per-jurisdiction data confidence) and
  the weights (±25%). **Never a point rank without its interval.**

> **Do not cite these ranks.** With 13 partial-seed jurisdictions the intervals are wide by construction —
> even the top two (Germany, US) tie within their intervals, and a rank can flip just from
> improving a country's source verification. The index exists to demonstrate the method and to
> *expose* how uncertain ranking is at this coverage. The ledger is the product. By design, the index
> rewards genuine **appropriated public outlay**, not announcement headlines — so sovereign-wealth /
> private-mobilization-heavy jurisdictions score low (the cardinal rule, expressed as a ranking).

## Roadmap

| Stage | Status | Scope |
|---|---|---|
| 1 — Ledger | **shipped** | Tagged, source-linked, downloadable government-commitment table |
| 2 — Normalization | **shipped** | Per-capita / %GDP / %GBARD + FX-vs-PPP tradable/non-tradable split |
| 3 — Outlay reconciliation | **shipped (seed)** | Versioned realization history per `event_key` → realization rate, expected-by-schedule rate, and pace flag. Machinery complete; data is a small flagged seed pending the official-statistics lag. |
| 4 — Composite index (optional) | **shipped (PROVISIONAL)** | OECD/JRC discipline: fixed transparent weights, geometric aggregation, n/a never imputed, Monte-Carlo 90% rank CIs. Machinery complete; ranks not citable until coverage grows (≥40 jurisdictions). |

**Current coverage** is **68 records across 22 jurisdictions** (2018–2026, with a comprehensive
2020–present sweep). The Stage-1 advance benchmark is ≥40 jurisdictions with ≥3 sourced records each;
next data work is upgrading `source_tier` T4→T1 by pinning primary budget URLs and expanding
jurisdictions (OECD STIP Compass + OECD.AI dashboards).

## Data quality & caveats

- All figures are **as-reported**; many large headlines are **unverified mobilization targets or private
  capital**, not government outlays. Treat every row as an *announced commitment pending realization*.
- GDP and population denominators are ~2024 nominal and accurate to a few percent; **price-level indices
  (for PPP) and GBARD are illustrative approximations**, flagged for pinning to exact World Bank WDI /
  OECD MSTI / ICP vintages.
- China figures carry the highest uncertainty (overlapping, partly non-additive funds; some estimates).

## Updating the ledger — daily ingestion

The ledger is an **all-time, append-only tracker — one row per announcement**. The viewer defaults to
newest-first, and a **Group → Jurisdiction** toggle rolls announcements up under collapsible per-country
parent rows (the parent shows the announcement count, distinct domains, latest date, and the **dedup'd
public-outlay sum** — never summed headlines, per the cardinal rule).

New announcements enter through a reviewed write-path so a daily headline-scanning job can feed the
ledger safely. The full contract is [`INGESTION.md`](INGESTION.md); the write-path is `ingest.py`:

```bash
python3 ingest.py validate candidates.jsonl   # dry-run: validate + dedup, no write
python3 ingest.py add      candidates.jsonl   # -> data/ingest-queue.jsonl (staging)
python3 ingest.py list                        # review the queue
python3 ingest.py promote [id ...]            # move vetted rows into the ledger
python3 build.py                              # regenerate, then commit
```

The scanner (`scan.py`) proposes candidate records; `ingest.py` validates against `data/schema.json`,
**dedups by `id` (reject) and `event_key` (warn — re-announcements aren't double-counted)**, and stages
them for human review. Auto-extracted rows are `reported`/`unconfirmed`, never self-certified `verified`.

```bash
python3 scan.py run --days 2 --add   # Google News RSS -> Claude extraction -> review queue
```

`scan.py` discovers headlines via **Google News RSS** (stdlib, no key) and extracts schema-valid records
with **Claude** (default `claude-opus-4-8`; `--model claude-sonnet-4-6` for cheaper daily runs) using
structured outputs. It is the one component that is **not** stdlib-only/offline — it needs the network
and `pip install anthropic` + `ANTHROPIC_API_KEY`. Schedule `scan.py run --add` daily (cron / GitHub
Action); it's idempotent on `id`. A human still works the queue and promotes. Full contract: `INGESTION.md`.

## Contributing data

By hand: append one JSON object per line to `data/government-commitments.jsonl` following
`data/schema.json`, then run `python3 build.py`. Prefer primary sources (national budgets, official
press releases); set `verification_status` honestly and leave `source_url` empty only when a primary
link is still pending. For batch/automated additions use `ingest.py` (above).

## License

Dual license (OWID model), finalized:

- **Code** — the generator (`build.py`) and viewer templates — under the **MIT License** (`LICENSE`).
- **Data** — everything in `data/` — under **CC BY 4.0** (`data/LICENSE`). Attribute as
  *"AI/Quantum Investment Ledger, Spencer Lee, CC BY 4.0"* and link the license.

All figures are aggregated from public announcements and official statistics and are provided
**as-reported** — many large headlines are unverified mobilization targets or private capital, and the
Stage-4 composite ranks are **provisional**. Verify against primary sources before reuse.
