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

## Current state — Stages 1 & 2 SHIPPED

- **Stage 1 (ledger):** tagged, source-linked, downloadable government-commitment table. 22 records / 14
  jurisdictions / 2 primary-source-verified. Cardinal rule enforced in code: **headlines are never summed**;
  only `public_outlay_usd` over appropriated/outlay actors aggregates (≈ **$71B**, dedup by `event_key`);
  `public_outlay_usd` and `private_mobilized_usd` stay separate.
- **Stage 2 (normalization):** live viewer toggles — **Currency** (Market FX vs PPP-blended =
  `tradable_share·FX + (1−tradable_share)·PPP`) and **View** (Absolute / Per-capita / %GDP / ×GBARD),
  joined to `data/denominators.json` on `iso3`. PPP is a flagged sensitivity scenario, never the default.

## File map

| File | Role |
|---|---|
| `README.md` | Project front door (overview, quick-start, roadmap, license note) |
| `methodology.md` | Public methodology — the tagging axes + normalization formulas |
| `build.py` | Generator (stdlib only): validates data + denominator join, computes derived fields, bakes `index.html` |
| `index.html` | The viewer (generated). **Hostable entry point** — serves at a site root |
| `data/schema.json` | Record field contract (+ `_normalization` block) |
| `data/government-commitments.jsonl` | Canonical ledger — append-only, one JSON object per line |
| `data/denominators.json` | GDP / population / price-level-index / GBARD by ISO3 |

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

**Stage 3 (commitment → outlay reconciliation):** add a versioned "realization" field updating announced
commitments against OECD / national-accounts outlay data on the 1–2yr statistical lag; surface a public
**"commitment realization rate"** per major pledge (e.g. flag Stargate's reported slow start). Schema work
+ a `realizations` history per `event_key`.

**Stage 4 (optional composite index):** only after the ledger is trusted. OECD/JRC Handbook discipline —
fixed transparent weights, geometric aggregation, missing data as `n/a` (not imputed), and an independent
statistical audit publishing **90% rank confidence intervals**. Never a point rank without its interval.

## Open decisions (were on the table when we paused)

- **License:** README flags an intended OWID-style split (MIT for `build.py`, CC-BY-4.0 for data). Not yet
  finalized — no `LICENSE` files committed. Offer was open to drop them in to make the standalone repo
  publish-ready.
- **Header polish:** the viewer's intro/"how to read" text is a bit dense at full width; an optional tidy
  (one-liner + collapsible detail) was offered but not done.
- **Sequence:** backfill data quality (TODOs 1–3 above) to firm up Stages 1–2 *before* Stage 3, vs. building
  Stage 3 next. Recommendation: do TODO #1 (cheap, raises credibility) and at least start #2, then Stage 3.

## Provenance note

Most large headlines (Stargate $500B, EU InvestAI €200B, France €109B, Saudi/UAE $100B) are private/
mobilized capital or multi-year targets, **not government outlays** — every row is an *announced commitment
pending realization*. China rows overlap and are partly non-additive (flagged `low`/`estimate`). All figures
as-reported through mid-June 2026.
