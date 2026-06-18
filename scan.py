#!/usr/bin/env python3
"""Daily headline scanner for the AI/Quantum Investment Ledger.

The left-hand side of the ingestion pipeline (see INGESTION.md): discover recent
AI/quantum government-investment headlines, extract structured candidate records
with Claude, and hand them to the reviewed write-path (`ingest.py`).

    headlines  --[discover: Google News RSS]-->  headlines.jsonl
    headlines  --[extract: Claude]------------>  candidates.jsonl
    candidates --[ingest.py add]-------------->  data/ingest-queue.jsonl  (review)

Two stages, independently runnable:

    python3 scan.py discover [--days 2] [--out headlines.jsonl]
        Stage 1 only. Stdlib + network, NO API key. Google News RSS search.

    python3 scan.py extract --headlines headlines.jsonl [--out candidates.jsonl]
                            [--model claude-opus-4-8]
        Stage 2 only. Needs the `anthropic` SDK and ANTHROPIC_API_KEY.

    python3 scan.py run [--days 2] [--add] [--model ...]
        Stage 1 + 2. With --add, pipes candidates into `ingest.py add` (review queue).

UNLIKE build.py / ingest.py this tool is NOT stdlib-only or offline: it needs the
network (discovery) and the Anthropic API (extraction). It writes only candidate
files and the review queue — never the canonical ledger directly. A human still
reviews the queue and runs `ingest.py promote` + `build.py`.

Model: defaults to claude-opus-4-8. For a high-volume daily run, pass
`--model claude-sonnet-4-6` to trade some accuracy for lower cost.
"""
import argparse
import json
import os
import subprocess
import sys
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(HERE, "data", "schema.json")
DEFAULT_MODEL = os.environ.get("LEDGER_SCAN_MODEL", "claude-opus-4-8")
MAX_HEADLINES = 60  # cap a SINGLE extraction call so the response fits max_tokens;
                    # comprehensive sweeps are chunked into batches of this size.
DEFAULT_MIN_TIER = 2  # the fidelity gate — drop candidates whose source_tier is worse

# Search queries for the discovery stage — aims for COMPLETE coverage of AI & quantum
# announcements involving a country/bloc (see data/schema.json#_collection_scope), public
# AND private. The extraction stage filters out the irrelevant ones and tiers each source.
QUERIES = [
    # --- public / government AI ---
    "national AI strategy government investment",
    "government artificial intelligence investment billion",
    "AI infrastructure public investment announcement",
    "sovereign AI compute fund",
    "government AI supercomputer data center funding",
    "public AI research institute funding launch",
    "AI act funding budget allocation",
    "ministry artificial intelligence program budget",
    # --- private / mobilized AI involving a nation ---
    "national AI champion private investment pledge",
    "AI data center investment country billion",
    "sovereign wealth fund AI investment",
    "AI summit investment pledge mobilization",
    # --- quantum (public + private) ---
    "quantum technology government funding",
    "quantum computing national program funding",
    "national quantum strategy initiative billion",
    "quantum research center government investment",
    "quantum private investment national program",
    # --- enabling compute / semiconductor ---
    "semiconductor subsidy government billion",
    "chips act government semiconductor funding",
    "GPU compute cluster national investment",
]

# Optional international reach: Google News editions (hl, gl, ceid) to sweep beyond the
# US/English surface. Enabled with `--international`; the default run uses US-en only.
EDITIONS = [
    ("en-US", "US", "US:en"),   # default
    ("en-GB", "GB", "GB:en"),
    ("en-IN", "IN", "IN:en"),
    ("fr",    "FR", "FR:fr"),
    ("de",    "DE", "DE:de"),
    ("ja",    "JP", "JP:ja"),
    ("ko",    "KR", "KR:ko"),
    ("zh-CN", "CN", "CN:zh-Hans"),
]

# ---------------------------------------------------------------------------
# Stage 1 — discovery (Google News RSS; stdlib only, no API key)
# ---------------------------------------------------------------------------
def _rss_url(query, edition=("en-US", "US", "US:en")):
    q = urllib.parse.quote(query)
    hl, gl, ceid = edition
    return (f"https://news.google.com/rss/search?q={q}"
            f"&hl={hl}&gl={gl}&ceid={urllib.parse.quote(ceid)}")


