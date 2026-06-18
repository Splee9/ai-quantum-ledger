#!/usr/bin/env python3
"""Build the AI/Quantum Investment Ledger viewer.

Self-contained: all paths are relative to this script's folder, so the project
folder can be hosted independently (GitHub Pages / Netlify / any static host).

Stage 1: source-linked, tagged, downloadable ledger of government commitments.
Stage 2: normalization layer — per-capita / per-GDP / per-GBARD views joined on
         iso3, plus a tradable/non-tradable FX-vs-PPP currency split.
Stage 3: commitment -> outlay reconciliation — a versioned realization history per
         event_key (data/realizations.jsonl), a computed realization rate vs the
         committed headline, an expected-by-now rate from the linear horizon
         schedule, and a pace flag (ahead / on_track / behind / stalled) that
         surfaces slow pledges (e.g. Stargate) WITHOUT summing anything new.

Reads data/government-commitments.jsonl + data/denominators.json +
data/realizations.jsonl, validates each record, computes derived fields, and bakes
a self-contained, dependency-free index.html with live view + currency-basis toggles.

Design rules (see methodology.md):
  - The ledger is the product; aggregates carry explicit non-additivity warnings.
    Headline figures are NEVER summed into a single global total.
  - public_outlay_usd and private_mobilized_usd are separate, never combined.
  - Every figure carries verification_status + confidence; nothing is hidden.
  - PPP is a SENSITIVITY SCENARIO (market FX for tradable compute, PPP for
    non-tradable talent/ops), never presented as ground truth.

Usage:  python3 build.py
"""
import json
import os
import sys
import html
import math
import random
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "government-commitments.jsonl")
DENOM = os.path.join(HERE, "data", "denominators.json")
REAL = os.path.join(HERE, "data", "realizations.jsonl")
WEIGHTS = os.path.join(HERE, "data", "index-weights.json")
OUT = os.path.join(HERE, "index.html")
INDEX_OUT = os.path.join(HERE, "composite-index.html")
# Redesigned viewer (design-handoff Power Index). build.py does NOT generate this
# page's template — it only injects live ledger aggregates into a marked block,
# so the file stays a working standalone demo when the generator hasn't run.
POWER_OUT = os.path.join(HERE, "power-index.html")
POWER_MARK_START = "/* ===POWER-INDEX-LEDGER-DATA START=== */"
POWER_MARK_END = "/* ===POWER-INDEX-LEDGER-DATA END=== */"

REQUIRED = ["id", "jurisdiction", "iso3", "program", "domain", "currency",
            "usd_approx", "announced", "actor_type", "verification_status",
            "confidence", "source_name", "event_key"]
ACTOR_TYPES = {"government_appropriated", "government_outlay", "state_fund",
               "sovereign_wealth", "mobilization_target", "public_private", "private"}
OUTLAY_ACTORS = {"government_appropriated", "government_outlay"}
# Source-fidelity tiers (see data/schema.json#_source_tiers). 1 = primary/official,
# 2 = major secondary, 3 = trade/regional/aggregator, 4 = low. The collection routine
# keeps only tier <= SOURCE_TIER_MIN.
SOURCE_TIERS = {1, 2, 3, 4}
SOURCE_TIER_MIN = 2
# Stage 3: realization tracking
REALIZED_BASIS = {"obligated", "disbursed", "deployed", "reported"}
PACE_FLAGS = {"ahead", "on_track", "behind", "stalled"}
# Stage 4: composite index — evidence weights + per-confidence Monte-Carlo sigma
VWEIGHT = {"verified": 1.0, "reported": 0.6, "estimate": 0.3, "unconfirmed": 0.1}
CONF_SD = {"high": 0.05, "medium": 0.15, "low": 0.35}
# Default share of a commitment that is globally-priced tradable hardware (market FX);
# the remainder is non-tradable (talent/ops/local construction) -> PPP in the blend.
TRADABLE_DEFAULT = {"compute": 0.90, "semiconductor": 0.65, "ai": 0.55,
                    "ai+quantum": 0.50, "quantum": 0.45}


def load_denominators():
    with open(DENOM, encoding="utf-8") as fh:
        d = json.load(fh)
    d.pop("_meta", None)
    return d


def load_records(denom):
    recs, ids, errors = [], set(), []
    with open(DATA, encoding="utf-8") as fh:
        for ln, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                r = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"line {ln}: bad JSON ({e})")
                continue
            for f in REQUIRED:
                if f not in r:
                    errors.append(f"line {ln} ({r.get('id','?')}): missing '{f}'")
            if r.get("actor_type") not in ACTOR_TYPES:
                errors.append(f"line {ln} ({r.get('id','?')}): bad actor_type '{r.get('actor_type')}'")
            if r.get("id") in ids:
                errors.append(f"line {ln}: duplicate id '{r.get('id')}'")
            ids.add(r.get("id"))
            if r.get("iso3") not in denom:
                errors.append(f"line {ln} ({r.get('id','?')}): no denominator for iso3 '{r.get('iso3')}'")

            # derived: annualize multi-year stock into a flow
            s, e = r.get("horizon_start_year"), r.get("horizon_end_year")
            r["annualized_usd"] = (round(r["usd_approx"] / (e - s + 1))
                                   if isinstance(s, int) and isinstance(e, int) and e >= s else None)
            # derived: resolved tradable share + PPP-converted USD
            ts = r.get("tradable_share")
            if ts is None:
                ts = TRADABLE_DEFAULT.get(r["domain"], 0.55)
            r["tradable_share_resolved"] = ts
            pli = (denom.get(r["iso3"]) or {}).get("price_level_index")
            r["usd_fx"] = r["usd_approx"]
            r["usd_ppp"] = round(r["usd_approx"] / pli) if pli else r["usd_approx"]
            recs.append(r)
    return recs, errors


def load_realizations():
    """Realization observations keyed by event_key (append-only jsonl).

    Each line is one as-of observation of how much of a pledge has actually been
    realized. Returns {event_key: [obs sorted by as_of]} plus validation errors.
    """
    series, errors = {}, []
    if not os.path.exists(REAL):
        return series, errors
    with open(REAL, encoding="utf-8") as fh:
        for ln, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                o = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"realizations line {ln}: bad JSON ({e})")
                continue
            ek = o.get("event_key")
            if not ek:
                errors.append(f"realizations line {ln}: missing event_key")
                continue
            if o.get("as_of") is None:
                errors.append(f"realizations line {ln} ({ek}): missing as_of")
            rb = o.get("realized_basis")
            if rb is not None and rb not in REALIZED_BASIS:
                errors.append(f"realizations line {ln} ({ek}): bad realized_basis '{rb}'")
            pf = o.get("pace_flag")
            if pf is not None and pf not in PACE_FLAGS:
                errors.append(f"realizations line {ln} ({ek}): bad pace_flag '{pf}'")
            if o.get("realized_usd") is None and pf is None:
                errors.append(f"realizations line {ln} ({ek}): needs realized_usd or pace_flag")
            series.setdefault(ek, []).append(o)
    for ek in series:
        series[ek].sort(key=lambda o: str(o.get("as_of") or ""))
    return series, errors


def _as_of_year(s):
    try:
        return int(str(s)[:4])
    except (TypeError, ValueError):
        return None


def _pace_from_rates(realized_rate, expected_rate):
    """Compare realized vs expected fraction-of-pledge into thresholds."""
    if realized_rate is None or expected_rate is None:
        return None
    if expected_rate <= 0:
        return "ahead" if realized_rate > 0 else None
    ratio = realized_rate / expected_rate
    if ratio >= 1.1:
        return "ahead"
    if ratio >= 0.9:
        return "on_track"
    if ratio >= 0.5:
        return "behind"
    return "stalled"


def attach_realizations(recs, series):
    """Join realization observations to records by event_key and compute, per record:
    latest realized figure, realization_rate (vs the event's committed headline),
    expected_rate (linear horizon schedule at the as-of date), and a pace_status.
    Realization is an EVENT-level fact, so records sharing an event_key get the same
    computed values. Nothing here is summed across events.
    """
    committed = {}
    for r in recs:
        ek = r["event_key"]
        committed[ek] = max(committed.get(ek, 0), r.get("usd_approx") or 0)
    for r in recs:
        r.update(realized_usd=None, realized_as_of=None, realized_basis=None,
                 realization_rate=None, expected_rate=None, pace_status=None,
                 realization_history=[])
        obs = series.get(r["event_key"])
        if not obs:
            continue
        r["realization_history"] = [{"as_of": o.get("as_of"),
                                     "realized_usd": o.get("realized_usd"),
                                     "realized_basis": o.get("realized_basis"),
                                     "pace_flag": o.get("pace_flag"),
                                     "source_name": o.get("source_name")} for o in obs]
        latest = obs[-1]
        r["realized_usd"] = latest.get("realized_usd")
        r["realized_as_of"] = latest.get("as_of")
        r["realized_basis"] = latest.get("realized_basis")
        comm = committed.get(r["event_key"]) or 0
        if r["realized_usd"] is not None and comm > 0:
            r["realization_rate"] = r["realized_usd"] / comm
        s, e, y = r.get("horizon_start_year"), r.get("horizon_end_year"), _as_of_year(latest.get("as_of"))
        if isinstance(s, int) and isinstance(e, int) and e > s and y is not None:
            r["expected_rate"] = min(1.0, max(0.0, (y - s) / (e - s)))
        # manual pace_flag override wins; else derive from realized-vs-expected
        r["pace_status"] = (latest.get("pace_flag")
                            or _pace_from_rates(r["realization_rate"], r["expected_rate"]))


