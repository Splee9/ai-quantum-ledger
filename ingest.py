#!/usr/bin/env python3
"""Ingestion write-path for the AI/Quantum Investment Ledger.

The deterministic, reviewable core that a daily headline-scanning job calls AFTER
it has extracted structured candidate records. This script does NOT scan the web
or call an LLM — it only validates, deduplicates, and appends. Keeping the write
path dumb and auditable is the point: the scanner proposes, a human (or a gated
job) disposes, and every accepted row is one `git diff` away from review.

Pipeline (see INGESTION.md for the full contract):

    headlines --[scanner + LLM extraction, EXTERNAL]--> candidates.jsonl
    candidates.jsonl --[ingest.py add]--> data/ingest-queue.jsonl   (staging)
    <human review of the queue>
    data/ingest-queue.jsonl --[ingest.py promote]--> data/government-commitments.jsonl
    python3 build.py  &&  git commit

Commands:
    python3 ingest.py validate <file>        # dry-run: validate only, no write
    python3 ingest.py add <file>             # validate + dedup -> append to the REVIEW QUEUE
    python3 ingest.py add <file> --to-ledger # append straight to the ledger (vetted rows only)
    python3 ingest.py list                   # show the review queue
    python3 ingest.py promote [id ...]       # move queue rows (all, or by id) into the ledger

<file> may be JSONL (one record per line) or a JSON array. Records must follow
data/schema.json. Stdlib only; reuses build.py's field contract.
"""
import json
import os
import sys

import build  # reuse the canonical field contract (REQUIRED, ACTOR_TYPES) + paths

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = build.DATA                                   # data/government-commitments.jsonl
QUEUE = os.path.join(HERE, "data", "ingest-queue.jsonl")

# Enum contract — mirrors data/schema.json (the authoritative contract)
DOMAINS = {"ai", "quantum", "ai+quantum", "semiconductor", "compute"}
VERIFICATION = {"verified", "reported", "estimate", "unconfirmed"}
CONFIDENCE = {"high", "medium", "low"}
# A scanner must never self-certify a row as primary-source verified.
AUTO_FORBIDDEN_STATUS = {"verified"}


