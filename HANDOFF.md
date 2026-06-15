# HANDOFF — AI/Quantum Investment Ledger

> Working continuation notes for picking up this project in a fresh session.
> **Remove this file before public release** (it contains process/session notes, not product docs).
> Last updated: 2026-06-15.

## Where this lives

- **Repo:** `Splee9/spencer_brain2` (the Spencer Brain vault) on GitHub.
- **Branch:** `claude/ai-quantum-investment-ledger-cfzhf4`  →  **Pull Request #1**.
- **Path in repo:** `ai-quantum-ledger/` (repo root). In the last container it was
  `/home/user/spencer_brain2/ai-quantum-ledger/`, but remote containers are ephemeral — the branch is
  the durable source of truth.

**To reopen / continue:**
```bash
git fetch origin
git checkout claude/ai-quantum-investment-ledger-cfzhf4
cd ai-quantum-ledger
python3 build.py            # regenerate index.html, then open it
```
This folder is **self-contained** — paths are relative to it, stdlib-only, no vault dependency. To spin
it out as an independent repo: `git mv ai-quantum-ledger ../new-repo` (or copy it), `git init`, done.

## What this project is (one paragraph)

A public, source-linked, transaction-level **ledger of national AI/quantum investment commitments**, with
a normalization layer (per-capita / %GDP / %GBARD) and an FX-vs-PPP currency split. *Layoffs.fyi × Our
World in Data × OECD/JRC rigor.* **The ledger is the product; a composite ranking index is a deliberately
later layer, always over the raw downloadable data.** Full rationale: `README.md` + `methodology.md`. The
originating research dossier lives in the vault at `wiki/sources/2026-06-15-ai-quantum-investment-ledger-research.md`
and the vault project page at `wiki/projects/ai-quantum-investment-ledger.md`.

## Current state — Stages 1–4 SHIPPED (Stage 4 PROVISIONAL)

- **Stage 1 (ledger):** tagged, source-linked, downloadable government-commitment table. 22 records / 14
  jurisdictions / 2 primary-source-verified. Cardinal rule enforced in code: **headlines are never summed**;
  only `public_outlay_usd` over appropriated/outlay actors aggregates (≈ **$71B**, dedup by `event_key`);
  `public_outlay_usd` and `private_mobilized_usd` stay separate.
- **Stage 2 (normalization):** live viewer toggles — **Currency** (Market FX vs PPP-blended =
  `tradable_share·FX + (1−tradable_share)·PPP`) and **View** (Absolute / Per-capita / %GDP / ×GBARD),
  joined to `data/denominators.json` on `iso3`. PPP is a flagged sensitivity scenario, never the default.
- **Stage 3 (realization):** new `data/realizations.jsonl` (append-only, dated observations keyed by
  `event_key`). `build.py` joins it and computes per-record `realization_rate` (realized ÷ committed
  headline), `expected_rate` (linear horizon schedule), and `pace_status` (ahead/on_track/behind/stalled;
  `pace_flag` override when no $ figure exists). Viewer gains a **Realization** View, a **Tracked only**
  filter, and a "Pledges tracked / N behind" KPI. Seeded with 5 flagged pledges (CHIPS ~$33B obligated &
  ahead; Stargate & EU InvestAI behind; Canada & IndiaAI on-track). **Realization is event-level; nothing
  new is summed.** Current build: 22 records / 14 jurisdictions / 2 verified / $71.0B outlays / 5 tracked.
- **Stage 4 (composite index — PROVISIONAL):** separate generated page `composite-index.html` over the
  raw ledger, OECD/JRC discipline. Config in `data/index-weights.json` (4 indicators: outlay %GDP 0.40,
  ×GBARD 0.20, breadth 0.15, evidence 0.25). Min-max→[1,100], **weighted geometric mean over available
  indicators** (n/a never imputed; coverage k/N shown), EU bloc excluded → **13 jurisdictions ranked**.
  **Monte-Carlo audit → 90% rank CIs** (2000 draws, seed 20260615, **byte-identical builds**), jittering
  indicator values (per-jurisdiction confidence σ) + weights (±25%). #1 USA (CI 1–1, via CHIPS $52.7B
  appropriated); everything below sits in wide overlapping CIs — the intended "don't cite these ranks"
  signal. By design the index rewards appropriated **outlay**, not headlines, so China/Saudi/UAE rank low.

## File map