def realization_aggregates(recs):
    """Event-level realization rollup (dedup by event_key)."""
    tracked, behind = set(), set()
    for r in recs:
        ek = r["event_key"]
        if r.get("realization_history"):
            tracked.add(ek)
            if r.get("pace_status") in ("behind", "stalled"):
                behind.add(ek)
    return {"tracked": len(tracked), "behind": len(behind)}


def aggregates(recs):
    seen, outlay = set(), 0
    for r in recs:
        if r["actor_type"] in OUTLAY_ACTORS and r["event_key"] not in seen:
            seen.add(r["event_key"])
            outlay += r.get("public_outlay_usd") or 0
    return {
        "records": len(recs),
        "jurisdictions": len({r["jurisdiction"] for r in recs}),
        "outlay_sum": outlay,
        "headline_sum": sum(r["usd_approx"] for r in recs),
        "verified": sum(1 for r in recs if r["verification_status"] == "verified"),
    }


# ---------------------------------------------------------------------------
# Stage 4: provisional composite index (OECD/JRC discipline)
# ---------------------------------------------------------------------------
def load_weights():
    with open(WEIGHTS, encoding="utf-8") as fh:
        return json.load(fh)


def jurisdiction_units(recs, denom):
    """Aggregate the ledger into per-jurisdiction indicator inputs. The EU bloc is
    excluded to avoid double-counting member states. Public outlay uses the
    cardinal-rule aggregate (outlay actors, dedup by event_key); headlines are
    never summed."""
    by = {}
    for r in recs:
        if r["iso3"] == "EU":
            continue
        by.setdefault(r["iso3"], []).append(r)
    units = {}
    for j, rs in by.items():
        d = denom.get(j, {})
        seen, outlay = set(), 0
        for r in rs:
            if r["actor_type"] in OUTLAY_ACTORS and r["event_key"] not in seen:
                seen.add(r["event_key"])
                outlay += r.get("public_outlay_usd") or 0
        domains = {r["domain"] for r in rs}
        evidence = sum(VWEIGHT.get(r["verification_status"], 0.1) for r in rs) / len(rs)
        conf_sd = sum(CONF_SD.get(r["confidence"], 0.35) for r in rs) / len(rs)
        units[j] = {"name": d.get("name", j), "outlay": outlay,
                    "gdp": d.get("gdp_usd"), "gbard": d.get("gbard_usd"),
                    "breadth": len(domains), "evidence": evidence,
                    "domains": sorted(domains), "n_records": len(rs),
                    "conf_sd": conf_sd}
    return units


def _raw_indicators(units, outlay_factor=None, breadth_jit=None, evidence_jit=None):
    """Raw indicator values per unit. n/a (None) is preserved, never imputed.
    The optional *_jit maps apply a Monte-Carlo perturbation per unit."""
    raw = {}
    for j, u in units.items():
        outlay = u["outlay"] * (outlay_factor[j] if outlay_factor else 1.0)
        breadth = u["breadth"] + (breadth_jit[j] if breadth_jit else 0.0)
        evidence = u["evidence"] + (evidence_jit[j] if evidence_jit else 0.0)
        raw[j] = {
            "outlay_gdp": (outlay / u["gdp"] * 100) if u["gdp"] else None,
            "outlay_gbard": (outlay / u["gbard"]) if u["gbard"] else None,
            "breadth": max(1.0, breadth),
            "evidence": min(1.0, max(0.05, evidence)),
        }
    return raw


def composite_from_raw(raw, indicators):
    """min-max -> [1,100] per indicator over AVAILABLE values, then weighted
    geometric mean over available indicators (weights renormalized per unit)."""
    keys = [i["key"] for i in indicators]
    wmap = {i["key"]: i["weight"] for i in indicators}
    norms = {j: {} for j in raw}
    for k in keys:
        vals = [(j, raw[j][k]) for j in raw if raw[j].get(k) is not None]
        xs = [v for _, v in vals]
        lo, hi = (min(xs), max(xs)) if xs else (0.0, 0.0)
        for j, v in vals:
            norms[j][k] = 50.0 if hi == lo else 1.0 + 99.0 * (v - lo) / (hi - lo)
    out = {}
    for j in raw:
        num = den = 0.0
        for k in keys:
            if k in norms[j]:
                num += wmap[k] * math.log(norms[j][k])
                den += wmap[k]
        out[j] = {"norms": norms[j], "coverage": len(norms[j]), "k": len(keys),
                  "composite": math.exp(num / den) if den > 0 else None}
    return out


def _ranks(comp):
    order = sorted((j for j in comp if comp[j]["composite"] is not None),
                   key=lambda j: comp[j]["composite"], reverse=True)
    return {j: i + 1 for i, j in enumerate(order)}


def _pctile(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    i = (len(xs) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def monte_carlo_ranks(units, indicators, draws, seed):
    """Re-rank under jittered indicator values + jittered weights; return the
    5th/50th/95th percentile rank per jurisdiction (90% rank confidence interval)."""
    rng = random.Random(seed)
    base_w = {i["key"]: i["weight"] for i in indicators}
    ranks = {j: [] for j in units}
    for _ in range(draws):
        w = {k: base_w[k] * (1 + rng.uniform(-0.25, 0.25)) for k in base_w}
        s = sum(w.values())
        wj = [{"key": k, "weight": w[k] / s} for k in base_w]
        of = {j: max(0.0, 1 + rng.gauss(0, u["conf_sd"])) for j, u in units.items()}
        bj = {j: rng.gauss(0, 0.5) for j in units}
        ej = {j: rng.gauss(0, 0.05) for j in units}
        comp = composite_from_raw(_raw_indicators(units, of, bj, ej), wj)
        for j, rk in _ranks(comp).items():
            ranks[j].append(rk)
    return {j: {"p5": _pctile(v, 0.05), "p50": _pctile(v, 0.50),
                "p95": _pctile(v, 0.95), "n": len(v)} for j, v in ranks.items()}


def build_index_rows(recs, denom, weights):
    """Compute the point composite + 90% rank CI per jurisdiction; return rows
    sorted by point rank plus a small summary."""
    indicators = weights["indicators"]
    meta = weights.get("_meta", {})
    draws = int(meta.get("draws", 2000))
    seed = int(meta.get("seed", 20260615))
    units = jurisdiction_units(recs, denom)
    point = composite_from_raw(_raw_indicators(units), indicators)
    prank = _ranks(point)
    ci = monte_carlo_ranks(units, indicators, draws, seed)
    rows = []
    for j, u in units.items():
        p = point[j]
        rows.append({
            "iso3": j, "name": u["name"], "rank": prank.get(j),
            "composite": p["composite"], "coverage": p["coverage"], "k": p["k"],
            "norms": p["norms"], "domains": u["domains"], "n_records": u["n_records"],
            "ci_low": round(ci[j]["p5"]) if ci[j]["p5"] is not None else None,
            "ci_med": round(ci[j]["p50"]) if ci[j]["p50"] is not None else None,
            "ci_high": round(ci[j]["p95"]) if ci[j]["p95"] is not None else None,
        })
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] if r["rank"] else 0))
    summary = {"n_ranked": sum(1 for r in rows if r["rank"] is not None),
               "draws": draws, "seed": seed, "n_indicators": len(indicators)}
    return rows, summary


def b(n):
    if n is None:
        return "n/a"
    a = abs(n)
    if a >= 1e9:
        return f"${n/1e9:.1f}B"
    if a >= 1e6:
        return f"${n/1e6:.0f}M"
    return f"${n:,.0f}"


