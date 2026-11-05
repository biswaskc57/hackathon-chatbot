"""Run the e-mail drafter on the tickets (or the golden set), the same way eval_run.py runs the chatbot.

Every ticket is treated as an incoming e-mail (subject + body) and drafted with the "email-draft" preset.
Writes results/<date>_email-draft_<fingerprint>_<set>.jsonl and .csv (with empty columns for checking by hand).

Run on the Mac (needs the gateway):
    .venv/bin/python eval_email.py --limit 3          first try
    .venv/bin/python eval_email.py                    all 40 tickets (blind test: once)
    .venv/bin/python eval_email.py --model-preset gemini-3.5-flash
                                                      same e-mail prompt and search, the model (and its settings) from that preset
    .venv/bin/python eval_email.py --model-preset gemini-3.5-flash --dry-run
                                                      show the settings and fingerprint, no calls
"""

import argparse
import csv
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from config import list_presets, load_settings
from email_draft import draft_reply, email_settings

ROOT = Path(__file__).resolve().parent
DATA, RESULTS = ROOT / "data", ROOT / "results"


def load_cases(test_set: str) -> list[dict]:
    if test_set == "tickets":
        with open(DATA / "tickets_tv.csv", encoding="utf-8") as f:
            return [{"id": r["ticket_id"], "channel": r["channel"], "category": r["category"], "kind": r["type"],
                     "subject": r["subject"], "body": r["body"], "source_passage_ids": r["source_passage_ids"].split("|")}
                    for r in csv.DictReader(f)]
    with open(DATA / "golden_seed.csv", encoding="utf-8") as f:
        return [{"id": r["question_id"], "channel": "golden", "category": r["category"], "kind": r["kind"],
                 "subject": r["question"][:60], "body": r["question"], "source_passage_ids": r["source_passage_ids"].split("|")}
                for r in csv.DictReader(f)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["tickets", "golden"], default="tickets")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model-preset", help="take model, temperature and model parameters from this preset "
                                               "(e.g. gemini-3.5-flash); prompt, search and limits stay the e-mail ones")
    parser.add_argument("--dry-run", action="store_true", help="show settings and fingerprint, no calls")
    args = parser.parse_args()

    settings = email_settings()
    if args.model_preset:
        if args.model_preset not in list_presets():
            raise SystemExit(f"Unknown preset '{args.model_preset}'. Available: {', '.join(list_presets())}")
        m = load_settings(args.model_preset)
        settings = replace(settings, model=m.model, temperature=m.temperature, extra_params=m.extra_params,
                           preset=f"{settings.preset}+{args.model_preset}")
    cases = load_cases(args.set)[: args.limit]
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M')}_{settings.preset}_{settings.fingerprint()}_{args.set}"
    RESULTS.mkdir(exist_ok=True)
    print(f"[{run_id}] {settings.model} {settings.extra_params or ''} temp {settings.temperature} | "
          f"search {settings.search_label()}, top {settings.top_k} | {len(cases)} e-mails")
    if args.dry_run:
        return

    rows = []
    for i, c in enumerate(cases, 1):
        d = asdict(draft_reply(c["subject"], c["body"], settings=settings))
        rows.append({"run_id": run_id, "test_set": args.set, "preset": settings.preset,
                     "fingerprint": settings.fingerprint(), "model": settings.model, **c,
                     "question": f"Subject: {c['subject']}\n\n{c['body']}", **d,
                     "retrieval_hit": bool(set(c["source_passage_ids"]) & set(d["retrieved_ids"]))})
        print(f"[{i}/{len(cases)}] {c['id']}: {d['decision']}" + (f"  ({len(d['warnings'])} warnings)" if d["warnings"] else ""))

    (RESULTS / f"{run_id}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (RESULTS / f"{run_id}_settings.json").write_text(json.dumps({"fingerprint": settings.fingerprint(), **settings.values()},
                                                                indent=2, ensure_ascii=False), encoding="utf-8")
    cols = ["id", "channel", "category", "kind", "question", "decision", "draft", "triage_note", "notes_for_agent",
            "source_passage_ids", "retrieved_ids", "retrieval_hit", "cited_ids", "warnings", "input_tokens", "output_tokens",
            "score (correct/partly/wrong/handover)", "invented_content (y/n)", "effort (as-is/minor/major/discard)", "scorer", "notes"]
    with open(RESULTS / f"{run_id}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in rows:
            w.writerow({**r, **{k: " | ".join(map(str, r[k])) if isinstance(r[k], list) else r[k]
                                for k in ("source_passage_ids", "retrieved_ids", "cited_ids", "warnings")},
                        "retrieval_hit": "y" if r["retrieval_hit"] else "n"})
    decisions = {k: sum(r["decision"] == k for r in rows) for k in ("draft", "partial", "no_draft")}
    print(f"\nDecisions: {decisions} | search hit (top {settings.top_k}): {sum(r['retrieval_hit'] for r in rows)}/{len(rows)}")
    print(f"Results: results/{run_id}.jsonl  (next: python3 judge_answers.py results/{run_id}.jsonl)")


if __name__ == "__main__":
    main()
