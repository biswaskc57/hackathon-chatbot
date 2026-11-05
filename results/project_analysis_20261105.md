# Project analysis and plan, 5 November 2026

What the results so far mean for the project brief, where the repo stands against R1–R7, and a phased plan for
the next session. All numbers come from the runs in `results/` (golden set, 20 questions, one scorer) and the
client facts in the brief.

## 1. The business case in numbers

| | Per month |
|---|---|
| Contacts | 18,000 (60% hotline, 40% written) |
| Cost today (EUR 7.37 per contact) | EUR 132,660 |
| Target (EUR 6.26 per contact, bot cost included) | EUR 112,680 |
| **Saving needed** | **EUR 19,980 = 33,300 agent minutes (1.85 min per contact)** |

Agent minutes by channel and type (EUR 0.60 per minute):

| | How-to (8.5 min) | Troubleshooting (10.5 min) | Out of scope (14 min) |
|---|---|---|---|
| Written (7,200 contacts) | 2,736 contacts · EUR 13,954 | 2,304 · EUR 14,515 | 2,160 · EUR 18,144 |
| Hotline (10,800 contacts) | 4,104 · EUR 20,930 | 3,456 · EUR 21,773 | 3,240 · EUR 27,216 |

The bot can only fully solve **written in-scope** contacts (EUR 28,469 of agent time per month). Hotline
contacts can only be shortened through **agent assist**. What it takes to reach the target:

| Written in-scope solved by the bot | Hotline in-scope time saved by agent assist | Saving per month | Target met? |
|---|---|---|---|
| 50% | 0% | EUR 14,234 | no |
| 70% | 0% | EUR 19,928 | no (just short) |
| 50% | 20% | EUR 22,775 | yes |
| 70% | 10% | EUR 24,198 | yes |

**Finding 1: the chat bot alone cannot reach the target.** Even 70% self-service on written contacts falls just
short. Agent assist for the hotline (60% of contacts) is part of the business case, not an extra. The brief ranks
the agent tab fourth; the numbers say it carries a large share of the saving.

**Finding 2: model cost is small for the target, but not for the budget.** Measured cost per 3-turn conversation
(list prices, see `cost_breakdown_20261105.md`), at one conversation per contact:

| Model | Per conversation | Per year (216,000 conversations) | With rewrite + rerank steps (about x3) |
|---|---|---|---|
| gemini-3.5-flash | $0.0076 | $1,642 | about $4,900 |
| gpt-4o | $0.0110 | $2,376 | about $7,100 |
| claude-opus-4-8 | $0.0370 | $7,992 | about $24,000 (30% of the EUR 80,000 budget) |

Per contact even Claude is under 10% of the EUR 1.11 saving target. But a multi-step pipeline on Claude would use
a large part of the first-year budget. Cheaper models for the rewrite, router and judge steps keep this down.

**Finding 3: wrong answers are expensive.** A wrong answer that brings the customer back costs a full contact
(EUR 7.37) and breaks the guard rail. Each 1% of wrong answers on written in-scope contacts is about 50 repeat
contacts, EUR 370 a month. A hand-over costs nothing extra. This is why the evidence gate and the menu-path check
matter more than the choice between similar models.

## 2. What the results show so far

| Result | Count | 95% confidence interval | Source |
|---|---|---|---|
| Golden answers correct (enriched search, any of the top 4 models) | 18/20 | 70% to 97% | model comparison |
| Invented content, Claude Opus 4.8 (both runs) | 0/20 | 0% to 16% | model comparison |
| Invented content, gpt-4o / gpt-5 / Gemini 3.5 Flash (raw run) | 1/20 each | 1% to 24% | model comparison |
| Right passage in top 3, enriched + glossary | 20/20 | 84% to 100% | measure_search.py |
| Out-of-scope probe handed over (top 4 models) | 8/8 | 68% to 100% | draft probe, not a test set |
| Follow-ups that keep troubleshooting after the fix | 17/20 | 64% to 95% | 5 conversations x 4 models |
| Warranty trap (p0020 retrieved, warranty mentioned) | 2 of 15 runs | | gemini-2.5-pro, gpt-5 (raw) |
| Median answer time, shortlisted models | 2.6–4.2 s | | under the 5 s target |

