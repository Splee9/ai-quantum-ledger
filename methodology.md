# AI/Quantum Investment Ledger — Methodology (Stages 1–2)

> Public methodology page for the government-commitments ledger. The ledger is the product;
> a composite index is a deliberately later layer (Stage 4). See `README.md` for the project
> overview and roadmap, and `data/schema.json` for the full field contract.

## What this is

A **source-linked, downloadable ledger of announced government (and government-adjacent) AI/quantum
investment commitments.** One row = one announcement. Every figure is tagged on the comparability
axes **before** any normalization or aggregation, so a reader can filter to apples-and-apples
subsets (e.g. "appropriated public outlays only").

## What this is *not* (yet)

- **Not an outlay tracker.** Most rows are *announced commitments*, not verified disbursements.
  Reconciling commitments against realized outlays is **Stage 3** (gated on the 1–2-year official-
  statistics lag).
- **Not a ranking.** No composite index until **Stage 4**, and only then with published 90% rank
  confidence intervals over the raw ledger.
- **Not complete.** This is a Stage-1 **seed** (currently ~22 records / ~14 jurisdictions). The
  Stage-1 advance benchmark is **≥40 jurisdictions, ≥3 sourced records each**.

## The cardinal rule: headlines are not additive

The single biggest integrity threat is **"announcement inflation"** — summing headline numbers that
are mostly private capital, multi-year targets, or the same money re-announced. So:

1. **Headline figures are never summed into a global total.** The viewer's "sum of headlines" KPI
   exists only to convey scale and is labeled non-additive.
2. **The only defensible aggregate is `sum(public_outlay_usd)` over `government_appropriated` /
   `government_outlay` actors, deduplicated by `event_key`.** That is the "appropriated public
   outlays" KPI.
3. **`public_outlay_usd` and `private_mobilized_usd` are stored separately and never combined** into
   a single "government investment" figure (the EU InvestAI / France €109B "mobilization" trap).

## Field contract

The full schema is `data/schema.json`. Key fields and the questions they answer:

| Field | Why it exists |
|---|---|
| `actor_type` | Is this a budget outlay, a state fund, sovereign-wealth investment, a mobilization target, or private capital? Drives every honest aggregate. |
| `public_outlay_usd` / `private_mobilized_usd` | Splits the headline so public and private are never conflated. |
| `headline_amount` + `currency` + `usd_approx` + `fx_rate_to_usd` | Original-currency figure, the USD conversion, and the rate used. (Stage 2 pins per-record *announcement-date* FX.) |
| `amount_low` / `amount_high` | Captures vague figures ("up to $100B") as a range, not a false point. |
| `horizon_start_year` / `horizon_end_year` | Lets the generator **annualize** a multi-year stock into a flow (`usd_approx ÷ years`) so a 10-year pledge isn't compared to a single-year figure. |
| `verification_status` (`verified`/`reported`/`estimate`/`unconfirmed`) + `confidence` | Nothing is hidden; low-confidence and estimated figures are shown *and flagged*, never silently dropped. |
| `event_key` | Groups re-announcements of the *same* money so dedup is possible. |
| `source_name` / `source_url` | A `reported` row with an empty `source_url` is awaiting a pinned primary source — an explicit TODO, not a hidden gap. |

## Currency conversion — and the compute exception (Stage 2, live)

Every headline converts to USD via `usd_approx` at market FX (with `fx_rate_to_usd` where known). The
viewer's **Currency** toggle then offers the research's methodological contribution — a **tradable /
non-tradable split**:

> `USD_blended = tradable_share × USD_FX + (1 − tradable_share) × USD_PPP`,
> where `USD_PPP = usd_approx ÷ price_level_index`.

The **tradable share** is the fraction that is globally-priced hardware (GPUs/compute), converted at
**market FX**; the remainder (talent, operations, local construction) is non-tradable and converted at
**PPP**. Absent line-item data, the generator applies a documented domain default — compute 0.90,
semiconductor 0.65, ai 0.55, ai+quantum 0.50, quantum 0.45 — overridable per record via `tradable_share`.
**PPP is a sensitivity SCENARIO, never ground truth** (OECD warns its PPPs are GDP-designed and may be
significantly revised); market FX remains the default basis.

## Normalization (Stage 2, live)

The **View** toggle joins each record to `denominators.json` on `iso3` and shows:

| View | Formula | Question it answers |
|---|---|---|
| Absolute | `usd_approx` (stock) + `annualized_usd` (stock ÷ horizon years) | raw scale |
| Per-capita | basis amount ÷ population | population intensity |
| % of GDP | annualized basis ÷ GDP × 100 | national *effort* (R&D-intensity style) |
| × GBARD | annualized basis ÷ government R&D budget | *fiscal prioritization* |

All four respond to the FX/PPP currency toggle. **Denominator quality:** GDP and population are ~2024
nominal and accurate to a few percent; **price-level indices (for PPP) and GBARD are illustrative
approximations**, flagged in `denominators.json._meta` for later pinning to exact World Bank WDI /
OECD MSTI / ICP 2021 vintages. Where GBARD is unknown (China opacity, several smaller economies) the
× GBARD view shows `n/a` rather than imputing.

## Known caveats baked into the current seed

- **China rows overlap and are partly non-additive** — the national AI fund draws from Big Fund III;
  the ¥1T guidance fund spans AI+quantum+hydrogen; the $184B is a Stanford *estimate*. All flagged
  `low`/`estimate` with notes.
- **Sovereign-wealth headlines (Saudi, UAE) are investment capital, not appropriated R&D budgets** —
  tagged `sovereign_wealth`, excluded from the public-outlay aggregate.
- **`reported` rows with empty `source_url`** (several national strategies) need a primary-source URL
  pinned before promotion to `verified`.

## Provenance & regeneration

- Canonical data: `data/government-commitments.jsonl` (append-only; one JSON object per line).
- Denominators: `data/denominators.json` (GDP, population, price-level index, GBARD by `iso3`).
- Viewer: `index.html` — self-contained, dependency-free, sortable/filterable, CSV-downloadable, with
  live FX/PPP and absolute/per-capita/%GDP/×GBARD toggles.
- Regenerate: `python3 build.py` (validates the contract + denominator join, computes annualized USD,
  the FX/PPP-blended figure, and the conservative outlay aggregate, then bakes data + denominators
  inline into the HTML).

*All figures as-reported through mid-June 2026.*