| File | Role |
|---|---|
| `README.md` | Project front door (overview, quick-start, roadmap, license note) |
| `methodology.md` | Public methodology — the tagging axes + normalization formulas |
| `build.py` | Generator (stdlib only): validates data + denominator join, computes derived fields, bakes `index.html` |
| `index.html` | The viewer (generated). **Hostable entry point** — serves at a site root |
| `data/schema.json` | Record field contract (+ `_normalization` and `_realization` blocks) |
| `data/government-commitments.jsonl` | Canonical ledger — append-only, one JSON object per line |
| `data/denominators.json` | GDP / population / price-level-index / GBARD by ISO3 |
| `data/realizations.jsonl` | Stage 3 — dated realization observations keyed by `event_key` (append-only) |
| `composite-index.html` | Stage 4 — provisional composite ranking with 90% rank CIs (generated) |
| `data/index-weights.json` | Stage 4 — indicators, fixed weights, Monte-Carlo seed/draws |

## How to preview (headless screenshot recipe)

`index.html` opens directly in any browser. To capture a screenshot headlessly (what we used this session):
Chromium ships at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` in the Claude container; install the
playwright npm module (`npm install playwright` in /tmp), then `chromium.launch({ executablePath: '<that
path>', args: ['--no-sandbox'] })`, `page.goto('file://.../index.html')`, click `#fBasis`/`#fView`/`#fDomain`
buttons to drive toggles, `page.screenshot(...)`. (Validation can also be done in pure Node with a DOM shim
that captures `#tb`.innerHTML — see git history of the old `scripts/` generator for that pattern.)

## What's NEXT (pick up here)

**Immediate data-quality TODOs (to truly close Stage 1):**
1. **Pin primary-source URLs** on every `verification_status: "reported"` row with an empty `source_url`
   (Germany, South Korea, Singapore, Australia, Israel national strategies). Promote to `verified` once traced.
2. **Expand coverage 14 → ≥40 jurisdictions**, ≥3 records each — seed from **OECD STIP Compass** and the
   **OECD.AI policy dashboards** (both free). Candidates not yet in: Japan, Taiwan, Italy, Spain, Netherlands,
   Brazil, Switzerland, Finland, Nordics, etc.
3. **Pin denominators** in `data/denominators.json` to exact vintages — GDP/pop from **World Bank WDI**,
   price-level indices from **ICP 2021**, **GBARD** from **OECD MSTI** (currently illustrative approximations,
   flagged in `_meta`).

**Stage 3 — SHIPPED (machinery; data is a seed).** Remaining Stage-3 *data* work: expand
`data/realizations.jsonl` beyond the 5 seed pledges as official outlay stats land — pin `disbursed`
(not just `obligated`) figures for CHIPS from the Commerce CHIPS Program Office; add OECD / national-
accounts outlay observations for the appropriated-outlay rows (Canada, France quantum, Germany, etc.);
trace `source_url` on the Stargate/SoftBank pace observation. The linear-schedule `expected_rate` is a
simple baseline — a future refinement could accept a per-pledge disbursement curve if one is published.

**Stage 4 — SHIPPED (machinery; PROVISIONAL).** The composite-index engine is complete and disciplined
(fixed weights, geometric aggregation, n/a never imputed, Monte-Carlo 90% rank CIs, reproducible seed).
What it now NEEDS is **coverage, not code**: the ranks are uncitable until the ledger reaches ≥40
jurisdictions (TODO #2 above). Optional refinements when coverage grows: add per-capita / realization
indicators, sensitivity analysis on the weight scheme, and a correlation check across indicators (the
three outlay-derived ones are correlated by construction). Do NOT promote the ranks off "PROVISIONAL"
until coverage and the data-quality TODOs land.

**Release finalization — DONE except the last cleanup.** `LICENSE` (MIT, code) and `data/LICENSE`
(CC BY 4.0, data) are committed; README license section + folder layout updated; the dense viewer "how
to read" note is now a collapsible `<details>` (cardinal-rule line stays visible). **The only remaining
publish step: delete this `HANDOFF.md`** (process notes, not product docs) when spinning the folder out as
a standalone repo. Copyright holder used: "Spencer Lee, 2026" — change if a different attribution is wanted.

## Open decisions — RESOLVED

- **License:** ✅ finalized OWID-style split — MIT for code (`LICENSE`), CC BY 4.0 for data (`data/LICENSE`).
- **Header polish:** ✅ done — the "how to read" note collapses to a one-liner + `<details>`.
- **Sequence:** ✅ moot — Stages 1–4 all shipped. Remaining work is data **coverage** (TODO #2, the gating
  item for citable Stage-4 ranks) and the data-quality TODOs (#1, #3), not new stages.

## Provenance note

Most large headlines (Stargate $500B, EU InvestAI €200B, France €109B, Saudi/UAE $100B) are private/
mobilized capital or multi-year targets, **not government outlays** — every row is an *announced commitment
pending realization*. China rows overlap and are partly non-additive (flagged `low`/`estimate`). All figures
as-reported through mid-June 2026.