def build_html(recs, denom, agg, ragg, errors):
    recs_sorted = sorted(recs, key=lambda r: r["usd_approx"], reverse=True)
    return TEMPLATE.format(
        data=json.dumps(recs_sorted, separators=(",", ":")),
        denom=json.dumps(denom, separators=(",", ":")),
        n_records=agg["records"], n_juris=agg["jurisdictions"],
        outlay=b(agg["outlay_sum"]), headline=b(agg["headline_sum"]),
        n_verified=agg["verified"],
        n_tracked=ragg["tracked"], n_behind=ragg["behind"],
        errnote=("" if not errors else
                 '<div class="note err"><b>Validation warnings:</b> '
                 + html.escape("; ".join(errors)) + "</div>"),
    )


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI/Quantum Investment Ledger</title>
<style>
:root{{--ink:#262236;--ink2:#3c3950;--mut:#7a7989;--faint:#9b9aa8;--line:#e9eaf0;--line2:#eef0f4;--card:#ffffff;--accent:#ef4e5b;--r:14px;--r-sm:9px;--gap:18px;--mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;--sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--sans);color:var(--ink2);line-height:1.5;background:linear-gradient(180deg,#fafbfc 0%,#f3f4f7 40%,#f1f2f6 100%);background-attachment:fixed;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
.wrap{{max-width:1380px;margin:0 auto;padding:34px 26px 44px}}
.masthead{{margin-bottom:24px}}
.eyebrow{{font-size:11px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--faint)}}
.masthead h1{{font-size:30px;line-height:1.12;font-weight:700;letter-spacing:-.02em;color:var(--ink);margin-top:10px}}
.masthead .lede{{font-size:14px;line-height:1.6;color:var(--mut);margin-top:12px;max-width:92ch}}
.masthead .lede b{{color:var(--ink2);font-weight:600}}
.xlink{{display:inline-flex;align-items:center;gap:7px;margin-top:16px;font-size:13px;font-weight:600;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:8px 16px;text-decoration:none;box-shadow:0 1px 2px rgba(30,30,60,.05)}}
.xlink:hover{{border-color:#d4d6e2}}.xlink .arr{{color:var(--accent);font-size:14px}}
.note{{font-size:12.5px;color:var(--ink2);background:var(--card);border:1px solid var(--line);border-radius:var(--r-sm);padding:13px 16px;margin-bottom:var(--gap);box-shadow:0 1px 2px rgba(30,30,60,.03)}}
.note.err{{background:#fdeef0;border-color:#f3ccd2;color:#a3303c}}.note.err b{{color:#b6333f}}
details.note summary{{cursor:pointer;list-style:none;color:var(--ink);font-weight:600;font-size:13px;display:flex;flex-wrap:wrap;gap:5px;align-items:baseline}}
details.note summary::-webkit-details-marker{{display:none}}
details.note summary .more{{color:var(--mut);font-weight:500;font-size:12px}}
details.note[open] summary{{margin-bottom:8px}}
details.note .d{{font-size:12.5px;line-height:1.62;color:var(--ink2);font-weight:400}}details.note .d b{{color:var(--ink)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:var(--gap)}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:0 1px 2px rgba(30,30,60,.04),0 12px 28px -20px rgba(30,30,60,.14)}}
.kpi .l{{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.12em;font-weight:600;line-height:1.3}}
.kpi .v{{font-family:var(--mono);font-size:25px;font-weight:600;color:var(--ink);margin-top:9px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.kpi .s{{font-size:11.5px;color:var(--mut);margin-top:6px;line-height:1.45}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:22px 24px;box-shadow:0 1px 2px rgba(30,30,60,.04),0 18px 44px -30px rgba(30,30,60,.18);margin-bottom:var(--gap)}}
.rhead{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:14px}}
.rhead h2{{font-size:14px;font-weight:700;color:var(--ink);letter-spacing:-.01em}}
.recent-grid{{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap)}}
@media(max-width:720px){{.recent-grid{{grid-template-columns:1fr}}}}
.rwin-h{{font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);margin-bottom:8px}}
.rbadge{{display:inline-block;background:var(--ink);color:#fff;border-radius:999px;padding:1px 8px;font-size:11px;margin-left:6px;font-weight:600;font-family:var(--mono)}}
.rbadge.zero{{background:#eceef3;color:#9b9aa8}}
.ritem{{font-size:12.5px;padding:7px 2px;border-bottom:1px solid var(--line2);display:flex;gap:10px;align-items:baseline}}
.ritem .rd{{color:var(--faint);font-size:11px;white-space:nowrap;min-width:80px;font-family:var(--mono)}}
.rempty{{color:var(--faint);font-size:12.5px;padding:9px 2px}}
.lbl{{font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);font-weight:600;margin:0 4px 0 2px}}
.ctl{{display:inline-flex;background:#eceef3;border-radius:9px;padding:3px;margin:0 10px 8px 0;flex-wrap:wrap;gap:2px}}
.ctl button{{border:0;background:transparent;padding:6px 12px;border-radius:7px;font-size:12.5px;font-weight:600;color:#6a6878;cursor:pointer;font-family:var(--sans)}}
.ctl button:hover{{color:var(--ink)}}
.ctl button.on{{background:var(--card);color:var(--ink);box-shadow:0 1px 2px rgba(30,30,60,.14)}}
.bar{{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin-bottom:10px}}
.vhelp{{font-size:12px;color:var(--mut);margin:-2px 2px 12px;line-height:1.5}}
.vhelp b{{color:var(--ink2);font-weight:600}}
details.morefilters{{margin:0 0 12px}}
details.morefilters summary{{cursor:pointer;list-style:none;font-size:11.5px;font-weight:600;color:var(--accent);display:inline-block;padding:3px 0}}
details.morefilters summary::-webkit-details-marker{{display:none}}
details.morefilters summary::before{{content:'+ '}}
details.morefilters[open] summary::before{{content:'\2013 '}}
.bar input{{padding:7px 11px;border:1px solid var(--line);border-radius:8px;font-size:13px;min-width:190px;font-family:var(--sans);color:var(--ink2);background:#fbfbfd}}
.bar input:focus{{outline:none;border-color:#c3c5d4;box-shadow:0 0 0 3px rgba(120,120,160,.10)}}
.bar input::placeholder{{color:#a9a8b6}}
.dl{{margin-left:auto;background:var(--ink);color:#fff;border:0;padding:8px 16px;border-radius:8px;font-size:12.5px;font-weight:600;cursor:pointer;font-family:var(--sans)}}
.dl:hover{{background:#1b1830}}
.tbl-scroll{{overflow-x:auto;max-height:78vh;border:1px solid var(--line);border-radius:10px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:5px 10px;text-align:right;border-bottom:1px solid var(--line2);white-space:nowrap}}
th:first-child,td:first-child,th.l,td.l{{text-align:left;white-space:normal}}
th{{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#c8c9d6;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--ink);font-weight:600;z-index:2;padding-top:9px;padding-bottom:9px}}
th:hover{{color:#fff}}
td{{font-variant-numeric:tabular-nums}}
td:not(.l){{font-family:var(--mono);font-size:11.5px;color:var(--ink2)}}
td.l{{color:var(--ink2)}}td.l:first-child{{font-weight:600;color:var(--ink)}}
td.hl{{font-family:var(--mono);font-weight:600;color:var(--ink)}}
tbody tr:nth-child(even) td{{background:#fafbfd}}
tbody tr:hover td{{background:#eef1f9}}
tbody tr.grp td{{background:#eceef5;border-top:1px solid var(--line);border-bottom:1px solid #dcdee9;cursor:pointer;font-family:var(--sans);color:var(--ink)}}
tbody tr.grp:hover td{{background:#e4e6f0}}
tr.grp .tw{{display:inline-block;width:12px;color:var(--mut);font-size:10px}}
tr.child td:first-child{{padding-left:24px;color:var(--mut)}}
th:nth-child(4),td:nth-child(4),th:nth-child(9),td:nth-child(9),th:nth-child(13),td:nth-child(13){{border-left:1px solid var(--line)}}
th:nth-child(4),th:nth-child(9),th:nth-child(13){{border-left:1px solid #46435a}}
.tag{{display:inline-block;font-weight:600;border-radius:999px;font-family:var(--sans);letter-spacing:.01em;font-size:10px;padding:1px 7px}}
.t-public,.p-ahead{{color:#2f7d5b;background:#edf7f1}}
.t-private,.p-behind{{color:#9a6a16;background:#fbf4e6}}
.t-other{{color:#4a5578;background:#eef0f8}}
.p-on_track{{color:#3f5bd0;background:#eef1fc}}
.p-stalled{{color:#c0414b;background:#fcedef}}
.c-high{{color:#2f7d5b;font-weight:600}}.c-medium{{color:#9a6a16}}.c-low{{color:#c0414b}}
.bn{{color:#a9a8b6;font-size:10px;font-family:var(--sans);font-weight:500}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
.foot{{font-size:11.5px;color:var(--faint);text-align:center;padding:18px 10px 4px;line-height:1.6;max-width:96ch;margin:0 auto}}
</style></head><body>
<div class="wrap">
<header class="masthead">
 <div class="eyebrow">Government &amp; government-adjacent commitments</div>
 <h1>AI / Quantum Investment Ledger</h1>
 <p class="lede">An <b>all-time, source-linked tracker of national AI/quantum investment announcements</b> &mdash; one row per announcement &mdash; with per-capita / %GDP / %GBARD views and an FX-vs-PPP currency split. Each figure is tagged commitment-vs-outlay, public-vs-mobilized, horizon, and confidence <b>before</b> any comparison. Sorted newest-first; <b>Arrange</b> as a flat list, grouped by jurisdiction, or <b>rolled up</b> to one aggregate row per country. The ledger is the product; the index is a later layer.</p>
 <a class="xlink" href="composite-index.html"><span class="arr">&rarr;</span> Provisional composite index (Stage&nbsp;4)</a>
</header>
{errnote}
<details class="note"><summary><b>How to read this &mdash; headline figures are NOT additive.</b> The only defensible sum is <b>appropriated public outlays</b> (KPI below). <span class="more">Expand for the full guide &middot;</span></summary>
<div class="d">Most large headlines (Stargate, InvestAI, France) are private/mobilized capital or multi-year targets, not government outlays. <b>PPP-blended</b> applies market FX to the tradable share (compute/hardware) and PPP to the rest (talent/ops) &mdash; a sensitivity scenario, not truth. Normalization denominators (GDP/pop accurate; price-levels &amp; GBARD approximate) are flagged for later pinning. <b>Realization view</b> compares what has actually been realized against the committed headline and a linear-schedule expectation, flagging pace (ahead / on&nbsp;track / behind / stalled) &mdash; <i>obligated</i> awards are not <i>disbursed</i> cash, so the basis is shown; most pledges are not yet tracked (statistics lag 1&ndash;2yr). The <a href="composite-index.html">composite index</a> is a deliberately later, PROVISIONAL layer. Partial seed (target: &ge;40 jurisdictions).</div></details>
<div class="kpis">
 <div class="kpi"><div class="l">Records</div><div class="v">{n_records}</div><div class="s">across {n_juris} jurisdictions</div></div>
 <div class="kpi"><div class="l">Appropriated public outlays</div><div class="v">{outlay}</div><div class="s">genuine budget outlays, dedup by event (FX)</div></div>
 <div class="kpi"><div class="l">Sum of headlines</div><div class="v">{headline}</div><div class="s">NOT additive &mdash; scale only</div></div>
 <div class="kpi"><div class="l">Primary-source verified</div><div class="v">{n_verified}</div><div class="s">traced to a budget / official doc</div></div>
 <div class="kpi"><div class="l">Pledges tracked (realization)</div><div class="v">{n_tracked}</div><div class="s">{n_behind} flagged behind / stalled</div></div>
</div>
<div class="card" id="recentCard">
 <div class="rhead"><h2>Recent announcements</h2><span class="bn" id="recentAsOf"></span>
  <span class="bn" style="margin-left:auto">By announcement date &middot; all records &middot; <code>YYYY-MM</code> dates placed at month start</span></div>
 <div class="recent-grid">
  <div><div class="rwin-h">Last 7 days <span class="rbadge" id="r7n">0</span></div><div id="r7"></div></div>
  <div><div class="rwin-h">Last 30 days <span class="rbadge" id="r30n">0</span></div><div id="r30"></div></div>
 </div>
</div>
<div class="card">
 <div class="bar">
  <span class="lbl" title="How rows are laid out">Arrange</span><span class="ctl" id="fGroup"><button data-v="" class="on">All rows</button><button data-v="group">By jurisdiction</button><button data-v="rollup">Roll-up</button></span>
  <span class="lbl" title="What every value is measured in">Measure</span><span class="ctl" id="fView"><button data-v="abs" class="on">Absolute $</button><button data-v="pc">Per capita</button><button data-v="gdp">% of GDP</button><button data-v="gbard" title="vs annual government R&amp;D budget (GBARD)">&times; R&amp;D budget</button><button data-v="realize">Realization</button></span>
 </div>
 <div class="vhelp" id="viewHelp"></div>
 <div class="bar">
  <span class="lbl">Domain</span><span class="ctl" id="fDomain"><button data-v="" class="on">All</button><button data-v="ai">AI</button><button data-v="quantum">Quantum</button><button data-v="ai+quantum">AI+Q</button><button data-v="semiconductor">Semi</button><button data-v="compute">Compute</button></span>
  <input id="q" placeholder="search jurisdiction / program&hellip;">
  <button class="dl" id="dl">Download CSV</button>
 </div>
 <details class="morefilters"><summary>More filters &amp; currency basis</summary>
  <div class="bar" style="margin-top:10px">
   <span class="lbl" title="PPP is a sensitivity scenario, not the default">Currency</span><span class="ctl" id="fBasis"><button data-v="fx" class="on">Market FX</button><button data-v="ppp">PPP-blended</button></span>
   <span class="lbl">Actor</span><span class="ctl" id="fActor"><button data-v="" class="on">All</button><button data-v="outlay">Public outlay</button><button data-v="private">Private / mobilized</button><button data-v="state_fund">State fund</button><button data-v="sovereign_wealth">Sovereign wealth</button></span>
   <span class="lbl">Realization</span><span class="ctl" id="fTrack"><button data-v="" class="on">All</button><button data-v="1">Tracked only</button></span>
  </div>
 </details>
 <div class="tbl-scroll"><table id="tbl"><thead id="thead"></thead><tbody id="tb"></tbody></table></div>
</div>
<div class="foot">Self-contained (no external libraries). Generated by build.py from data/government-commitments.jsonl + data/denominators.json. Methodology: methodology.md. All figures as-reported; many are unverified mobilization targets; PPP &amp; GBARD views are approximate scenarios.</div>
</div>
<script>
const D={data},DEN={denom};
let fBasis="fx",fView="abs",fDom="",fAct="",fTrack="",fGroup="",q="",sortK="announced",sortDir=-1;
const collapsed=new Set();  // jurisdictions collapsed in group-by view
const esc=s=>String(s==null?"":s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const usd=n=>{{if(n==null)return null;const a=Math.abs(n);
  if(a>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(a>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+Math.round(n).toLocaleString()}};
const na='<span style="color:#b0b5c0">n/a</span>';
const cell=v=>v==null?na:v;
const actorTag=t=>{{const pub=['government_appropriated','government_outlay'],priv=['private','mobilization_target'];
  const cls=pub.includes(t)?'t-public':priv.includes(t)?'t-private':'t-other';
  return '<span class="tag '+cls+'">'+t.replace(/_/g,' ')+'</span>'}};
const horizon=r=>{{if(r.horizon_start_year&&r.horizon_end_year)return r.horizon_start_year+'-'+r.horizon_end_year;
  if(r.horizon_start_year)return r.horizon_start_year+'+';return'open'}};
const paceTag=p=>p?'<span class="tag p-'+p+'">'+p.replace(/_/g,' ')+'</span>':'';
const tracked=r=>!!(r.realization_history&&r.realization_history.length);
// Recent-announcements timeline: parse announced (YYYY-MM-DD | YYYY-MM | YYYY) to a UTC ms stamp
function parseAnn(s){{if(!s)return null;const p=String(s).split('-');const y=+p[0],m=(+p[1]||1)-1,d=+p[2]||1;
  return y?Date.UTC(y,m,d):null}}
function recentItem(x){{const r=x.r;
  const prog=r.source_url?'<a href="'+esc(r.source_url)+'" target="_blank" rel="noopener">'+esc(r.program)+'</a>':esc(r.program);
  return '<div class="ritem"><span class="rd">'+esc(r.announced)+'</span><span>'+esc(r.jurisdiction)
    +' &middot; '+prog+' &middot; '+(usd(r.usd_fx)||'n/a')+' '+actorTag(r.actor_type)+'</span></div>'}}
function renderRecent(){{
  const n=new Date(),today=Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate());
  const items=D.map(r=>{{const t=parseAnn(r.announced);return t==null?null:{{r,ago:Math.floor((today-t)/864e5)}}}})
    .filter(x=>x&&x.ago>=0).sort((a,c)=>a.ago-c.ago);
  const w7=items.filter(x=>x.ago<=7),w30=items.filter(x=>x.ago<=30);
  const set=(id,n)=>{{const e=document.getElementById(id);e.textContent=n;e.classList.toggle('zero',n===0)}};
  set('r7n',w7.length);set('r30n',w30.length);
  document.getElementById('r7').innerHTML=w7.length?w7.map(recentItem).join(''):'<div class="rempty">No announcements in the last 7 days.</div>';
  document.getElementById('r30').innerHTML=w30.length?w30.map(recentItem).join(''):'<div class="rempty">No announcements in the last 30 days.</div>';
  document.getElementById('recentAsOf').textContent='as of '+new Date(today).toISOString().slice(0,10);
}}
// basis amount: FX vs PPP-blended (tradable share at FX, rest at PPP)
function amt(r){{if(fBasis==='fx')return r.usd_fx;
  const ts=r.tradable_share_resolved;return ts*r.usd_fx+(1-ts)*r.usd_ppp}}
function annual(r){{const a=amt(r);if(r.annualized_usd==null)return null;return a*(r.annualized_usd/r.usd_fx)}}
// the normalized metric shown in the second numeric column, per fView
function norm(r){{const den=DEN[r.iso3]||{{}};const A=amt(r),AN=annual(r);
  if(fView==='abs')return AN; // annualized stock
  if(fView==='pc')return den.population?A/den.population:null;
  if(fView==='gdp')return den.gdp_usd?( (AN!=null?AN:A)/den.gdp_usd*100):null;
  if(fView==='gbard')return den.gbard_usd?((AN!=null?AN:A)/den.gbard_usd):null;
  if(fView==='realize')return r.realization_rate; // null sorts last
  return AN}}
function realizeFmt(r){{
  if(!tracked(r))return na;
  const rr=r.realization_rate,ps=r.pace_status;
  let pct=rr==null?'<span class="bn">no $ figure</span>':'<b>'+(rr*100).toFixed(0)+'%</b>';
  let meta=[];if(r.realized_basis)meta.push(r.realized_basis);if(r.realized_as_of)meta.push('as of '+r.realized_as_of);
  const ms=meta.length?' <span class="bn">'+esc(meta.join(' · '))+'</span>':'';
  return pct+(ps?' '+paceTag(ps):'')+ms}}
function normFmt(r){{if(fView==='realize')return realizeFmt(r);
  const v=norm(r);if(v==null)return na;
  if(fView==='pc')return'$'+(v>=1e6?(v/1e6).toFixed(1)+'M':v>=1e3?(v/1e3).toFixed(0)+'k':v.toFixed(0))+'/cap';
  if(fView==='gdp')return v.toFixed(v<1?3:2)+'% GDP';
  if(fView==='gbard')return v.toFixed(v<1?2:1)+'×';
  return usd(v)}}
function sortVal(r){{if(sortK==='_amount')return amt(r);if(sortK==='_norm')return norm(r);
  let v=r[sortK];return v==null?-Infinity:v}}
function match(r){{
  if(fDom&&r.domain!==fDom)return false;
  if(fAct==='outlay'&&!['government_appropriated','government_outlay'].includes(r.actor_type))return false;
  if(fAct&&fAct!=='outlay'&&r.actor_type!==fAct)return false;
  if(fTrack&&!tracked(r))return false;
  if(q&&!(r.jurisdiction+' '+r.program+' '+r.iso3).toLowerCase().includes(q))return false;
  return true}}
function rows(){{return D.filter(match).sort((a,c)=>{{let x=sortVal(a),y=sortVal(c);
  if(typeof x==='string')return sortDir*x.localeCompare(y);
  if(x==null)x=-Infinity;if(y==null)y=-Infinity;return sortDir*(x-y)}})}}
function rowHtml(r,child){{
  const src=r.source_url?'<a href="'+esc(r.source_url)+'" target="_blank" rel="noopener">'+esc(r.source_name)+'</a>':esc(r.source_name);
  const cls=child?(' class="child"'+(collapsed.has(child)?' style="display:none"':'')):'';
  return '<tr'+cls+' title="'+esc(r.notes||'')+'">'
   +'<td class="l">'+esc(r.jurisdiction)+'</td>'
   +'<td class="l">'+esc(r.program)+'</td>'
   +'<td>'+esc(r.domain)+'</td>'
   +'<td class="hl">'+cell(usd(amt(r)))+'</td>'
   +'<td>'+normFmt(r)+'</td>'
   +'<td>'+cell(usd(r.public_outlay_usd))+'</td>'
   +'<td>'+cell(usd(r.private_mobilized_usd))+'</td>'
   +'<td>'+Math.round(r.tradable_share_resolved*100)+'%</td>'
   +'<td class="l">'+actorTag(r.actor_type)+'</td>'
   +'<td>'+esc(r.announced)+'</td>'
   +'<td>'+horizon(r)+'</td>'
   +'<td class="c-'+esc(r.confidence)+'">'+esc(r.confidence)+'</td>'
   +'<td class="l">'+src+(r.verification_status!=='verified'?' <span style="color:#b0b5c0">('+esc(r.verification_status)+')</span>':'')+'</td>'
   +'</tr>';
}}
// jurisdiction parent summary — respects the cardinal rule (dedup public outlay only; headlines NOT summed)
function groupSummary(rs){{const seen=new Set();let outlay=0;
  rs.forEach(r=>{{if(['government_appropriated','government_outlay'].includes(r.actor_type)&&!seen.has(r.event_key)){{seen.add(r.event_key);outlay+=r.public_outlay_usd||0}}}});
  const domains=[...new Set(rs.map(r=>r.domain))].sort();
  const latest=rs.map(r=>r.announced).filter(Boolean).sort().slice(-1)[0]||'';
  return {{count:rs.length,outlay,domains,latest}};
}}
function groupHeader(j,rs){{const s=groupSummary(rs),open=!collapsed.has(j);
  return '<tr class="grp" data-jur="'+esc(j)+'">'
   +'<td class="l"><span class="tw">'+(open?'▾':'▸')+'</span> <b>'+esc(j)+'</b> <span class="bn">('+s.count+')</span></td>'
   +'<td class="l bn">'+s.count+' announcement'+(s.count>1?'s':'')+'</td>'
   +'<td class="bn">'+esc(s.domains.join(', '))+'</td>'
   +'<td class="bn">not summed</td><td></td>'
   +'<td class="hl">'+(usd(s.outlay)||na)+'</td>'
   +'<td></td><td></td><td></td>'
   +'<td>'+esc(s.latest)+'</td><td></td><td></td><td></td>'
   +'</tr>';
}}
// plain-English description of the current Measure + basis (the clarity line under the controls)
function updateHelper(){{
  const basis=fBasis==='fx'?'market FX':'PPP-blended (a sensitivity scenario)';
  let m;
  if(fGroup==='rollup')
    m='<b>Roll-up:</b> one row per jurisdiction, showing appropriated <b>public outlay only</b> (deduplicated by event &mdash; headlines are never summed). The value column follows the Measure toggle.';
  else
    m=({{abs:'<b>Absolute $:</b> the headline commitment in USD.',
        pc:'<b>Per capita:</b> committed USD &divide; population.',
        gdp:'<b>% of GDP:</b> annualized commitment as a share of GDP (national effort).',
        gbard:'<b>&times; R&amp;D budget:</b> annualized commitment vs the annual government R&amp;D budget (GBARD).',
        realize:'<b>Realization:</b> how much of each pledge has actually been realized vs a linear-schedule expectation.'}})[fView]
      +' Currency basis: '+basis+'.';
  document.getElementById('viewHelp').innerHTML=m;
}}
function detailHead(){{
  const amt='Headline ('+(fBasis==='fx'?'FX':'PPP')+')';
  const norm=({{abs:'Annualized',pc:'Per-capita',gdp:'% of GDP',gbard:'× ann. GBARD',realize:'Realized vs commit'}})[fView];
  return '<tr><th class="l" data-k="jurisdiction">Jurisdiction</th><th class="l" data-k="program">Program</th>'
   +'<th data-k="domain">Domain</th><th data-k="_amount">'+amt+'</th><th data-k="_norm">'+norm+'</th>'
   +'<th data-k="public_outlay_usd">Public</th><th data-k="private_mobilized_usd">Private/mob.</th>'
   +'<th data-k="tradable_share_resolved">Trad.%</th><th class="l" data-k="actor_type">Type</th>'
   +'<th data-k="announced">Announced</th><th data-k="horizon_end_year">Horizon</th>'
   +'<th data-k="confidence">Conf.</th><th class="l" data-k="source_name">Source</th></tr>';
}}
function rollupHead(){{
  const vl=({{abs:'Public outlay',pc:'Outlay / capita',gdp:'Outlay % GDP',gbard:'Outlay × GBARD',realize:'Public outlay'}})[fView];
  return '<tr><th class="l" data-k="_jur">Jurisdiction</th><th data-k="_count">Announcements</th>'
   +'<th data-k="_val">'+vl+'</th><th class="l" data-k="_domains">Domains</th>'
   +'<th data-k="_verified">Verified</th><th data-k="_latest">Latest</th></tr>';
}}
// aggregate filtered rows to one object per jurisdiction (iso3); reuses the cardinal-rule groupSummary
function jurAgg(rs){{const g={{}};
  rs.forEach(r=>{{(g[r.iso3]=g[r.iso3]||{{iso3:r.iso3,jur:r.jurisdiction,recs:[]}}).recs.push(r)}});
  return Object.values(g).map(o=>{{const s=groupSummary(o.recs);
    o.count=s.count;o.outlay=s.outlay;o.domains=s.domains;o.latest=s.latest;
    o.verified=o.recs.filter(r=>r.verification_status==='verified').length;o.den=DEN[o.iso3]||{{}};return o}});
}}
function rollupVal(o){{
  if(fView==='pc')return o.den.population?o.outlay/o.den.population:null;
  if(fView==='gdp')return o.den.gdp_usd?o.outlay/o.den.gdp_usd*100:null;
  if(fView==='gbard')return o.den.gbard_usd?o.outlay/o.den.gbard_usd:null;
  return o.outlay}}
function rollupValFmt(o){{const v=rollupVal(o);
  if(fView==='pc')return v==null?na:'$'+(v>=1e3?(v/1e3).toFixed(1)+'k':v.toFixed(0))+'/cap';
  if(fView==='gdp')return v==null?na:v.toFixed(v<1?3:2)+'%';
  if(fView==='gbard')return v==null?na:v.toFixed(2)+'×';
  return usd(o.outlay)||'$0'}}
function rollupRow(o){{return '<tr title="'+o.count+' announcement'+(o.count>1?'s':'')+', '+esc(o.iso3)+'">'
   +'<td class="l">'+esc(o.jur)+'</td><td>'+o.count+'</td><td class="hl">'+rollupValFmt(o)+'</td>'
   +'<td class="l">'+esc(o.domains.join(', '))+'</td><td>'+o.verified+'</td><td>'+esc(o.latest||'')+'</td></tr>'}}
function aggSortVal(o){{
  if(sortK==='_jur')return o.jur;if(sortK==='_count')return o.count;
  if(sortK==='_val'){{const v=rollupVal(o);return v==null?-Infinity:v}}
  if(sortK==='_domains')return o.domains.length;if(sortK==='_verified')return o.verified;
  if(sortK==='_latest')return o.latest||'';return o.outlay}}
function render(){{
  updateHelper();
  document.getElementById('thead').innerHTML=fGroup==='rollup'?rollupHead():detailHead();
  const rs=rows();let html;
  if(fGroup==='rollup'){{
    html=jurAgg(rs).sort((a,c)=>{{let x=aggSortVal(a),y=aggSortVal(c);
      if(typeof x==='string')return sortDir*x.localeCompare(y);
      if(x==null)x=-Infinity;if(y==null)y=-Infinity;return sortDir*(x-y)}}).map(rollupRow).join('');
  }} else if(fGroup==='group'){{
    const g={{}};rs.forEach(r=>{{(g[r.jurisdiction]=g[r.jurisdiction]||[]).push(r)}});
    const order=Object.keys(g).sort((a,b)=>groupSummary(g[b]).latest.localeCompare(groupSummary(g[a]).latest));
    html=order.map(j=>groupHeader(j,g[j])+g[j].map(r=>rowHtml(r,j)).join('')).join('');
  }} else html=rs.map(r=>rowHtml(r,null)).join('');
  document.getElementById('tb').innerHTML=html;
}}
function wire(id,set){{document.getElementById(id).onclick=e=>{{if(e.target.tagName!=='BUTTON')return;
  set(e.target.dataset.v);[...e.currentTarget.children].forEach(c=>c.classList.toggle('on',c===e.target));render()}}}}
wire('fBasis',v=>fBasis=v);wire('fView',v=>fView=v);wire('fDomain',v=>fDom=v);wire('fActor',v=>fAct=v);wire('fTrack',v=>fTrack=v);
// switching arrange mode resets the sort to a sensible default for that mode
wire('fGroup',v=>{{fGroup=v;if(v==='rollup'){{sortK='_val';sortDir=-1}}else{{sortK='announced';sortDir=-1}}}});
document.getElementById('q').oninput=e=>{{q=e.target.value.toLowerCase().trim();render()}};
renderRecent();
// collapse/expand a jurisdiction group
document.getElementById('tb').addEventListener('click',e=>{{const tr=e.target.closest('tr.grp');if(!tr)return;
  const j=tr.dataset.jur;collapsed.has(j)?collapsed.delete(j):collapsed.add(j);render()}});
// delegated sort — survives the dynamic <thead> rebuild on every render
document.getElementById('thead').addEventListener('click',e=>{{const th=e.target.closest('th');
  if(!th||!th.dataset.k)return;const k=th.dataset.k;if(sortK===k)sortDir*=-1;else{{sortK=k;sortDir=-1}}render()}});
document.getElementById('dl').onclick=()=>{{
  const cols=['id','jurisdiction','iso3','program','domain','headline_amount','currency','usd_approx',
    'annualized_usd','tradable_share_resolved','usd_fx','usd_ppp','public_outlay_usd','private_mobilized_usd',
    'actor_type','announced','horizon_start_year','horizon_end_year','verification_status','confidence',
    'realized_usd','realized_as_of','realized_basis','realization_rate','expected_rate','pace_status',
    'source_name','source_url','event_key','notes'];
  const qq=v=>v==null?'':/[",\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':String(v);
  const csv=[cols.join(',')].concat(rows().map(r=>cols.map(c=>qq(r[c])).join(','))).join('\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));
  a.download='ai-quantum-ledger.csv';a.click()}};
render();
</script></body></html>
"""


def _ci_bar(r, n):
    if r["ci_low"] is None or not n:
        return '<span class="bn">n/a</span>'
    lo, hi, pt = r["ci_low"], r["ci_high"], r["rank"]
    left = (lo - 1) / n * 100
    width = max((hi - lo + 1) / n * 100, 2.5)
    mk = (pt - 1) / n * 100
    return ('<div class="cibar"><div class="cispan" style="left:{:.1f}%;width:{:.1f}%"></div>'
            '<div class="cimk" style="left:{:.1f}%"></div></div> '
            '<span class="cit">{}&ndash;{}</span>').format(left, width, mk, lo, hi)


def build_index_html(rows, summary, weights, errors):
    inds = weights["indicators"]
    meta = weights.get("_meta", {})
    n = summary["n_ranked"]
    head_cells = "".join(
        '<th title="{}">{}</th>'.format(html.escape(i.get("desc", "")),
                                        html.escape(i["label"].split(" (")[0]))
        for i in inds)
    body = []
    for r in rows:
        ncells = []
        for i in inds:
            v = r["norms"].get(i["key"])
            ncells.append("<td>{}</td>".format(
                '<span class="bn">n/a</span>' if v is None else "{:.0f}".format(v)))
        cov_cls = "" if r["coverage"] == r["k"] else ' class="cov"'
        body.append(
            "<tr>"
            '<td class="rk">{rank}</td>'
            '<td class="ci">{ci}</td>'
            '<td class="l">{name}</td>'
            '<td class="hl">{comp}</td>'
            "{ncells}"
            '<td{covc}>{cov}/{k}</td>'
            '<td>{nrec}</td>'
            '<td class="l dom">{dom}</td>'
            "</tr>".format(
                rank=r["rank"] if r["rank"] else "n/a", ci=_ci_bar(r, n),
                name=html.escape(r["name"]),
                comp="{:.1f}".format(r["composite"]) if r["composite"] is not None else "n/a",
                ncells="".join(ncells), covc=cov_cls, cov=r["coverage"], k=r["k"],
                nrec=r["n_records"], dom=html.escape(", ".join(r["domains"]))))
    wrows = "".join(
        '<tr><td class="l">{}</td><td class="hl">{:.0%}</td><td class="l">{}</td></tr>'.format(
            html.escape(i["label"]), i["weight"], html.escape(i.get("desc", "")))
        for i in inds)
    return TEMPLATE_INDEX.format(
        warning=html.escape(meta.get("warning", "")),
        design=html.escape(meta.get("deliberate_design_note", "")),
        n_ranked=n, n_ind=summary["n_indicators"], draws=summary["draws"],
        seed=summary["seed"], head_cells=head_cells, rows="".join(body),
        weights_rows=wrows,
        norm=html.escape(meta.get("normalization", "")),
        agg=html.escape(meta.get("aggregation", "")),
        unc=html.escape(meta.get("uncertainty", "")),
        data=json.dumps(rows, separators=(",", ":")),
        errnote=("" if not errors else
                 '<div class="note err"><b>Validation warnings:</b> '
                 + html.escape("; ".join(errors)) + "</div>"),
    )


TEMPLATE_INDEX = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI/Quantum Investment Composite Index (PROVISIONAL)</title>
<style>
:root{{--ink:#262236;--ink2:#3c3950;--mut:#7a7989;--faint:#9b9aa8;--line:#e9eaf0;--line2:#eef0f4;--card:#ffffff;--accent:#ef4e5b;--r:14px;--r-sm:9px;--gap:18px;--mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;--sans:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--sans);color:var(--ink2);line-height:1.5;background:linear-gradient(180deg,#fafbfc 0%,#f3f4f7 40%,#f1f2f6 100%);background-attachment:fixed;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
.wrap{{max-width:1380px;margin:0 auto;padding:34px 26px 44px}}
.masthead{{margin-bottom:22px}}
.eyebrow{{font-size:11px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--faint)}}
.masthead h1{{font-size:30px;line-height:1.12;font-weight:700;letter-spacing:-.02em;color:var(--ink);margin-top:10px}}
.masthead .lede{{font-size:14px;line-height:1.6;color:var(--mut);margin-top:12px;max-width:96ch}}
.masthead .lede b{{color:var(--ink2);font-weight:600}}
.xlink{{display:inline-flex;align-items:center;gap:7px;margin-top:16px;font-size:13px;font-weight:600;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:8px 16px;text-decoration:none;box-shadow:0 1px 2px rgba(30,30,60,.05)}}
.xlink:hover{{border-color:#d4d6e2}}.xlink .arr{{color:var(--accent);font-size:14px}}
.warn{{background:linear-gradient(180deg,#fdeef0,#fce9ec);color:#a3303c;border:1px solid #f3ccd2;border-radius:var(--r-sm);padding:14px 18px;margin-bottom:var(--gap);font-size:12.5px;line-height:1.58}}
.warn b{{text-transform:uppercase;letter-spacing:.1em;font-size:11px;color:#b6333f}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:var(--gap)}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:15px 17px;box-shadow:0 1px 2px rgba(30,30,60,.04),0 12px 28px -20px rgba(30,30,60,.14)}}
.kpi .l{{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.12em;font-weight:600;line-height:1.3}}
.kpi .v{{font-family:var(--mono);font-size:24px;font-weight:600;color:var(--ink);margin-top:8px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:22px 24px;box-shadow:0 1px 2px rgba(30,30,60,.04),0 18px 44px -30px rgba(30,30,60,.18);margin-bottom:var(--gap)}}
.card h2{{font-size:14px;font-weight:700;color:var(--ink);margin-bottom:10px;letter-spacing:-.01em}}
.note{{font-size:12.5px;color:var(--ink2);background:#fafbfc;border:1px solid var(--line);border-radius:var(--r-sm);padding:12px 15px;margin-bottom:var(--gap);line-height:1.6}}
.note b{{color:var(--ink)}}
.note.err{{background:#fdeef0;border-color:#f3ccd2;color:#a3303c}}
.dl{{background:var(--ink);color:#fff;border:0;padding:8px 16px;border-radius:8px;font-size:12.5px;font-weight:600;cursor:pointer;font-family:var(--sans)}}
.dl:hover{{background:#1b1830}}
.ci{{min-width:190px}}
.cibar{{position:relative;display:inline-block;width:118px;height:7px;background:#eceef3;border-radius:4px;vertical-align:middle;margin-right:8px}}
.cispan{{position:absolute;top:0;height:7px;background:#c4ccef;border-radius:4px}}
.cimk{{position:absolute;top:-3px;width:3px;height:13px;background:var(--ink);border-radius:2px}}
.cit{{font-size:11px;color:var(--mut);font-family:var(--mono);font-variant-numeric:tabular-nums}}
.bn{{color:#a9a8b6;font-size:11px;font-family:var(--sans)}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
.foot{{font-size:11.5px;color:var(--faint);text-align:center;padding:18px 10px 4px;line-height:1.6;max-width:96ch;margin:0 auto}}
td.rk{{font-family:var(--mono);font-weight:700;font-size:15px;color:var(--ink)}}
td.cov{{color:#9a6a16;font-weight:600;font-family:var(--mono)}}
td.dom{{white-space:normal;color:var(--mut);font-size:11px;font-family:var(--sans)}}
th.dom{{white-space:normal;font-size:11px;font-weight:600}}
.tbl-scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:10px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:6px 11px;text-align:right;border-bottom:1px solid var(--line2);white-space:nowrap;vertical-align:middle}}
th:first-child,td:first-child,th.l,td.l{{text-align:left;white-space:normal}}
th{{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#c8c9d6;cursor:default;background:var(--ink);font-weight:600;padding-top:9px;padding-bottom:9px}}
th.l,th:first-child{{color:#c8c9d6}}
td{{font-variant-numeric:tabular-nums}}
td:not(.l):not(.dom):not(.ci){{font-family:var(--mono);font-size:11.5px;color:var(--ink2)}}
td.l{{color:var(--ink2)}}td.l:first-child,td.hl{{color:var(--ink)}}
td.hl{{font-family:var(--mono);font-weight:700}}
tbody tr:nth-child(even) td{{background:#fafbfd}}
tbody tr:hover td{{background:#eef1f9}}
</style></head><body>
<div class="wrap">
<header class="masthead">
 <div class="eyebrow">Stage 4 &middot; Provisional layer over the ledger</div>
 <h1>AI / Quantum Investment Composite Index</h1>
 <p class="lede">An OECD/JRC-style composite over the <a href="index.html">raw ledger</a> &mdash; fixed transparent weights, geometric aggregation, missing data as n/a (never imputed), and an independent Monte-Carlo audit publishing <b>90% rank confidence intervals</b>. Never a point rank without its interval. &middot; <a href="methodology.md">methodology</a></p>
 <a class="xlink" href="index.html"><span class="arr">&larr;</span> Back to the ledger</a>
</header>
<div class="warn"><b>Do not cite these ranks.</b> {warning}</div>
{errnote}
<div class="kpis">
 <div class="kpi"><div class="l">Jurisdictions ranked</div><div class="v">{n_ranked}</div></div>
 <div class="kpi"><div class="l">Indicators</div><div class="v">{n_ind}</div></div>
 <div class="kpi"><div class="l">Monte-Carlo draws</div><div class="v">{draws}</div></div>
 <div class="kpi"><div class="l">Seed (reproducible)</div><div class="v">{seed}</div></div>
</div>
<div class="card">
 <div class="bar" style="display:flex;align-items:center;margin-bottom:10px">
  <h2 style="margin:0">Ranking &mdash; point rank with 90% confidence interval</h2>
  <button class="dl" id="dl" style="margin-left:auto">Download CSV</button>
 </div>
 <div class="tbl-scroll"><table id="tbl"><thead><tr>
  <th>Rank</th><th>90% rank CI</th><th class="l">Jurisdiction</th><th>Composite</th>
  {head_cells}<th>Cov.</th><th>Recs</th><th class="l dom">Domains</th>
 </tr></thead><tbody>{rows}</tbody></table></div>
 <div class="note" style="margin-top:12px">The wide intervals are the point: at this coverage the data cannot distinguish most jurisdictions. <b>Composite</b> is a 1&ndash;100-scaled weighted geometric mean; <b>Cov.</b> is how many indicators the score is built on (amber = a core indicator is n/a and was not imputed). Indicator columns are the 1&ndash;100 normalized values. Hover an indicator header for its definition.</div>
</div>
<div class="card"><h2>Weighting scheme (fixed &amp; transparent)</h2>
 <table><thead><tr><th class="l">Indicator</th><th>Weight</th><th class="l">Definition</th></tr></thead>
 <tbody>{weights_rows}</tbody></table>
 <div class="note" style="margin-top:12px"><b>Normalization.</b> {norm}<br><b>Aggregation.</b> {agg}<br><b>Uncertainty.</b> {unc}</div>
 <div class="note"><b>By design:</b> {design}</div>
</div>
<div class="foot">Self-contained, generated by build.py from the ledger + data/index-weights.json. The ledger is the product; this index is a deliberately later, provisional layer over it.</div>
</div>
<script>
const ROWS={data};
document.getElementById('dl').onclick=()=>{{
  const inds=ROWS.length?Object.keys(ROWS[0].norms):[];
  const cols=['rank','ci_low','ci_med','ci_high','iso3','name','composite','coverage','k','n_records']
    .concat(inds.map(k=>'norm_'+k)).concat(['domains']);
  const val=(r,c)=>c.startsWith('norm_')?r.norms[c.slice(5)]:c==='domains'?r.domains.join('; '):r[c];
  const qq=v=>v==null?'':/[",\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':String(v);
  const csv=[cols.join(',')].concat(ROWS.map(r=>cols.map(c=>qq(val(r,c))).join(','))).join('\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));
  a.download='ai-quantum-composite-index.csv';a.click()}};
</script></body></html>
"""


# ---------------------------------------------------------------------------
# Power Index (redesign) — live binding of the derivable dimensions
# ---------------------------------------------------------------------------
# The redesigned viewer (power-index.html) ranks jurisdictions across 11
# AI/Quantum dimensions. Three are derivable from this ledger; the rest stay
# illustrative placeholders in the page. The Power Index is a BENCHMARKING lens
# (distinct from the cardinal-rule composite index, which stays appropriated-
# outlay-only). Here the live dims measure best-available COMMITTED CAPITAL BY
# ORIGIN so every jurisdiction is comparable, including state-capital players
# (China, Saudi, UAE) whose money is not appropriated budget outlay:
#   - per record, the explicit public/private split wins when present;
#   - otherwise usd_approx is bucketed by actor origin (government/state vs
#     private/mobilized);
#   - deduplicated by event_key; estimate/unconfirmed tiers excluded (drops the
#     overlapping China guidance-fund estimate and other modeled figures).
# AI pillar includes "compute" (Stargate et al.); "semiconductor" is excluded
# (fab-adjacent). The separate ai_compute *capacity* dimension is untouched.
POWER_AI_DOMAINS = {"ai", "ai+quantum", "compute"}
POWER_Q_DOMAINS = {"quantum", "ai+quantum"}
POWER_LIVE_DIMS = ["ai_public", "ai_private", "q_public"]
POWER_GOV_ORIGIN = {"government_appropriated", "government_outlay", "state_fund",
                    "sovereign_wealth", "public_private"}
POWER_PRIV_ORIGIN = {"private", "mobilization_target"}
POWER_BENCH_EXCLUDE = {"estimate", "unconfirmed"}  # benchmark on credibly-reported commitments
# iso3 -> 2-letter short code (tiles / compare headers)
POWER_SH = {"USA": "US", "EU": "EU", "FRA": "FR", "SAU": "SA", "ARE": "AE",
            "CHN": "CN", "CAN": "CA", "GBR": "UK", "IND": "IN", "DEU": "DE",
            "KOR": "KR", "SGP": "SG", "AUS": "AU", "ISR": "IL", "JPN": "JP",
            "TWN": "TW", "KAZ": "KZ"}
# iso3 -> (col,row) on the 7-column tile cartogram (roughly geographic, west→east)
POWER_TILES = {"CAN": (1, 1), "USA": (1, 2), "GBR": (3, 1), "FRA": (3, 2),
               "EU": (4, 1), "DEU": (4, 2), "ARE": (4, 3), "ISR": (5, 1),
               "SAU": (5, 2), "CHN": (6, 1), "IND": (6, 2), "SGP": (6, 3),
               "KOR": (7, 1), "AUS": (7, 2), "JPN": (7, 3), "TWN": (5, 3),
               "KAZ": (5, 4)}


def _power_contribution(r, value_usd):
    """Full per-record provenance for the drill-down card, with the bucketed amount."""
    return {"program": r["program"], "domain": r["domain"],
            "amount_b": round(value_usd / 1e9, 3), "actor_type": r["actor_type"],
            "source_name": r["source_name"], "source_url": r.get("source_url"),
            "source_tier": r.get("source_tier"), "announced": r["announced"],
            "verification": r["verification_status"], "id": r["id"]}


def _power_capital(rs, domains):
    """Best-available committed capital for a jurisdiction's records in `domains`,
    split into (public/state, private/mobilized), deduplicated by event_key, with
    estimate/unconfirmed tiers excluded. The explicit public_outlay/private split wins
    per record; otherwise usd_approx is bucketed by actor origin. Returns
    (pub_usd, priv_usd, {pub:[contrib], priv:[contrib]}) — the contribution lists are
    exactly the records that compose each total (one per event_key, the max), sorted
    by amount desc, each carrying full provenance for the drill-down card."""
    pub, priv = {}, {}      # event_key -> (value, contribution dict)
    for r in rs:
        if r["domain"] not in domains:
            continue
        if r.get("verification_status") in POWER_BENCH_EXCLUDE:
            continue
        ek, act = r["event_key"], r["actor_type"]
        po, pm = r.get("public_outlay_usd"), r.get("private_mobilized_usd")
        if po is None and pm is None:
            # no explicit split → assign the whole headline to one bucket by origin
            pub_c = r["usd_approx"] if act in POWER_GOV_ORIGIN else 0
            priv_c = r["usd_approx"] if act in POWER_PRIV_ORIGIN else 0
        else:
            # respect the explicit split; never also claim the headline
            pub_c, priv_c = po or 0, pm or 0
        if pub_c > pub.get(ek, (0, None))[0]:
            pub[ek] = (pub_c, _power_contribution(r, pub_c))
        if priv_c > priv.get(ek, (0, None))[0]:
            priv[ek] = (priv_c, _power_contribution(r, priv_c))
    def _list(bucket):
        return sorted((c for v, c in bucket.values() if v > 0),
                      key=lambda c: c["amount_b"], reverse=True)
    contribs = {"pub": _list(pub), "priv": _list(priv)}
    return sum(v for v, _ in pub.values()), sum(v for v, _ in priv.values()), contribs


def _power_jurisdictions(denom):
    """Full display set for the viewer, from the normalization denominators —
    iso, name, 2-letter code, population (M), GDP ($T), and tile coordinates."""
    J = []
    for iso, d in denom.items():
        col, row = POWER_TILES.get(iso, (1, 1))
        J.append({"iso": iso, "name": d.get("name", iso),
                  "sh": POWER_SH.get(iso, iso[:2]),
                  "popM": round((d.get("population") or 0) / 1e6, 1),
                  "gdpT": round((d.get("gdp_usd") or 0) / 1e12, 2),
                  "col": col, "row": row})
    # stable, roughly geographic order (by tile row then column) for nice defaults
    J.sort(key=lambda j: (j["row"], j["col"]))
    return J


def build_power_index_data(recs, denom, generated):
    """Live values (in $B) for the three derivable Power-Index dimensions plus the
    full jurisdiction set, keyed by iso3, with per-dim provenance and contributing
    programs. Shape matches power-index.html's buildData() overlay."""
    isos = sorted({r["iso3"] for r in recs} | set(denom.keys()))
    values, programs, contributions = {}, {}, {}
    for iso in isos:
        rs = [r for r in recs if r["iso3"] == iso]
        aip, aiv, ai_c = _power_capital(rs, POWER_AI_DOMAINS)
        qp, _, q_c = _power_capital(rs, POWER_Q_DOMAINS)
        values[iso] = {"ai_public": round(aip / 1e9, 3),
                       "ai_private": round(aiv / 1e9, 3),
                       "q_public": round(qp / 1e9, 3)}
        # the records that compose each live total (full provenance for the drill-down card)
        contributions[iso] = {"ai_public": ai_c["pub"], "ai_private": ai_c["priv"],
                              "q_public": q_c["pub"]}
        # one-line program-name summary for the hover chip — derived from the same lists
        programs[iso] = {dim: [c["program"] for c in contributions[iso][dim]][:4]
                         for dim in POWER_LIVE_DIMS}
    sources = {
        "ai_public": {"name": "Ledger — committed public / state AI capital", "date": generated},
        "ai_private": {"name": "Ledger — committed private / mobilized AI capital", "date": generated},
        "q_public": {"name": "Ledger — committed public / state quantum capital", "date": generated},
    }
    return {"generated": generated, "live_dims": POWER_LIVE_DIMS,
            "J": _power_jurisdictions(denom),
            "values": values, "sources": sources, "programs": programs,
            "contributions": contributions,
            "note": ("Live dims = best-available committed capital by origin ($B), "
                     "deduplicated by event_key, estimate/unconfirmed tiers excluded. "
                     "Other dimensions in the viewer are illustrative placeholders.")}


def write_power_index_data(data):
    """Inject `data` into power-index.html's marked LEDGER_DATA block (the page
    template is hand-authored; only this block is generated). Returns True on write."""
    if not os.path.exists(POWER_OUT):
        print("  (power-index.html not found — skipped live binding)")
        return False
    with open(POWER_OUT, encoding="utf-8") as fh:
        src = fh.read()
    i, k = src.find(POWER_MARK_START), src.find(POWER_MARK_END)
    if i < 0 or k < 0 or k < i:
        print("  (power-index.html missing LEDGER_DATA markers — skipped)")
        return False
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    block = f"{POWER_MARK_START}\nconst LEDGER_DATA = {payload};\n{POWER_MARK_END}"
    new = src[:i] + block + src[k + len(POWER_MARK_END):]
    if new != src:
        with open(POWER_OUT, "w", encoding="utf-8") as fh:
            fh.write(new)
    return True


def main():
    denom = load_denominators()
    recs, errors = load_records(denom)
    series, rerrors = load_realizations()
    errors += rerrors
    # warn on realization observations that don't match any ledger event_key
    event_keys = {r["event_key"] for r in recs}
    for ek in series:
        if ek not in event_keys:
            errors.append(f"realizations: event_key '{ek}' has no matching ledger record")
    attach_realizations(recs, series)
    agg = aggregates(recs)
    ragg = realization_aggregates(recs)
    if errors:
        print("VALIDATION WARNINGS:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(build_html(recs, denom, agg, ragg, errors))
    # Stage 4: provisional composite index (separate page over the same ledger)
    weights = load_weights()
    rows, summary = build_index_rows(recs, denom, weights)
    with open(INDEX_OUT, "w", encoding="utf-8") as fh:
        fh.write(build_index_html(rows, summary, weights, errors))
    # Redesign: bind the three derivable dimensions into power-index.html
    generated = datetime.date.today().isoformat()
    pdata = build_power_index_data(recs, denom, generated)
    wrote_power = write_power_index_data(pdata)
    print(f"Wrote {OUT}")
    print(f"  {agg['records']} records / {agg['jurisdictions']} jurisdictions / "
          f"{agg['verified']} verified / {len(denom)} denominators")
    print(f"  appropriated public outlays (FX, dedup): ${agg['outlay_sum']/1e9:.1f}B")
    print(f"  realization: {ragg['tracked']} pledges tracked / {ragg['behind']} behind-or-stalled")
    print(f"Wrote {INDEX_OUT}")
    top = rows[0] if rows else None
    if top:
        print(f"  composite index (PROVISIONAL): {summary['n_ranked']} jurisdictions ranked, "
              f"{summary['draws']} MC draws; #1 {top['name']} "
              f"(rank CI {top['ci_low']}-{top['ci_high']})")
    if wrote_power:
        nz = sum(1 for v in pdata["values"].values()
                 if any(v[d] for d in POWER_LIVE_DIMS))
        print(f"Wrote {POWER_OUT}")
        print(f"  power-index live dims: {', '.join(POWER_LIVE_DIMS)} "
              f"({nz} jurisdictions with a non-zero live value; generated {generated})")


if __name__ == "__main__":
    main()
