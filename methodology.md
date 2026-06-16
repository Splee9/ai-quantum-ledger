# AI/Quantum Investment Ledger — Methodology (Stages 1–4)

> Public methodology page for the government-commitments ledger. The ledger is the product;
> a composite index is a deliberately later layer (Stage 4). See `README.md` for the project
> overview and roadmap, and `data/schema.json` for the full field contract.

## What this is

A **source-linked, downloadable ledger of announced government (and government-adjacent) AI/quantum
investment commitments.** One row = one announcement. Every figure is tagged on the comparability
axes **before** any normalization or aggregation, so a reader can filter to apples-and-apples
subsets (e.g. "appropriated public outlays only").

## What this is *not* (yet)

- **A partial outlay tracker.** Most rows are *announced commitments*, not verified disbursements.
  **Stage 3 (live)** reconciles commitments against realized outlays for a small, flagged seed of
  pledges; full coverage is gated on the 1–2-year official-statistics lag.
- **Not a ranking to cite.** **Stage 4 (live, PROVISIONAL)** ships the composite-index *machinery*
  with published 90% rank confidence intervals — but at current coverage those intervals are wide by
  construction and the ranks must not be cited. The index is a deliberately later layer over the ledger.
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

## Commitment → outlay reconciliation (Stage 3, live)

The ledger stores *announcements*; Stage 3 asks **how much actually happened**. Realization observations
live in a separate append-only file, `data/realizations.jsonl`, keyed by `event_key` (the same key that
dedups re-announcements). Each line is one **dated observation**:

| Field | Meaning |
|---|---|
| `as_of` | When the observation was made (`YYYY-MM`); the generator keeps a per-pledge history sorted by date and shows the latest. |
| `realized_usd` | Cumulative realized USD. **Null** when no credible dollar figure exists yet. |
| `realized_basis` | `obligated` (awarded, not paid) · `disbursed` (public cash out) · `deployed` (private/SWF capital spent) · `reported` (press only). **Obligated ≠ disbursed** — always surfaced. |
| `pace_flag` | Manual pace override for when realization can't yet be a number (a credibly-reported slow start). Overrides the computed pace. |
| `verification_status` / `confidence` / `source_name` / `source_url` / `notes` | Same sourcing discipline as the ledger. |

`build.py` joins these to the ledger and computes, per record:

> `realization_rate = latest realized_usd ÷ committed` (the event's headline `usd_approx`).
> `expected_rate = clamp₀¹((as_of_year − horizon_start) ÷ (horizon_end − horizon_start))` — the fraction
> *due by now* on a **linear schedule**.
> `pace_status` = `pace_flag` if set, else from `realization_rate ÷ expected_rate`:
> **≥1.1 ahead · ≥0.9 on track · ≥0.5 behind · else stalled**.

The viewer's **Realization** view shows the realized %, basis, and a pace tag; a **Tracked only** filter
isolates the seeded pledges, and a KPI counts tracked pledges and how many are behind/stalled.

**Integrity guards.** Realization is an **event-level** fact — records sharing an `event_key` share the
computed values, and **nothing new is summed across events**. The linear schedule is a deliberately
simple, transparent baseline (real disbursement curves are back-loaded; *behind early* is normal and
labeled, not alarmist). Coverage is intentionally a **small flagged seed** — e.g. CHIPS (~$25B
*obligated*, ahead of schedule, with cash disbursement far behind) and Stargate (flagged *behind* on the
reported slow start) — because official outlay statistics lag 1–2 years; an untracked pledge shows as
*not tracked*, never as silently realized.

## The composite index (Stage 4, live — PROVISIONAL)

Stage 4 ships the *optional* ranking layer, built strictly to OECD/JRC **Handbook on Constructing
Composite Indicators** discipline and rendered on its own page (`composite-index.html`) over the raw
ledger. It exists to demonstrate the method **and to show how uncertain the ranks are at current
coverage** — not to rank countries. Every design choice is in `data/index-weights.json`.

**Ranking unit.** Jurisdiction (`iso3`). The **EU bloc is excluded** to avoid double-counting member
states. 13 jurisdictions are currently rankable.

**Indicators (fixed, transparent weights).**

| Indicator | Weight | Definition |
|---|---|---|
| Public-outlay effort (% GDP) | 0.40 | `sum(public_outlay_usd)` over outlay actors, dedup by `event_key`, ÷ GDP × 100. The cardinal-rule aggregate — headlines are never summed. |
| Fiscal prioritization (× GBARD) | 0.20 | public outlay ÷ government R&D budget. **n/a where GBARD is unknown** (not imputed). |
| Program breadth (domains) | 0.15 | distinct domains the jurisdiction has a record in (1–5). |
| Evidence quality (0–1) | 0.25 | verification-weighted mean over its records (verified 1.0 / reported 0.6 / estimate 0.3 / unconfirmed 0.1). |

**Normalization → aggregation.** Each indicator is **min-max normalized to [1, 100]** across the ranked
jurisdictions (lower bound 1, not 0, so the geometric mean is well-defined). The composite is a
**weighted geometric mean over the indicators a jurisdiction actually has** — missing indicators are
`n/a`, the weights are **renormalized** over what's present, and the **coverage (k of N)** is reported
on every row. Geometric (not arithmetic) aggregation deliberately limits compensability: a very weak
dimension can't be fully offset by a strong one.

**The deliberate consequence.** Because the outlay indicators reward *appropriated public outlay* and
not announcement headlines, jurisdictions whose commitments are sovereign-wealth, state-fund, or private
mobilization capital (Saudi Arabia, UAE, much of China, France's €109B headline) score **low by design**
— their money is not appropriated public spend. This is the cardinal rule expressed as a ranking, not a
flaw.

**Uncertainty audit → 90% rank confidence intervals.** Point ranks are never shown alone. A Monte-Carlo
audit (`R = 2000` draws, **fixed seed → byte-identical builds**) re-ranks the field under joint
perturbation of (a) every indicator's underlying value by a **per-jurisdiction data-confidence σ**
(high/medium/low → 5% / 15% / 35%) and (b) the **weights by ±25%** (renormalized), re-normalizing and
re-ranking each draw. Each jurisdiction's **5th–95th-percentile rank is its 90% CI**. At present even
the top two jurisdictions tie within their intervals — a rank can flip merely from improving a country's
source verification (e.g. verifying Germany's two programs to official docs lifted its evidence-quality
indicator enough to tie the US) — and nearly everything else sits in wide overlapping intervals. That is
the intended, honest signal that **the ledger needs far more coverage before any rank is meaningful**.

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
- Realizations: `data/realizations.jsonl` (append-only; dated outlay observations keyed by `event_key`).
- Index weights: `data/index-weights.json` (Stage 4 — indicators, fixed weights, MC seed/draws).
- Viewers: `index.html` (the ledger — FX/PPP and absolute/per-capita/%GDP/×GBARD/Realization toggles) and
  `composite-index.html` (the provisional Stage-4 ranking with 90% rank CIs). Both self-contained,
  dependency-free, CSV-downloadable.
- Regenerate: `python3 build.py` (validates the contract + denominator join + realization join, computes
  annualized USD, the FX/PPP-blended figure, the conservative outlay aggregate, the realization
  rate/expected-rate/pace per pledge, **and** the Stage-4 composite + Monte-Carlo rank CIs, then bakes
  both pages).

*All figures as-reported through mid-June 2026.*
