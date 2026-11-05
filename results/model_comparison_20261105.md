# Model comparison, 5 November 2026

Which gateway model should answer customers? All 11 models available through the MCI key were run on the
golden set (20 questions, raw corpus, BM25 top 3, eval prompt, no conversation memory). Only the model and the
parameters it needs to give a complete answer change between runs. Scored by one scorer (Claude), first pass,
against the reference answers; the team's scoring rule is not agreed yet. Small samples: they show differences,
not statistically proven ones.

## Recommendation (after the raw and enriched runs)

| Rank | Model | Settings | Why |
|---|---|---|---|
| 1 | `claude-opus-4-8` | temperature 0 (eval default) | The only model with **no invented content in either run**. When the search misses (Q12, and Q14 in the raw run) it hands over instead of guessing, and the search will still miss on real tickets (35/40 in the top 3 with the enriched search). Follows the style rules (asks "Did this help?"), shortest correct answers, hands over on all 8 out-of-scope probes. |
| 2 | `gemini-3.5-flash` | `{"reasoningEffort": "minimal"}` | With the enriched search: 18/20 correct, nothing invented, fastest (2.6 s median). It was wrong on Q14 in the raw run. Its weak points are style, which the prompt can fix: introduces itself as an AI in 12 of 20 answers, says "I will hand you over now" although no hand-over exists yet, once wrote "$180$". |
| 3 | `gpt-5` | `{"temperature": 1, "reasoningEffort": "minimal"}` | 18/20 correct, but it adds its own knowledge: in the enriched run it says the manual does not cover Q12 and then gives an Anynet+ path "on many Smart Tech TVs" anyway; in the raw run it invented a pairing-code step (Q13). Longest answers (156 words). Grounding problems are harder to fix with the prompt than style. |
| ref | `gpt-4o` | eval default | Current baseline. Raw run: answered Q14 from its own knowledge. With the enriched search the Q14 miss disappears and it is as clean as Claude on this set, so its weak point only shows when the search misses. |

## Cost per answer