def _ssl_context():
    """Verify TLS using certifi's CA bundle when available (it ships with the
    anthropic SDK), else the system default. Never disables verification."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def parse_rss(xml_bytes):
    """Parse a Google News RSS payload into a list of headline dicts."""
    out = []
    root = ET.fromstring(xml_bytes)
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if title and link:
            out.append({"title": title, "link": link, "published": pub, "source": source})
    return out


def _within_days(published, days, now):
    if not published:
        return True  # keep undated items; extraction can still judge them
    try:
        dt = parsedate_to_datetime(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return dt >= now - timedelta(days=days)


def discover(days=2, queries=QUERIES, editions=None):
    """Pull recent headlines across all queries (and editions), deduped by link."""
    editions = editions or [EDITIONS[0]]
    now = datetime.now(timezone.utc)
    ctx = _ssl_context()
    seen, headlines = set(), []
    for edition in editions:
        for q in queries:
            try:
                req = urllib.request.Request(_rss_url(q, edition), headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                    items = parse_rss(r.read())
            except Exception as e:  # network/parse errors per query shouldn't kill the run
                print(f"  warn: query '{q}' [{edition[1]}] failed: {e}", file=sys.stderr)
                continue
            for h in items:
                key = h["link"]
                if key in seen or not _within_days(h["published"], days, now):
                    continue
                seen.add(key)
                h["query"] = q
                h["edition"] = edition[1]
                headlines.append(h)
    return headlines


# ---------------------------------------------------------------------------
# Stage 2 — extraction (Claude, via the official anthropic SDK)
# ---------------------------------------------------------------------------
# JSON schema for structured output. Every property is required; optional fields
# use nullable types (mirrors data/schema.json). additionalProperties:false is
# required by the structured-outputs feature.
_REC = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "stable slug country-program-year, e.g. jp-ai-strategy-2025"},
        "jurisdiction": {"type": "string"},
        "iso3": {"type": "string", "description": "ISO-3166 alpha-3, or 'EU' for the bloc"},
        "program": {"type": "string"},
        "domain": {"type": "string", "enum": ["ai", "quantum", "ai+quantum", "semiconductor", "compute"]},
        "currency": {"type": "string", "description": "ISO 4217 of the headline figure"},
        "usd_approx": {"type": "number", "description": "headline converted to USD (full units)"},
        "headline_amount": {"type": ["number", "null"], "description": "figure in original currency units"},
        "announced": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM"},
        "actor_type": {"type": "string", "enum": ["government_appropriated", "government_outlay", "state_fund",
                                                  "sovereign_wealth", "mobilization_target", "public_private", "private"]},
        "public_outlay_usd": {"type": ["number", "null"]},
        "private_mobilized_usd": {"type": ["number", "null"]},
        "horizon_start_year": {"type": ["integer", "null"]},
        "horizon_end_year": {"type": ["integer", "null"]},
        "verification_status": {"type": "string", "enum": ["verified", "reported", "estimate", "unconfirmed"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "source_name": {"type": "string"},
        "source_url": {"type": ["string", "null"]},
        "source_tier": {"type": "integer", "enum": [1, 2, 3, 4],
                        "description": "fidelity of the cited outlet: 1 primary/official, 2 major secondary "
                                       "(wire services, papers of record, established research trackers), "
                                       "3 trade/regional/aggregator, 4 low (PR wire, social, blog)"},
        "event_key": {"type": "string", "description": "stable key grouping re-announcements of the SAME money"},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["id", "jurisdiction", "iso3", "program", "domain", "currency", "usd_approx",
                 "headline_amount", "announced", "actor_type", "public_outlay_usd", "private_mobilized_usd",
                 "horizon_start_year", "horizon_end_year", "verification_status", "confidence",
                 "source_name", "source_url", "source_tier", "event_key", "notes"],
}
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"candidates": {"type": "array", "items": _REC}},
    "required": ["candidates"],
}

SYSTEM = """You extract structured records for an all-time ledger of AI and quantum \
INVESTMENT COMMITMENTS that INVOLVE A COUNTRY OR BLOC, one row per announcement.