What this does **not** tell us yet:
- **Resolution rate.** "Correct per the manual" is not "the customer's problem is solved". The business case
  depends on how many written in-scope contacts end without an agent. We have no number for this.
- **Wrong-answer rate with confidence.** With n = 20, "0 wrong" still allows up to 16%. The extended and
  robustness sets (R3) are needed to narrow this.
- **Routing.** Out-of-scope behaviour rests on the system prompt and an 8-question draft probe.
- **Ticket results.** Tickets are no longer blind (see 4).

## 3. Repo against the requirements

| Req. | Status | What exists | What is missing |
|---|---|---|---|
| R1 Ingest | partly | Passages as given; the prompt tells the model to read "Settings Picture Picture Mode" as a path | Restore ">" at ingest, split p0106 / p0210 / p0068 (5,300 to 5,700 chars, median 744) into chunks with the parent id, collapse near-duplicates |
| R1 Search | partly | BM25; enriched search (generated customer questions); glossary (5 entries); follow-up search with earlier messages | Vectors + RRF, LLM query rewriting, optional rerank |
| R1 Acceptance | | Golden hit@5 19/20 raw, 20/20 with glossary; tickets 35/40 raw, 38/40 enriched | Brief says the ticket baseline is 34/40; our raw count is 35/40. Agree which run is the baseline |
| R2 Router | missing | Scope rules only in the system prompt | Router step (in scope / out / unclear), clarifying question |
| R2 Evidence gate | missing | | Gate on retrieval or rerank score; the README notes a BM25 score threshold alone was not enough |
| R2 Grounded answers | done | Numbered steps, menu paths, citations, "contact support if" kept | |
| R2 Menu-path check | partly | `eval_run.py` flags unknown paths as hints, with many false positives (regex catches trailing words) | Menu tree from the corpus, check inside the answer step, block or hand over |
| R2 PII masking | missing | Prompt asks customers not to share data; logs store lengths only | Masking before the LLM call |
| R2 Trap passages | not handled | p0020 contains a warranty sentence; p0138 is "Request Support" | Tests and a rule; 2 of 15 runs already repeated the warranty sentence |
| R3 Runner | partly | `eval_run.py`: CSV per run + settings file, `--model`, `--params` | jsonl named `<date>_<preset>_<fingerprint>`, retrieval switchable per preset |
| R3 Metrics | partly | hit@1/3/5; tokens; latency; hand scoring | recall@k, precision@k, MRR, acceptable-passages list, faithfulness, citation precision, routing confusion matrix, EUR per answer in the runner, confidence intervals |
| R3 LLM judge | missing | One human scorer (first pass) | Judge with fixed rubric, stored reasoning, human-review file, agreement |
| R3 Test sets | partly | Golden (unchanged); 8-question out-of-scope draft (not in the repo) | Extended set (~30), robustness set (60 rewordings), frozen |
| R4 Reporting | partly | Two write-ups (`model_comparison`, `cost_breakdown`) by hand | `report.py`, trade-off chart, failure list, CSV for the cost model |
| R5 UI | partly | Streamlit chat with presets; web API + Lovable chat (both call `run_turn`) | Collapsible sources and visible hand-over in Streamlit; agent tab; evaluation tab; retrieval settings in the sidebar |
| R6 Performance | mostly | Index built once per process (BM25 builds in under a second); median 2.6–4.2 s | Index and embedding cache on disk (needed once vectors arrive); tokens per step |
| R7 Guided troubleshooting | partly | Prompt gives 1–2 checks at a time; follow-ups now find the passage again | Step-by-step use of the structured troubleshooting passages |

## 4. Rule issues to fix first