def read_candidates(path):
    """Accept either a JSON array or JSONL (one object per line)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text:
        return []
    if text[0] == "[":
        return json.loads(text)
    out = []
    for ln, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path} line {ln}: bad JSON ({e})")
    return out


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                out.append(json.loads(raw))
    return out


def existing_keys():
    """ids and event_keys already present in the ledger AND the queue."""
    ids, events = set(), set()
    for rec in load_jsonl(LEDGER) + load_jsonl(QUEUE):
        ids.add(rec.get("id"))
        events.add(rec.get("event_key"))
    return ids, events


def validate(rec, denom, ids, events):
    """Return (errors, warnings). errors block ingestion; warnings do not."""
    errors, warnings = [], []
    rid = rec.get("id", "?")
    for f in build.REQUIRED:
        if f not in rec or rec.get(f) in (None, ""):
            errors.append(f"missing required field '{f}'")
    if rec.get("actor_type") not in build.ACTOR_TYPES:
        errors.append(f"bad actor_type '{rec.get('actor_type')}'")
    if rec.get("domain") not in DOMAINS:
        errors.append(f"bad domain '{rec.get('domain')}'")
    if rec.get("verification_status") not in VERIFICATION:
        errors.append(f"bad verification_status '{rec.get('verification_status')}'")
    if rec.get("confidence") not in CONFIDENCE:
        errors.append(f"bad confidence '{rec.get('confidence')}'")
    if not isinstance(rec.get("usd_approx"), (int, float)):
        errors.append("usd_approx must be a number")
    if rec.get("id") in ids:
        errors.append(f"duplicate id '{rid}' (already in ledger/queue)")
    # soft signals — accepted, but surfaced for the reviewer
    if rec.get("event_key") in events:
        warnings.append(f"event_key '{rec.get('event_key')}' already exists "
                        "(re-announcement of the same money; will NOT be double-counted in the outlay aggregate)")
    if rec.get("iso3") not in denom:
        warnings.append(f"no denominator for iso3 '{rec.get('iso3')}' "
                        "(add it to data/denominators.json so normalized views work)")
    if rec.get("verification_status") in AUTO_FORBIDDEN_STATUS:
        warnings.append("verification_status 'verified' should be set by a human after tracing a "
                        "primary source, not by an automated scanner")
    if not rec.get("source_url") and rec.get("verification_status") not in ("unconfirmed",):
        warnings.append("empty source_url — pin a primary source or set verification_status to 'unconfirmed'")
    return errors, warnings


def _check_batch(recs, denom):
    """Validate a batch, dedup within the batch too. Returns (accepted, rejected)."""
    ids, events = existing_keys()
    accepted, rejected = [], []
    for i, rec in enumerate(recs):
        errs, warns = validate(rec, denom, ids, events)
        rid = rec.get("id", f"<row {i+1}>")
        if errs:
            rejected.append((rid, errs))
            print(f"  REJECT {rid}: {'; '.join(errs)}", file=sys.stderr)
        else:
            for w in warns:
                print(f"  warn   {rid}: {w}", file=sys.stderr)
            accepted.append(rec)
            ids.add(rec.get("id"))            # dedup later rows in the same batch
            events.add(rec.get("event_key"))
    return accepted, rejected


def append_jsonl(path, recs):
    with open(path, "a", encoding="utf-8") as fh:
        for rec in recs:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_validate(args):
    recs = read_candidates(args[0])
    denom = build.load_denominators()
    accepted, rejected = _check_batch(recs, denom)
    print(f"validate: {len(accepted)} ok / {len(rejected)} rejected (of {len(recs)})")
    return 1 if rejected else 0


def cmd_add(args):
    to_ledger = "--to-ledger" in args
    files = [a for a in args if not a.startswith("--")]
    if not files:
        raise SystemExit("usage: ingest.py add <file> [--to-ledger]")
    recs = read_candidates(files[0])
    denom = build.load_denominators()
    accepted, rejected = _check_batch(recs, denom)
    target = LEDGER if to_ledger else QUEUE
    if accepted:
        append_jsonl(target, accepted)
    where = "ledger" if to_ledger else "review queue"
    print(f"add: appended {len(accepted)} to {where} ({os.path.relpath(target, HERE)}); "
          f"{len(rejected)} rejected")
    if not to_ledger and accepted:
        print("     review with `ingest.py list`, then `ingest.py promote`")
    return 1 if rejected else 0


def cmd_list(_args):
    """Review surface: one block per queued candidate. Open each source link to
    verify before promoting; edit data/ingest-queue.jsonl by hand to fix a field
    (e.g. swap a Google-News redirect for the clean publisher URL)."""
    q = load_jsonl(QUEUE)
    if not q:
        print("review queue is empty")
        return 0
    print(f"review queue: {len(q)} record(s) — verify sources, then `ingest.py promote <id> ...`\n")
    for r in q:
        print(f"  [{r.get('id')}]  {r.get('jurisdiction','?')} · {r.get('domain','?')} · "
              f"{r.get('actor_type','?')} · {r.get('verification_status','?')}/{r.get('confidence','?')}")
        print(f"     {r.get('program','')}  —  {build.b(r.get('usd_approx'))} "
              f"({r.get('currency','?')})  announced {r.get('announced','?')}")
        print(f"     source: {r.get('source_url') or '(no URL — add one before promoting)'}")
        if r.get("notes"):
            print(f"     notes:  {str(r.get('notes'))[:140]}")
        print()
    return 0


def cmd_promote(args):
    q = load_jsonl(QUEUE)
    if not q:
        print("review queue is empty")
        return 0
    wanted = set(args)
    take = [r for r in q if (not wanted or r.get("id") in wanted)]
    keep = [r for r in q if r not in take]
    denom = build.load_denominators()
    # re-validate against the LEDGER only (queue rows are being removed)
    ids = {r.get("id") for r in load_jsonl(LEDGER)}
    events = {r.get("event_key") for r in load_jsonl(LEDGER)}
    promoted, blocked = [], []
    for r in take:
        errs, _ = validate(r, denom, ids, events)
        if errs:
            blocked.append((r.get("id"), errs))
            keep.append(r)
            print(f"  BLOCK {r.get('id')}: {'; '.join(errs)}", file=sys.stderr)
        else:
            promoted.append(r)
            ids.add(r.get("id"))
            events.add(r.get("event_key"))
    if promoted:
        append_jsonl(LEDGER, promoted)
        with open(QUEUE, "w", encoding="utf-8") as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"promote: moved {len(promoted)} to the ledger; {len(blocked)} blocked; {len(keep)} left in queue")
    if promoted:
        print("     now run `python3 build.py` and commit")
    return 1 if blocked else 0


COMMANDS = {"validate": cmd_validate, "add": cmd_add, "list": cmd_list, "promote": cmd_promote}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