List prices from third-party price pages (November 2026, not confirmed against the providers' own pages or the
gateway's billing). Tokens are the measured averages per golden answer: enriched run for the top four, raw run
for the others. Output tokens include hidden reasoning tokens.

| Model | $ per 1M input / output | Avg. tokens in / out | Cost per answer | Per 1,000 answers | Quality on the golden set |
|---|---|---|---|---|---|
| gpt-5-nano | 0.05 / 0.40 | 1103 / 143 | $0.0001 | $0.11 | Not scored in full; irrelevant steps on Q14 |
| gemini-3.1-flash-lite | 0.25 / 1.50 | 1091 / 154 | $0.0005 | $0.50 | Not scored in full; Q14 misdiagnosed, answered the account question |
| **gemini-3.5-flash** | 1.50 / 9.00 | 1057 / 200 | **$0.0034** | **$3.39** | 18 correct, 0 invented (enriched) |
| **gpt-5** (minimal) | 1.25 / 10.00 | 1069 / 229 | **$0.0036** | **$3.63** | 18 correct, 1 invented (enriched) |
| gpt-4o | 2.50 / 10.00 | 1046 / 176 | $0.0044 | $4.38 | 18 correct, 0 invented (enriched); legacy model |
| **claude-opus-4-8** | 5.00 / 25.00 | 1650 / 223 | **$0.0138** | **$13.80** | 18 correct, 0 invented in both runs |

The model is a very small part of the cost per contact (EUR 7.37 today, target EUR 6.26). Even Claude Opus 4.8
costs under 2 cents per answer. A wrong answer that brings the customer back costs a full contact, so Claude's
extra ~$10 per 1,000 answers over Gemini 3.5 Flash pays for itself if it prevents about one or two repeat
contacts per 1,000 answers. It avoided a guess on 1 of 20 questions in the raw run. The two cheapest models
would save about $3 per 1,000 answers compared with Gemini 3.5 Flash, which does not justify weaker answers.

## Golden set (20 questions), raw search

| Model | Correct | Hand-over | Wrong or invented | Median / max latency | Avg. input / output tokens | Avg. words |
|---|---|---|---|---|---|---|
| claude-opus-4-8 | 18 | 2 (Q12, Q14) | 0 | 4.2 / 5.9 s | 1698 / 232 | 105 |
| gpt-5 (minimal) | 18 (3 with small additions) | 1 (Q12) | Q14 irrelevant steps | 3.5 / 6.5 s | 1103 / 234 | 156 |
| gemini-3.5-flash (minimal) | 17 | 1 (Q12) | Q14 wrong, Q16 partly | 2.9 / 5.2 s | 1091 / 206 | 143 |
| gpt-4o | 18 (2 with small additions) | 1 (Q12) | Q14 invented | 3.2 / 5.2 s | 1080 / 177 | 131 |

- Q12 and Q14 are retrieval misses: the right passage is not in the top 3. The right behaviour there is to hand over. Only Claude Opus 4.8 did this on both.
- Every model cited the right passage on 17 or 18 of 20 questions; the `must_include` and unknown-menu hints from `eval_run.py` barely separate the models (most menu "hints" are regex false positives).
- Claude counts about 55% more input tokens for the same text (its tokenizer), so its token cost per answer is higher. At list prices it is still well under EUR 0.02 per answer, small against the EUR 7.37 cost per contact; check the gateway's own price list before using cost figures in the business case.

## Golden set, enriched search (top 3 and gpt-4o)

Same settings; the search also uses `data/search_questions.jsonl`. 12 questions get different passages, but only
one changes from a miss to a hit: **Q14** now finds p0107 (pairing). Q12 still misses.

| Model | Correct | Partly | Hand-over | Invented | Median latency | Avg. input / output tokens |
|---|---|---|---|---|---|---|
| claude-opus-4-8 | 18 | Q14 | Q12 | 0 | 3.5 s | 1650 / 223 |
| gemini-3.5-flash | 18 | Q14 | Q12 | 0 | 2.6 s | 1057 / 200 |
| gpt-5 (minimal) | 18 | Q14 | Q12, but with an invented Anynet+ path | 1 | 4.0 s | 1069 / 229 |
| gpt-4o | 18 | Q14 | Q12 | 0 | 2.8 s | 1046 / 176 |

- Q14 is only partly right for every model: the passages on batteries, protective stickers and the TV buttons
  (p0236, p0108) are still not found, so all models give only the pairing step. That is correct and grounded.
- The enriched search does not slow anything down and uses slightly fewer input tokens.
- The golden set is the development set: the generated search questions were not written from it, but the
  enriched gain should be confirmed on the held-out tickets.

## Out-of-scope probe (8 questions, draft)

Warranty, return, order status, price, accessory, burning smell plus technician, account e-mail change, in-app
refund. Written for this comparison only; it is not the team's out-of-scope set.

- All four models above handed over on all 8. Claude Opus 4.8 and gpt-5 also gave the manual's safety and
  diagnosis steps where they apply (vertical line, burning smell), which is the behaviour we want.
- `gemini-3.1-flash-lite`, `gemini-2.5-pro`, `claude-opus-4-6` and `sonar-pro` answered the account question
  themselves instead of handing over.
- Several models promise actions that do not exist yet ("I'll arrange a technician", "I am handing you over now").
  The prompt should say that the hand-over is offered, not performed, until the hand-over feature is built.

## Not shortlisted

| Model | Reason |
|---|---|
| `sonar-pro`, `sonar-reasoning-pro` | Web-search models: wrong tool for answers that must come only from the manual of a fictional brand. Answers were short and grounded here, but answered the account question (sonar-pro). |
| `gemini-2.5-pro`, `gemini-3.1-pro-preview` | Thinking cannot be switched off or reduced enough: about 1,000 output tokens per answer, median 10–13 s, up to 45 s. Too slow for chat. |
| `claude-opus-4-6` | Superseded by 4.8. Slower (up to 26 s), chattier, answered the account question. Needs `reasoningEffort: none` for temperature 0. |
| `gemini-3.1-flash-lite` | Fastest (2.1 s) but the most menu-path hints (11/20) and answered the account question. |
| `gpt-5-nano` | Fast and cheap, but weaker hand-over wording and the fewest correct citations (17). |

## Gateway notes

- `gpt-5` and `gpt-5-nano` fail with temperature 0 (error 605); they need `reasoningEffort` and accept only temperature 1.
- Gemini 3.x models spend the `maxTokens` budget on hidden reasoning: at 800 tokens the visible answer is cut off.
  `reasoningEffort: "minimal"` fixes this for the Flash models; the Pro models need `maxTokens` 3000.
- `claude-opus-4-6` accepts temperature only with `reasoningEffort: "none"`; `claude-opus-4-8` rejects `none`.

## Files

`results/corpus-raw_golden_<model>_20261105-1000.csv` and `_settings.json` for every model, and
`results/corpus-enriched_golden_<model>_20261105-1016.csv` for the four enriched runs. Reproduce a run with,
for example:

    .venv/bin/python eval_run.py --corpus raw --set golden --model gpt-5 --params '{"temperature": 1, "reasoningEffort": "minimal"}'

## Next steps

1. Decide whether the UI uses the enriched search (it helps every model on Q14 and costs nothing extra), then, once
   the prompt is frozen, run the chosen model on the held-out tickets.
2. Have a second team member score the shortlisted CSVs, so the result does not rest on one scorer.
3. Add the "offer, do not promise, a hand-over" line to the prompt and write the team's out-of-scope set.