1. **Tickets are no longer a blind test.** Ticket hit rates were printed in every `measure_search.py` run, and
   4 of the 5 glossary entries name tickets as their source (TV-0003, TV-0037, TV-0024, TV-0031, TV-0028, TV-0025).
   Proposal: remove the ticket-sourced glossary entries (keep the Q12 entry from the golden set), stop printing
   ticket totals in `measure_search.py`, and record in the README that ticket search numbers were seen during
   development. The answer-level ticket run has not been done, so that part can still be blind.
2. **Not every behaviour is switchable in a preset.** Search type (raw / enriched / glossary), the follow-up
   search and top-k live in code, environment variables or command-line flags. They should move into `Settings`,
   which also puts them in the fingerprint. This changes all fingerprints once; the old `a9a0f383` runs stay
   comparable through their settings files.
3. **Results format.** The brief asks for `results/<date>_<preset>_<fingerprint>.jsonl`. Extend `eval_run.py` to
   write that next to the existing CSV (the CSV stays for hand scoring).

## 5. Model choice for the next phase

The guard rail ("a confident wrong answer is worse than a hand-over") favours the model that hands over when the
evidence is missing. On our data that is Claude Opus 4.8. Gemini 3.5 Flash matched it once the search found the
right passage, at a fifth of the cost. The evidence gate and menu-path check (R2) will make the answer model less
decisive. Proposal: build R1/R2 with **gemini-3.5-flash** as the default answer model, keep **claude-opus-4-8**
as the comparison preset, and decide after the extended set and the trade-off chart.

## 6. Plan for the next session

Each step is a small commit, switchable in a preset, and followed by an evaluation run with before/after numbers.

| Step | Requirement | Work | Done when |
|---|---|---|---|
| 0 | Rules | Remove ticket-sourced glossary entries; move search type, follow-up search and top-k into `Settings`; jsonl results file | Fingerprints include retrieval settings; tickets untouched from here on |
| 1 | R1 ingest | Restore ">" in menu paths; chunk the three long passages (parent id kept, citations use the parent id); collapse the three near-duplicate pairs; cached index | Golden hit@5 not lower; hit@1 measured |
| 2 | R3 retrieval | `acceptable_passages.csv` (hand-checked, golden only); recall@k, precision@k, MRR; confidence intervals | One retrieval scorecard for all search variants |
| 3 | R1 hybrid | Check the gateway for an embeddings endpoint; otherwise a small local model (needs a one-off download); RRF merge | hit@5 >= baseline, hit@1 better than 14/20 |
| 4 | R1 rewrite + rerank | LLM query rewrite (prompt sees only the customer message, never tickets); optional LLM rerank of top 10 with a score | Fit to Screen and Anynet+ found without glossary entries |
| 5 | R2 safety | Router; evidence gate on the rerank score; menu tree + path check; PII masking; hand-over ticket summary; p0020 / p0138 trap rule | Each switch on/off in a preset |
| 6 | R3 answers | Extended set (~30) and robustness set (60), frozen; LLM judge with rubric; human-review file of 20 cases; routing confusion matrix | Judge-human agreement reported |
| 7 | R4 | `report.py`, trade-off chart (answered share vs wrong-answer rate across gate thresholds), failure list, CSV of rates for the cost model | Business team can plug in the rates |
| 8 | R5 | Streamlit agent tab and evaluation tab; Lovable chat stays on the API | Agent tab uses `run_turn` |

## 7. Decisions needed

1. Remove the ticket-sourced glossary entries and treat ticket *search* numbers as seen? (Proposed: yes.)
2. Embeddings: if the gateway has none, may we download a small local model (about 100–500 MB)?
3. Default answer model for R1/R2: gemini-3.5-flash, with claude-opus-4-8 as comparison? (Proposed: yes.)
4. Which ticket baseline counts for R1 acceptance: 34/40 (brief) or 35/40 (our raw measurement)?
5. The business team needs a resolution-rate assumption for written in-scope contacts (we can only measure
   correct answers and hand-over rates, not whether the customer's problem was solved).
