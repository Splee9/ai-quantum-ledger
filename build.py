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

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "government-commitments.jsonl")
DENOM = os.path.join(HERE, "data", "denominators.json")
REAL = os.path.join(HERE, "data", "realizations.jsonl")
WEIGHTS = os.path.join(HERE, "data", "index-weights.json")
OUT = os.path.join(HERE, "index.html")
INDEX_OUT = os.path.join(HERE, "composite-index.html")

REQUIRED = ["id", "jurisdiction", "iso3", "program", "domain", "currency",
            "usd_approx", "announced", "actor_type", "verification_status",
            "confidence", "source_name", "event_key"]
ACTOR_TYPES = {"government_appropriated", "government_outlay", "state_fund",
               "sovereign_wealth", "mobilization_target", "public_private", "private"}
OUTLAY_ACTORS = {"government_appropriated", "government_outlay"}
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
:root{{--head:#16213e;--txt:#1a1f36;--mut:#6b7280;--r:10px;--gap:16px}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#eef1f6;color:var(--txt);line-height:1.5}}
.wrap{{max-width:1360px;margin:0 auto;padding:var(--gap)}}
.head{{background:var(--head);color:#fff;padding:22px 26px;border-radius:var(--r);margin-bottom:var(--gap)}}
.head h1{{font-size:21px;font-weight:700}}.head p{{font-size:13px;color:#9fb3d1;margin-top:4px;max-width:980px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:var(--gap);margin-bottom:var(--gap)}}
.kpi{{background:#fff;border-radius:var(--r);padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.kpi .l{{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}}
.kpi .v{{font-size:23px;font-weight:700;margin-top:4px}}.kpi .s{{font-size:12px;color:var(--mut);margin-top:2px}}
.card{{background:#fff;border-radius:var(--r);padding:18px 22px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:var(--gap)}}
.note{{font-size:12px;color:var(--mut);background:#fffbe6;border:1px solid #ffe58f;border-radius:8px;padding:10px 12px;margin-bottom:var(--gap)}}
.note.err{{background:#fff1f0;border-color:#ffa39e}}
details.note summary{{cursor:pointer;color:var(--txt)}}
details.note summary .more{{color:var(--mut);font-weight:400}}
details.note[open] summary{{margin-bottom:6px}}
details.note .d{{font-size:12px;line-height:1.55}}
.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);margin:0 6px 0 2px}}
.ctl{{display:inline-flex;background:#e7ecf5;border-radius:8px;padding:3px;margin:0 10px 8px 0;flex-wrap:wrap}}
.ctl button{{border:0;background:transparent;padding:6px 12px;border-radius:6px;font-size:12.5px;font-weight:600;color:#3a4a6b;cursor:pointer}}
.ctl button.on{{background:var(--head);color:#fff}}
.bar{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:8px}}
.bar input{{padding:6px 10px;border:1px solid #d7deea;border-radius:7px;font-size:13px;min-width:170px}}
.dl{{margin-left:auto;background:#16213e;color:#fff;border:0;padding:7px 14px;border-radius:7px;font-size:12.5px;font-weight:600;cursor:pointer}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid #eef0f4;white-space:nowrap}}
th:first-child,td:first-child,th.l,td.l{{text-align:left;white-space:normal}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut);cursor:pointer;user-select:none;position:sticky;top:0;background:#fff}}
td.hl{{font-weight:700}}
tr:hover td{{background:#f7f9fc}}
.tag{{display:inline-block;font-size:10.5px;font-weight:600;padding:1px 7px;border-radius:10px;border:1px solid}}
.t-public{{color:#1d6f42;border-color:#9bd5b1;background:#eaf7ef}}
.t-private{{color:#8a5a00;border-color:#ffd591;background:#fff7e6}}
.t-other{{color:#3a4a6b;border-color:#c3cee0;background:#eef2f9}}
.c-high{{color:#1d6f42;font-weight:600}}.c-medium{{color:#8a5a00}}.c-low{{color:#a8071a}}
.p-ahead{{color:#1d6f42;border-color:#9bd5b1;background:#eaf7ef}}
.p-on_track{{color:#1f4ea8;border-color:#aac4ee;background:#eef2fb}}
.p-behind{{color:#8a5a00;border-color:#ffd591;background:#fff7e6}}
.p-stalled{{color:#a8071a;border-color:#ffa39e;background:#fff1f0}}
.bn{{color:#9aa0ac;font-size:10px}}
a{{color:#1f4ea8;text-decoration:none}}a:hover{{text-decoration:underline}}
.foot{{font-size:11.5px;color:var(--mut);text-align:center;padding:10px}}
</style></head><body>
<div class="wrap">
<div class="head"><h1>AI/Quantum Investment Ledger</h1>
<p>A source-linked, downloadable ledger of national AI/quantum investment commitments, with per-capita / %GDP / %GBARD views and an FX-vs-PPP currency split. Each figure is tagged commitment-vs-outlay, public-vs-mobilized, horizon, and confidence &mdash; <b>before</b> any comparison. The ledger is the product; the index is a later layer. <a href="composite-index.html" style="color:#9fd0ff">&rarr; Provisional composite index (Stage 4)</a></p></div>
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
<div class="card">
 <div class="bar">
  <span class="lbl">Currency</span><span class="ctl" id="fBasis"><button data-v="fx" class="on">Market FX</button><button data-v="ppp">PPP-blended</button></span>
  <span class="lbl">View</span><span class="ctl" id="fView"><button data-v="abs" class="on">Absolute</button><button data-v="pc">Per-capita</button><button data-v="gdp">% of GDP</button><button data-v="gbard">&times; GBARD</button><button data-v="realize">Realization</button></span>
 </div>
 <div class="bar">
  <span class="ctl" id="fDomain"><button data-v="" class="on">All domains</button><button data-v="ai">AI</button><button data-v="quantum">Quantum</button><button data-v="ai+quantum">AI+Q</button><button data-v="semiconductor">Semi</button><button data-v="compute">Compute</button></span>
  <span class="ctl" id="fActor"><button data-v="" class="on">All actors</button><button data-v="outlay">Public outlay</button><button data-v="private">Private/mob.</button><button data-v="state_fund">State fund</button><button data-v="sovereign_wealth">SWF</button></span>
  <span class="lbl">Realization</span><span class="ctl" id="fTrack"><button data-v="" class="on">All</button><button data-v="1">Tracked only</button></span>
  <input id="q" placeholder="filter jurisdiction / program...">
  <button class="dl" id="dl">Download CSV</button>
 </div>
 <div style="overflow-x:auto;max-height:68vh"><table id="tbl"><thead><tr>
  <th class="l" data-k="jurisdiction">Jurisdiction</th>
  <th class="l" data-k="program">Program</th>
  <th data-k="domain">Domain</th>
  <th data-k="_amount" id="hAmt">Headline (FX)</th>
  <th data-k="_norm" id="hNorm">Annualized</th>
  <th data-k="public_outlay_usd">Public</th>
  <th data-k="private_mobilized_usd">Private/mob.</th>
  <th data-k="tradable_share_resolved">Trad.%</th>
  <th class="l" data-k="actor_type">Type</th>
  <th data-k="announced">Announced</th>
  <th data-k="horizon_end_year">Horizon</th>
  <th data-k="confidence">Conf.</th>
  <th class="l" data-k="source_name">Source</th>
 </tr></thead><tbody id="tb"></tbody></table></div>
</div>
<div class="foot">Self-contained (no external libraries). Generated by build.py from data/government-commitments.jsonl + data/denominators.json. Methodology: methodology.md. All figures as-reported; many are unverified mobilization targets; PPP &amp; GBARD views are approximate scenarios.</div>
</div>
<script>
const D={data},DEN={denom};
let fBasis="fx",fView="abs",fDom="",fAct="",fTrack="",q="",sortK="_amount",sortDir=-1;
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
function render(){{
  document.getElementById('hAmt').textContent='Headline ('+(fBasis==='fx'?'FX':'PPP')+')';
  document.getElementById('hNorm').textContent=
    ({{abs:'Annualized',pc:'Per-capita',gdp:'% of GDP',gbard:'× ann. GBARD',realize:'Realized vs commit'}})[fView];
  document.getElementById('tb').innerHTML=rows().map(r=>{{
    const src=r.source_url?'<a href="'+esc(r.source_url)+'" target="_blank" rel="noopener">'+esc(r.source_name)+'</a>':esc(r.source_name);
    return '<tr title="'+esc(r.notes||'')+'">'
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
     +'</tr>'}}).join('');
}}
function wire(id,set){{document.getElementById(id).onclick=e=>{{if(e.target.tagName!=='BUTTON')return;
  set(e.target.dataset.v);[...e.currentTarget.children].forEach(c=>c.classList.toggle('on',c===e.target));render()}}}}
wire('fBasis',v=>fBasis=v);wire('fView',v=>fView=v);wire('fDomain',v=>fDom=v);wire('fActor',v=>fAct=v);wire('fTrack',v=>fTrack=v);
document.getElementById('q').oninput=e=>{{q=e.target.value.toLowerCase().trim();render()}};
document.querySelectorAll('#tbl thead th').forEach(th=>th.onclick=()=>{{
  const k=th.dataset.k;if(!k)return;if(sortK===k)sortDir*=-1;else{{sortK=k;sortDir=-1}}render()}});
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
:root{{--head:#16213e;--txt:#1a1f36;--mut:#6b7280;--r:10px;--gap:16px}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#eef1f6;color:var(--txt);line-height:1.5}}
.wrap{{max-width:1360px;margin:0 auto;padding:var(--gap)}}
.head{{background:var(--head);color:#fff;padding:22px 26px;border-radius:var(--r);margin-bottom:var(--gap)}}
.head h1{{font-size:21px;font-weight:700}}.head p{{font-size:13px;color:#9fb3d1;margin-top:4px;max-width:1040px}}
.head a{{color:#9fd0ff}}
.warn{{background:#a8071a;color:#fff;border-radius:var(--r);padding:14px 18px;margin-bottom:var(--gap);font-size:13px}}
.warn b{{text-transform:uppercase;letter-spacing:.5px;font-size:11.5px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--gap);margin-bottom:var(--gap)}}
.kpi{{background:#fff;border-radius:var(--r);padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.kpi .l{{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}}
.kpi .v{{font-size:22px;font-weight:700;margin-top:3px}}
.card{{background:#fff;border-radius:var(--r);padding:18px 22px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:var(--gap)}}
.card h2{{font-size:14px;margin-bottom:10px}}
.note{{font-size:12px;color:var(--mut);background:#fffbe6;border:1px solid #ffe58f;border-radius:8px;padding:10px 12px;margin-bottom:var(--gap)}}
.note.err{{background:#fff1f0;border-color:#ffa39e}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid #eef0f4;white-space:nowrap;vertical-align:middle}}
th:first-child,td:first-child,th.l,td.l{{text-align:left}}
td.dom,th.dom{{white-space:normal;color:var(--mut);font-size:11px}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut)}}
td.rk{{font-weight:700;font-size:15px}}td.hl{{font-weight:700}}
td.cov{{color:#8a5a00;font-weight:600}}
tr:hover td{{background:#f7f9fc}}
.ci{{min-width:180px}}
.cibar{{position:relative;display:inline-block;width:120px;height:8px;background:#e7ecf5;border-radius:4px;vertical-align:middle;margin-right:6px}}
.cispan{{position:absolute;top:0;height:8px;background:#aac4ee;border-radius:4px}}
.cimk{{position:absolute;top:-2px;width:3px;height:12px;background:#16213e;border-radius:2px}}
.cit{{font-size:11px;color:var(--mut)}}
.bn{{color:#9aa0ac;font-size:11px}}
.dl{{background:#16213e;color:#fff;border:0;padding:7px 14px;border-radius:7px;font-size:12.5px;font-weight:600;cursor:pointer}}
.foot{{font-size:11.5px;color:var(--mut);text-align:center;padding:10px}}
a{{color:#1f4ea8;text-decoration:none}}a:hover{{text-decoration:underline}}
</style></head><body>
<div class="wrap">
<div class="head"><h1>AI/Quantum Investment Composite Index <span style="font-weight:400;color:#ff9a8b">— PROVISIONAL</span></h1>
<p>An OECD/JRC-style composite over the <a href="index.html">raw ledger</a> &mdash; fixed transparent weights, geometric aggregation, missing data as n/a (never imputed), and an independent Monte-Carlo audit publishing <b>90% rank confidence intervals</b>. <b>Never a point rank without its interval.</b> <a href="index.html">&larr; Back to the ledger</a> &middot; <a href="methodology.md">methodology</a></p></div>
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
 <div style="overflow-x:auto"><table id="tbl"><thead><tr>
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


if __name__ == "__main__":
    main()
