"""Score answers automatically with a second model ("LLM as judge"), then check a sample by hand.

Reads a results .jsonl from eval_run.py (chatbot) or eval_email.py (e-mail drafts). For each answer the judge sees:
the customer's message, the manual passages that answer it (the test set's source passages), the other passages
the assistant was given, and the answer. It scores with the team's proposed rule:
    correct   the key steps from the source passages, every claim supported by the manual text shown
    partly    nothing wrong, but key steps missing
    wrong     any TV feature, menu, option or step not in the manual text shown, or the wrong problem
    handover  no real answer, only a referral to a human (a "no draft" e-mail counts here without a judge call)
Generic advice about the customer's own device is not counted as invented. E-mail drafts also get an effort
estimate (send as-is / minor edit / major edit / discard).

Use a DIFFERENT model as judge than the one that answered (default claude-opus-4-8), and check 10 answers by hand:
the agreement rate is what makes the scores credible. The script prints which 10.

Run on the Mac (needs the gateway):
    .venv/bin/python judge_answers.py results/<run>.jsonl
    .venv/bin/python judge_answers.py results/<run>.jsonl --judge-model gemini-3.5-flash --limit 3
"""

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path

from llm_client import APIClient, LLMError, parse_usage
from retrieval import load_corpus

PROMPT = """You check answers from a TV support assistant against the TV manual. Be strict and fair.

CUSTOMER MESSAGE:
{question}

MANUAL PASSAGES THAT ANSWER IT (ground truth):
{gold}

OTHER MANUAL PASSAGES THE ASSISTANT WAS GIVEN:
{other}

THE ASSISTANT'S {what}:
{answer}

Score it:
- "correct": it addresses the customer's actual problem with the key steps or facts from the ground-truth passages, and every claim is supported by the manual text above.
- "partly": nothing in it is wrong, but key steps or facts from the ground-truth passages are missing.
- "wrong": at least one TV feature, menu name, option or step is not in the manual text above or contradicts it, or it answers a different problem.
- "handover": there is no real answer; it only refers the customer to a human colleague.
Ending with "contact support if this does not help" is fine when the manual says so. Generic advice about the customer's own device or cable (for example: check the cable is plugged in) is not invented content, unless it is presented as a TV feature or setting.
- "invented": "y" if any TV feature, menu name, option or procedure is not in the manual text above, else "n". Quote it in "invented_detail".
- "missing": the most important missing step, or "".
- "reason": one sentence.{effort_rule}

Return only a JSON object: {{"score": "...", "invented": "y|n", "invented_detail": "...", "missing": "...", "reason": "..."{effort_field}}}"""

EFFORT_RULE = ('\n- "effort": how much a support agent would need to change before sending this e-mail: '
               '"send as-is", "minor edit", "major edit" or "discard".')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", help="a .jsonl written by eval_run.py or eval_email.py")
    parser.add_argument("--judge-model", default="claude-opus-4-8", help="use a different model than the one that answered")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rows = [json.loads(l) for l in Path(args.results).read_text(encoding="utf-8").splitlines() if l.strip()][: args.limit]
    is_email = "decision" in rows[0]
    if rows[0].get("model") == args.judge_model:
        print(f"Note: the judge ({args.judge_model}) is the same model that answered. Prefer a different one.")
    corpus = {p.id: p for p in load_corpus()}
    client = APIClient()
    out_path = Path(args.results).with_name(Path(args.results).stem + f"_judged-{args.judge_model}.jsonl")
    tok_in = tok_out = 0

    judged = []
    for i, r in enumerate(rows, 1):
        answer = r.get("draft") if is_email else r.get("answer")
        gold_ids = r["source_passage_ids"] if isinstance(r["source_passage_ids"], list) else r["source_passage_ids"].split("|")
        other_ids = [p for p in r.get("retrieved_ids", []) if p not in gold_ids]
        if is_email and r.get("decision") == "no_draft":
            verdict = {"score": "handover", "invented": "n", "invented_detail": "", "missing": "",
                       "reason": "No draft was written.", "effort": "discard"}
        else:
            prompt = PROMPT.format(
                question=r["question"],
                gold="\n\n".join(f"[{p}] {corpus[p].text}" for p in gold_ids if p in corpus),
                other="\n\n".join(f"[{p}] {corpus[p].text}" for p in other_ids if p in corpus) or "(none)",
                what="E-MAIL DRAFT" if is_email else "ANSWER", answer=answer,
                effort_rule=EFFORT_RULE if is_email else "", effort_field=', "effort": "..."' if is_email else "")
            try:
                resp = client.create_chat_completion(model=args.judge_model, temperature=0, maxTokens=400,
                                                     messages=[{"role": "user", "content": prompt}])
                verdict = json.loads(re.search(r"\{.*\}", resp["data"]["content"], re.S).group(0))
                u = parse_usage(resp); tok_in += u["input_tokens"] or 0; tok_out += u["output_tokens"] or 0
            except (LLMError, AttributeError, ValueError) as exc:
                verdict = {"score": "", "reason": f"judge failed: {exc}"}
        judged.append({**r, "judge_model": args.judge_model, **{f"judge_{k}": v for k, v in verdict.items()}})
        print(f"[{i}/{len(rows)}] {r['id']}: {verdict.get('score')}" + (" (invented)" if verdict.get("invented") == "y" else ""))

    out_path.write_text("".join(json.dumps(j, ensure_ascii=False) + "\n" for j in judged), encoding="utf-8")
    with open(out_path.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["id", "category", "kind", "question", "draft" if is_email else "answer", "judge_score", "judge_invented",
                "judge_invented_detail", "judge_missing", "judge_reason"] + (["judge_effort"] if is_email else []) + ["human_score", "human_notes"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(judged)

    scores = {s: sum(j.get("judge_score") == s for j in judged) for s in ("correct", "partly", "wrong", "handover")}
    print(f"\nJudge ({args.judge_model}): {scores} | invented: {sum(j.get('judge_invented') == 'y' for j in judged)}/{len(judged)}"
          f" | judge tokens {tok_in} in, {tok_out} out")
    if is_email:
        print("Effort:", {e: sum(j.get("judge_effort") == e for j in judged) for e in ("send as-is", "minor edit", "major edit", "discard")})
    sample = sorted(random.Random(42).sample([j["id"] for j in judged], min(10, len(judged))))
    print(f"\nCheck these by hand (fill human_score in the CSV): {', '.join(sample)}")
    print(f"Saved: {out_path}\n       {out_path.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