You are given recent news headlines. Emit ONE candidate record for each headline that \
describes a *new* commitment that is BOTH (a) about AI, quantum, ai+quantum, AI-enabling \
compute, or AI-relevant semiconductor capacity, AND (b) involves a national jurisdiction — \
either a government / government-adjacent commitment, OR a private / mobilization commitment \
framed around a country (national AI champions, sovereign-AI data centers, summit pledges). \
Collect BOTH public and private money. Skip everything else (pure company product launches, \
opinion / market-size pieces, private funding rounds with no national framing, duplicates).

Hard rules (this is a credibility-first ledger):
- NEVER sum headline figures. Keep public and private money in SEPARATE fields \
  (public_outlay_usd vs private_mobilized_usd). Big "mobilization" headlines (private \
  capital, multi-year targets) are actor_type 'mobilization_target' or 'private', with \
  the genuine public portion (if any) in public_outlay_usd.
- source_tier (FIDELITY of the cited outlet — judge it, this drives the collection gate):
    1 = primary/official (government budget docs, ministry/.gov/European-Commission releases,
        legislative appropriations, official program pages; for private, the official company
        newsroom or a primary filing);
    2 = major established secondary (Reuters, AP, Bloomberg, Financial Times, WSJ, NYT, Nikkei,
        The Economist; established research trackers: OECD.AI, Stanford HAI, McKinsey, WIPO,
        Epoch AI, CSIS);
    3 = trade press / regional outlet / news aggregator (TechCrunch, The Register, smaller
        regional press, a bare Google-News surface with no named outlet of record);
    4 = low fidelity (PR-wire distribution, social posts, anonymous blogs, content farms).
  Assign the tier of the ACTUAL outlet in 'source'. When the outlet is unknown or clearly a
  blog/PR wire, use 3 or 4. Prefer the underlying primary source's tier if the headline \
  clearly cites an official release. Do NOT inflate tiers — the downstream gate keeps only <= 2.
- verification_status: use 'reported' (credible press) or 'unconfirmed'. NEVER 'verified' \
  or 'estimate' — a human assigns those after tracing a primary source.
- confidence: 'low' or 'medium' for headline-derived rows. Prefer 'low' when unsure.
- id: a stable slug 'country-program-year' (lowercase, hyphenated), unique per announcement.
- event_key: a stable slug for the underlying money, shared across re-announcements of the \
  SAME commitment (so totals can dedupe).
- usd_approx: best-effort USD conversion of the headline (full units, not millions). Set \
  currency to the original ISO-4217 code. If you cannot estimate a figure, do not invent \
  one — skip the headline instead.
- source_url: the article link provided. source_name: the outlet.
- Leave any field you cannot determine as null (where the schema allows) rather than guessing.
- announced: the announcement date (YYYY-MM-DD or YYYY-MM), not the article date if they differ.

Return ONLY the structured object. An empty candidates array is correct when nothing qualifies."""


def build_user_content(headlines):
    lines = ["Recent headlines (title | source | date | url):"]
    for h in headlines[:MAX_HEADLINES]:
        lines.append(f"- {h.get('title','')} | {h.get('source','')} | "
                     f"{h.get('published','')} | {h.get('link','')}")
    lines.append("\nEmit candidate records for the qualifying government AI/quantum "
                 "investment announcements only.")
    return "\n".join(lines)


def _extract_batch(client, headlines, model):
    """One extraction API call over <= MAX_HEADLINES headlines."""
    resp = client.messages.create(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user_content(headlines)}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), None)
    return json.loads(text).get("candidates", []) if text else []


def extract(headlines, model=DEFAULT_MODEL):
    """Call Claude to extract candidate records, chunked into MAX_HEADLINES batches
    so a comprehensive sweep doesn't overflow a single response. Returns a list of dicts."""
    if not headlines:
        return []
    try:
        import anthropic
    except ImportError:
        raise SystemExit("extract needs the Anthropic SDK: pip install anthropic")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit("extract needs ANTHROPIC_API_KEY (or an `ant auth login` profile).")
    client = anthropic.Anthropic()
    cands = []
    batches = [headlines[i:i + MAX_HEADLINES] for i in range(0, len(headlines), MAX_HEADLINES)]
    for n, batch in enumerate(batches, 1):
        if len(batches) > 1:
            print(f"  extract batch {n}/{len(batches)} ({len(batch)} headlines)…", file=sys.stderr)
        cands.extend(_extract_batch(client, batch, model))
    return cands


