#!/usr/bin/env python3
"""Build the AI/Quantum Investment Ledger viewer.

Self-contained: all paths are relative to this script's folder, so the project
folder can be hosted independently (GitHub Pages / Netlify / any static host).

Stage 1: source-linked, tagged, downloadable ledger of government commitments.
Stage 2: normalization layer — per-capita / per-GDP / per-GBARD views joined on
         iso3, plus a tradable/non-tradable FX-vs-PPP currency split.

Reads data/government-commitments.jsonl + data/denominators.json, validates each
record, computes derived fields, and bakes a self-contained, dependency-free
index.html with live view + currency-basis toggles.

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

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "government-commitments.jsonl")
DENOM = os.path.join(HERE, "data", "denominators.json")
OUT = os.path.join(HERE, "index.html")

REQUIRED = ["id", "jurisdiction", "iso3", "program", "domain", "currency",
            "usd_approx", "announced", "actor_type", "verification_status",
            "confidence", "source_name", "event_key"]
ACTOR_TYPES = {"government_appropriated", "government_outlay", "state_fund",
               "sovereign_wealth", "mobilization_target", "public_private", "private"}
OUTLAY_ACTORS = {"government_appropriated", "government_outlay"}
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


def b(n):
    if n is None:
        return "n/a"
    a = abs(n)
    if a >= 1e9:
        return f"${n/1e9:.1f}B"
    if a >= 1e6:
        return f"${n/1e6:.0f}M"
    return f"${n:,.0f}"


def build_html(recs, denom, agg, errors):
    recs_sorted = sorted(recs, key=lambda r: r["usd_approx"], reverse=True)
    return TEMPLATE.format(
        data=json.dumps(recs_sorted, separators=(",", ":")),
        denom=json.dumps(denom, separators=(",", ":")),
        n_records=agg["records"], n_juris=agg["jurisdictions"],
        outlay=b(agg["outlay_sum"]), headline=b(agg["headline_sum"]),
        n_verified=agg["verified"],
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
a{{color:#1f4ea8;text-decoration:none}}a:hover{{text-decoration:underline}}
.foot{{font-size:11.5px;color:var(--mut);text-align:center;padding:10px}}
</style></head><body>
<div class="wrap">
<div class="head"><h1>AI/Quantum Investment Ledger</h1>
<p>A source-linked, downloadable ledger of national AI/quantum investment commitments, with per-capita / %GDP / %GBARD views and an FX-vs-PPP currency split. Each figure is tagged commitment-vs-outlay, public-vs-mobilized, horizon, and confidence &mdash; <b>before</b> any comparison. The ledger is the product; the index is a later layer.</p></div>
{errnote}
<div class="note"><b>How to read this &mdash; headline figures are NOT additive.</b> Most large headlines (Stargate, InvestAI, France) are private/mobilized capital or multi-year targets, not government outlays. The only defensible sum is <b>appropriated public outlays</b> (below). <b>PPP-blended</b> applies market FX to the tradable share (compute/hardware) and PPP to the rest (talent/ops) &mdash; a sensitivity scenario, not truth. Normalization denominators (GDP/pop accurate; price-levels &amp; GBARD approximate) are flagged for later pinning. Partial seed (target: &ge;40 jurisdictions).</div>
<div class="kpis">
 <div class="kpi"><div class="l">Records</div><div class="v">{n_records}</div><div class="s">across {n_juris} jurisdictions</div></div>
 <div class="kpi"><div class="l">Appropriated public outlays</div><div class="v">{outlay}</div><div class="s">genuine budget outlays, dedup by event (FX)</div></div>
 <div class="kpi"><div class="l">Sum of headlines</div><div class="v">{headline}</div><div class="s">NOT additive &mdash; scale only</div></div>
 <div class="kpi"><div class="l">Primary-source verified</div><div class="v">{n_verified}</div><div class="s">traced to a budget / official doc</div></div>
</div>
<div class="card">
 <div class="bar">
  <span class="lbl">Currency</span><span class="ctl" id="fBasis"><button data-v="fx" class="on">Market FX</button><button data-v="ppp">PPP-blended</button></span>
  <span class="lbl">View</span><span class="ctl" id="fView"><button data-v="abs" class="on">Absolute</button><button data-v="pc">Per-capita</button><button data-v="gdp">% of GDP</button><button data-v="gbard">&times; GBARD</button></span>
 </div>
 <div class="bar">
  <span class="ctl" id="fDomain"><button data-v="" class="on">All domains</button><button data-v="ai">AI</button><button data-v="quantum">Quantum</button><button data-v="ai+quantum">AI+Q</button><button data-v="semiconductor">Semi</button><button data-v="compute">Compute</button></span>
  <span class="ctl" id="fActor"><button data-v="" class="on">All actors</button><button data-v="outlay">Public outlay</button><button data-v="private">Private/mob.</button><button data-v="state_fund">State fund</button><button data-v="sovereign_wealth">SWF</button></span>
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
let fBasis="fx",fView="abs",fDom="",fAct="",q="",sortK="_amount",sortDir=-1;
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
  return AN}}
function normFmt(r){{const v=norm(r);if(v==null)return na;
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
  if(q&&!(r.jurisdiction+' '+r.program+' '+r.iso3).toLowerCase().includes(q))return false;
  return true}}
function rows(){{return D.filter(match).sort((a,c)=>{{let x=sortVal(a),y=sortVal(c);
  if(typeof x==='string')return sortDir*x.localeCompare(y);
  if(x==null)x=-Infinity;if(y==null)y=-Infinity;return sortDir*(x-y)}})}}
function render(){{
  document.getElementById('hAmt').textContent='Headline ('+(fBasis==='fx'?'FX':'PPP')+')';
  document.getElementById('hNorm').textContent=
    ({{abs:'Annualized',pc:'Per-capita',gdp:'% of GDP',gbard:'× ann. GBARD'}})[fView];
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
wire('fBasis',v=>fBasis=v);wire('fView',v=>fView=v);wire('fDomain',v=>fDom=v);wire('fActor',v=>fAct=v);
document.getElementById('q').oninput=e=>{{q=e.target.value.toLowerCase().trim();render()}};
document.querySelectorAll('#tbl thead th').forEach(th=>th.onclick=()=>{{
  const k=th.dataset.k;if(!k)return;if(sortK===k)sortDir*=-1;else{{sortK=k;sortDir=-1}}render()}});
document.getElementById('dl').onclick=()=>{{
  const cols=['id','jurisdiction','iso3','program','domain','headline_amount','currency','usd_approx',
    'annualized_usd','tradable_share_resolved','usd_fx','usd_ppp','public_outlay_usd','private_mobilized_usd',
    'actor_type','announced','horizon_start_year','horizon_end_year','verification_status','confidence',
    'source_name','source_url','event_key','notes'];
  const qq=v=>v==null?'':/[",\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':String(v);
  const csv=[cols.join(',')].concat(rows().map(r=>cols.map(c=>qq(r[c])).join(','))).join('\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));
  a.download='ai-quantum-ledger.csv';a.click()}};
render();
</script></body></html>
"""


def main():
    denom = load_denominators()
    recs, errors = load_records(denom)
    agg = aggregates(recs)
    if errors:
        print("VALIDATION WARNINGS:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(build_html(recs, denom, agg, errors))
    print(f"Wrote {OUT}")
    print(f"  {agg['records']} records / {agg['jurisdictions']} jurisdictions / "
          f"{agg['verified']} verified / {len(denom)} denominators")
    print(f"  appropriated public outlays (FX, dedup): ${agg['outlay_sum']/1e9:.1f}B")


if __name__ == "__main__":
    main()
