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
├── methodology.md                    # the public methodology (how figures are tagged & normalized)
├── build.py                          # generator: validates data + bakes index.html (stdlib only)
├── index.html                        # the viewer (generated; hostable entry point)
└── data/
    ├── schema.json                   # the record field contract
    ├── government-commitments.jsonl  # canonical ledger (append-only, one JSON object per line)
    └── denominators.json             # GDP / population / price-level / GBARD by ISO3 (normalization)
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
- **View:** Absolute · Per-capita · % of GDP (national effort) · × GBARD (fiscal prioritization).

## Roadmap

| Stage | Status | Scope |
|---|---|---|
| 1 — Ledger | **shipped** | Tagged, source-linked, downloadable government-commitment table |
| 2 — Normalization | **shipped** | Per-capita / %GDP / %GBARD + FX-vs-PPP tradable/non-tradable split |
| 3 — Outlay reconciliation | planned | Versioned "realization rate": commitments vs. OECD/national-accounts outlays on the 1–2yr lag |
| 4 — Composite index (optional) | planned | OECD/JRC discipline: fixed transparent weights, geometric aggregation, published 90% rank confidence intervals — always over the raw ledger |

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

Intended dual license (OWID model): **code (build.py) under MIT**, **data under CC-BY-4.0** — finalize
before public release. All figures are aggregated from public announcements and official statistics;
attribute and verify before reuse.