def apply_tier_gate(cands, min_tier=DEFAULT_MIN_TIER):
    """Split candidates on the source-fidelity gate. Returns (kept, dropped) where
    kept have source_tier <= min_tier (a missing tier is treated as failing the gate)."""
    kept, dropped = [], []
    for c in cands:
        t = c.get("source_tier")
        (kept if isinstance(t, int) and t <= min_tier else dropped).append(c)
    return kept, dropped


# ---------------------------------------------------------------------------
# IO helpers + commands
# ---------------------------------------------------------------------------
def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _editions_for(args):
    return EDITIONS if getattr(args, "international", False) else [EDITIONS[0]]


def cmd_discover(args):
    hs = discover(days=args.days, editions=_editions_for(args))
    _write_jsonl(args.out, hs)
    scope = "international" if args.international else "US-en"
    print(f"discover: {len(hs)} headlines -> {os.path.relpath(args.out, HERE)} "
          f"(last {args.days}d, {scope}, {len(QUERIES)} queries)")
    return 0


def cmd_extract(args):
    headlines = _read_jsonl(args.headlines)
    cands = extract(headlines, model=args.model)
    kept, dropped = apply_tier_gate(cands, min_tier=args.min_tier)
    _write_jsonl(args.out, kept)
    print(f"extract: {len(kept)} candidate(s) kept (tier<={args.min_tier}), {len(dropped)} dropped "
          f"below the gate, from {len(headlines)} headlines -> {os.path.relpath(args.out, HERE)} "
          f"(model {args.model})")
    return 0


def cmd_run(args):
    hs = discover(days=args.days, editions=_editions_for(args))
    scope = "international" if args.international else "US-en"
    print(f"run: discovered {len(hs)} headlines (last {args.days}d, {scope})")
    cands = extract(hs, model=args.model)
    kept, dropped = apply_tier_gate(cands, min_tier=args.min_tier)
    _write_jsonl(args.out, kept)
    print(f"run: extracted {len(cands)} candidate(s); kept {len(kept)} at tier<={args.min_tier}, "
          f"dropped {len(dropped)} below the gate -> {os.path.relpath(args.out, HERE)}")
    if args.add and kept:
        print("run: handing tier-gated candidates to ingest.py add (review queue)...")
        return subprocess.call([sys.executable, os.path.join(HERE, "ingest.py"), "add", args.out])
    if args.add:
        print("run: nothing to add.")
    return 0


def main(argv):
    p = argparse.ArgumentParser(description="AI/Quantum ledger headline scanner")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="Stage 1: Google News RSS -> headlines.jsonl (no API key)")
    d.add_argument("--days", type=int, default=2)
    d.add_argument("--out", default=os.path.join(HERE, "headlines.jsonl"))
    d.add_argument("--international", action="store_true",
                   help="sweep all Google News editions (global reach), not just US-en")
    d.set_defaults(func=cmd_discover)

    e = sub.add_parser("extract", help="Stage 2: Claude -> candidates.jsonl (needs API key)")
    e.add_argument("--headlines", required=True)
    e.add_argument("--out", default=os.path.join(HERE, "candidates.jsonl"))
    e.add_argument("--model", default=DEFAULT_MODEL)
    e.add_argument("--min-tier", type=int, default=DEFAULT_MIN_TIER, dest="min_tier",
                   help="source-fidelity gate: keep candidates with source_tier <= this (default 2)")
    e.set_defaults(func=cmd_extract)

    r = sub.add_parser("run", help="Stage 1 + 2 (+ optional ingest)")
    r.add_argument("--days", type=int, default=2)
    r.add_argument("--out", default=os.path.join(HERE, "candidates.jsonl"))
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--international", action="store_true",
                   help="sweep all Google News editions (global reach), not just US-en")
    r.add_argument("--min-tier", type=int, default=DEFAULT_MIN_TIER, dest="min_tier",
                   help="source-fidelity gate: keep candidates with source_tier <= this (default 2)")
    r.add_argument("--add", action="store_true", help="pipe candidates into ingest.py add")
    r.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
