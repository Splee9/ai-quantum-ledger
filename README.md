# AI/Quantum Investment Ledger

A public, source-linked, **transaction-level ledger of national (and government-adjacent) AI and quantum
investment commitments** — with a transparent normalization layer (per-capita / %GDP / %GBARD) and an
FX-vs-PPP currency split. Think *Layoffs.fyi × Our World in Data × OECD/JRC composite-indicator rigor*,
for government technology spend.

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
├── LICENSE                           # MIT (covers the code / build.py)
├── methodology.md                    # the public methodology (how figures are tagged & normalized)
├── build.py                          # generator: validates data + bakes both pages (stdlib only)
├── index.html                        # the ledger viewer (generated; hostable entry point)
├── composite-index.html              # Stage 4: provisional composite ranking w/ 90% rank CIs (generated)
└── data/
    ├── LICENSE                       # CC BY 4.0 (covers everything in data/)
    ├── schema.json                   # the record field contract (+ normalization & realization blocks)
    ├── government-commitments.jsonl  # canonical ledger (append-only, one JSON object per line)
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
  *disbursed* cash, so the basis is always shown (e.g. CHIPS shows ~$33B **obligated**, well above
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
> only the top rank is currently distinguishable. The index exists to demonstrate the method and to
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

**Current coverage** is a partial seed (22 records / 14 jurisdictions). The Stage-1 advance benchmark is
≥40 jurisdictions with ≥3 sourced records each; next data work is pinning primary-source URLs on
`reported` rows and expanding jurisdictions (OECD STIP Compass + OECD.AI dashboards).

## Data quality & caveats

- All figures are **as-reported**; many large headlines are **unverified mobilization targets or private
  capital**, not government outlays. Treat every row as an *announced commitment pending realization*.
- GDP and population denominators are ~2024 nominal and accurate to a few percent; **price-level indices
  (for PPP) and GBARD are illustrative approximations**, flagged for pinning to exact World Bank WDI /
  OECD MSTI / ICP vintages.
- China figures carry the highest uncertainty (overlapping, partly non-additive funds; some estimates).

## Contributing data

Append one JSON object per line to `data/government-commitments.jsonl` following `data/schema.json`,
then run `python3 build.py` (it validates the field contract and the denominator join and re-bakes the
viewer). Prefer primary sources (national budgets, official press releases); set `verification_status`
honestly and leave `source_url` empty only when a primary link is still pending.

## License

Dual license (OWID model), finalized:

- **Code** — the generator (`build.py`) and viewer templates — under the **MIT License** (`LICENSE`).
- **Data** — everything in `data/` — under **CC BY 4.0** (`data/LICENSE`). Attribute as
  *"AI/Quantum Investment Ledger, Spencer Lee, CC BY 4.0"* and link the license.

All figures are aggregated from public announcements and official statistics and are provided
**as-reported** — many large headlines are unverified mobilization targets or private capital, and the
Stage-4 composite ranks are **provisional**. Verify against primary sources before reuse.
