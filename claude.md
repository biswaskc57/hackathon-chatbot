# Smart Tech Support Assistant – Project brief for Claude Code

## 1. Project definition
Hackathon Track A. An AI support assistant for Smart Tech Inc. (fictional European smart-TV maker) that answers
TV how-to and troubleshooting questions from the product manual with sources, hands everything else to a human
with a ticket summary, assists human agents, and drafts replies to emails.

We must prove three claims in the demo:
1. It answers correctly from the manual, with sources.
2. It knows when NOT to answer and hands over cleanly ("a confident wrong answer is worse than a hand-over").
3. Its cost and quality are measured, not assumed (numbers go to the separate business presentation).

Client facts: 18,000 contacts/month; 60% hotline, 40% written (chat, e-mail, web form); 38% how-to (8.5 min),
32% troubleshooting (10.5 min), 30% out of scope: warranty, repair, orders, prices, account (14 min).
Target: cost per contact EUR 7.37 -> <= EUR 6.26 with no increase in wrong advice. GDPR and EU AI Act apply.

## 2. Architecture

```
FRONT-ENDS                 Live demo (split screen)   Email screen   CLI (chat.py)   Evaluation runner
                                     \                    |               |               /
ENGINE                                assistant.run_turn(conversation, message, settings) -> TurnResult
                                      mode = "pipeline" (default) | "agent" (bounded agent, R9)
                                                          |
MODULES (each switchable in settings.json)
  pii.py        mask personal data before any LLM call
  router.py     how-to | troubleshooting | out of scope | unclear
  retrieval     clean + chunk corpus, hybrid search (BM25 + vectors), optional query rewrite / rerank
  gate          evidence gate: answer only when the manual supports it
  answer        grounded answer with [pXXXX] citations, keeps "contact support if…"
  menu_check    menu-path check against a tree built from the corpus (blocks invented menus)
  tickets.py    one ticket per conversation, lifecycle + hand-over summary (R6)
  email.py      parse, mask, split questions, decide, draft reply (R7)
                                                          |
GATEWAY                    llm_client.py (EU gateway; roles user/assistant only; camelCase params)
                                                          |
STORAGE   data/ (corpus, golden, tickets_tv, own test sets) · index/ (generated, not committed)
          results/ (evaluation runs) · logs/ (no customer text) · tickets store (masked summaries only)
          demo/replays/ (recorded demo scenarios for replay mode)
```

Target layout is guidance. Map existing files onto it; do not rename or move files without a plan I approved.

## 3. Current state of the repo (do not break)
Audited 5 Nov 2026. Real files, mapped onto the target layout:

Engine and gateway
- llm_client.py: gateway client (retries, readable errors, parse_usage). Gateway accepts ONLY roles "user" and
  "assistant"; fold_system_messages() puts the system prompt into the first user message. camelCase params (maxTokens).
- config.py + settings.json: Settings dataclass, named presets (baseline, strict-0.0, gemini-3.5-flash,
  gpt-5-minimal, email-draft), 8-char settings fingerprint, MODEL_RULES (params each gateway model needs).
  The default system prompt exists twice (config.py fallback + settings.json): change both.
- assistant.py: run_turn(client, history, user_text, settings, conversation_id, turn, source, passages=None)
  -> TurnResult(answer, history, usage, latency_s, retrieved_ids). Steps today: BM25 search -> passages placed
  before the question with "cite [pXXXX], hand over if not covered" instructions -> one gateway call -> one log
  line in logs/conversation_log.jsonl (lengths, ids, tokens, latency; no customer text). No router, gate, PII,
  menu check or ticket inside run_turn yet.
- retrieval.py: BM25 over data/corpus.jsonl; optional search-only enrichment (data/search_questions.jsonl,
  5 generated customer questions per passage) and glossary query expansion (data/glossary.csv, with "unless"
  words); follow-up search (score < 8.5 -> searched with the last 2 customer messages). No cleaning, chunking,
  dedup, vectors or rewrite yet.

Front-ends (all call run_turn)
- app.py: Streamlit chat, centered layout, preset/settings sidebar, token stats. run.py ui.
- pages/1_Agent_inbox.py: Streamlit page auto-loaded next to app.py: e-mail inbox (data/demo_emails.jsonl or
  pasted), draft via email_draft.py, edit / send (simulated) / discard, review log to logs/email_review_log.jsonl.
- chat.py: CLI. run.py chat.
- api.py (+ Dockerfile, requirements-api.txt, .dockerignore): FastAPI for the external Lovable UI: /config,
  /chat, /feedback (thumbs up/down + fixed reason, logs/feedback_log.jsonl). Access-code protected. run.py api.
- email_draft.py: draft_reply(subject, body) -> EmailDraft: regex clean-up (quoted replies, sign-off, e-mail,
  phone, serial, order number), search (preset email-draft: enriched + glossary, top 5), one JSON call
  (draft | partial | no_draft, category, type, priority, cited_ids, triage_note), then checks: strip ids from the
  text, warn on menu paths / bold terms not in the corpus, add the AI notice.

Evaluation (keep all; results are evidence for the business deck)
- eval_run.py: test set (golden | tickets) x preset [--corpus none|raw|enriched] [--model] [--params]. Fixed eval
  values on top of the preset: temperature 0, 800 tokens, no memory, "all steps in one answer". Each case is one
  run_turn. Writes results/<date>_<preset>_<fingerprint>_<set>.jsonl + .csv (hand-scoring columns) +
  _settings.json. Auto columns: retrieved_ids, retrieval_hit (any gold id in top_k), cited_ids,
  unknown_menu_paths, unknown_bold_terms (hints, not verdicts), tokens, latency.
- eval_email.py: same for the e-mail drafter (tickets or golden as e-mails) -> decisions, retrieval_hit, warnings.
- judge_answers.py: LLM judge (default claude-opus-4-8) on a results .jsonl: correct / partly / wrong /
  handover, invented y/n, effort for e-mails; writes _judged-<model>.jsonl/.csv and prints 10 ids to hand-check.
  Known issue: some judge calls return no score (8/40, 4/40, 7/40 in the ticket runs).
- measure_search.py: hit@1/3/5, no model calls, raw vs enriched vs +glossary (golden; --tickets = blind).
- test_glossary.py + data/glossary_tests.csv: per-entry glossary help/hurt check.
- make_search_questions.py: generated data/search_questions.jsonl (gpt-4o, passage text only).
- Model comparison (the "3-model evaluation"): results/model_comparison_20261105.md: 11 gateway models on golden
  raw (results/corpus-raw_golden_<model>_*.csv), top 4 on golden enriched (corpus-enriched_*); recommendation
  claude-opus-4-8 > gemini-3.5-flash > gpt-5 (minimal), gpt-4o reference. Cost in cost_breakdown_20261105.md;
  business numbers and phased plan in project_analysis_20261105.md. step1_*/corpus-raw_golden_20261104-* are
  the first runs (older script).
- Measured so far: search golden raw hit@1/3/5 14/18/19 of 20, enriched + glossary 15/20/20; golden answers
  18/20 correct for the top 4 models (enriched).
- WARNING: the blind ticket set has already been run 3 times and judged (commit 73700c4: eval-baseline,
  eval-gemini-3.5-flash, email-draft), and ticket search hit rates were printed during development. Treat ticket
  numbers as no longer fully blind; do not tune on them.

What already works vs R1–R8 (see section 5 for status per requirement)
- Retrieval with citations: yes (BM25 + enrichment + glossary, [pXXXX] citations by prompt).
- Router: no (scope is only an instruction in the system prompt).
- Evidence gate: no (prompt says "hand over if passages do not answer"; a BM25 score threshold was tested and rejected).
- Menu-path check: partly: unknown_menu_paths() in eval_run.py, used as warnings in email_draft.py; not in
  run_turn, never blocks; regex gives false positives.
- PII masking: partly: email_draft.clean_email() (regex); not applied to chat / run_turn; names only in sign-offs.
- Hand-over / tickets: no ticket store; e-mail no_draft/partial + triage_note is the only hand-over.
- E-mail handling: mostly (draft_reply + Agent inbox + eval_email); missing per-question split and routing, language
  detection, loading tickets_tv e-mails in the UI.

## 4. Rules
- One engine, many front-ends: everything calls run_turn(). What is evaluated is exactly what is demoed.
- Every new behaviour is switchable in settings.json, so evaluation can compare it.
- Never tune on tickets_tv.csv (blind test, run once at the end). Keep golden_seed.csv unchanged.
- Never commit .env, secrets, logs/ or index/. Never log or store raw customer text.
- Never delete, move or rename files without my approval; when proposing removal, show the evidence.
- Plan before large changes; small commits; re-run the evaluation after changes that affect answers and report
  before/after numbers.

Team rules carried over from README.md (decided before this brief):
- Generated data (search questions, glossary, test queries) come from the corpus, the golden set or general
  knowledge, never from tickets. Glossary: map specific customer terms to rare manual terms; test every entry with
  test_glossary.py (one query it must help, one it must not hurt).
- Evaluation settings are fixed in eval_run.eval_settings() (temperature 0, 800 tokens, no memory); a prompt change
  changes the fingerprint, so earlier runs must be re-run to compare.
- Judge with a different model than the one that answered, and hand-check a sample.
- Logs store lengths, ids, tokens and fixed-list feedback only; never free text.
- The bot always discloses it is an AI (EU AI Act); e-mail drafts get the AI notice added by code, not by the model.

## 5. Scope (narrowed for the hackathon)

| Build | Shrink | Pitch only (not built) |
|---|---|---|
| R1 retrieval: cleaning, chunking, hybrid search (or BM25 + query rewrite if no embeddings) | Rerank only if hit@1 is weak | Approved-answer cache, guided troubleshooting |
| R2 router, evidence gate, hand-over, PII masking, menu-path check | Judge: hand-check ~20 answers, no formal agreement study | Robustness set of 60 rewordings |
| R3 evaluation: golden + extended (~20) + tickets blind once; model/preset comparison; trade-off chart; CSV for business team | R7 email: one function + one screen, draft mode only | Auto-send, helpdesk/IMAP connectors |
| R6 tickets (simple store) and R8 demo UI | R9 bounded agent: build only if R1–R3 are done; compare with pipeline | 7-day repeat-contact linking, voice/IVR |

Status (audit 5 Nov 2026):

| Req | Status | Done | Missing |
|---|---|---|---|
| R1 retrieval | partly | BM25, search-only enrichment, glossary, follow-up search, citations, measure_search.py | ">" restoration, chunking of p0106/p0210/p0068, near-dup collapse, vectors + RRF, query rewrite |
| R2 safety | partly | scope + "hand over if not covered" in prompt; menu-path + PII regex in email_draft.py only | router, evidence gate, menu check and PII inside run_turn, hand-over flow, trap-passage tests |
| R3 evaluation | partly | eval_run / eval_email / judge_answers, 11-model comparison, cost per answer, search hit@k | extended set (~20 incl. out of scope), MRR + extra acceptable ids, routing confusion matrix, CIs in code, business CSV, trade-off chart |
| R6 tickets | not started | – | store, status lifecycle, "Did this help?" (only api.py /feedback thumbs) |
| R7 email | mostly | draft_reply, Agent inbox page (edit/send/discard), eval_email, 5 demo e-mails | per-question split + routing, language detection, ~10 synthetic test e-mails, load tickets_tv e-mails in UI |
| R8 demo UI | not started | app.py chat + Agent inbox page to reuse | split screen, agent console, trace strip, scenarios, replay, presenter mode |
| R9 agent | not started | – | all |

## 6. Requirements

### R1 Retrieval – must
- Restore ">" in menu paths; split long passages (p0106, p0210, p0068) into chunks keeping the parent id;
  collapse near-duplicates (p0216/p0217, p0107/p0108, p0124/p0125).
- Hybrid search (BM25 + vectors, RRF). No embeddings endpoint on the gateway -> small local embedding model.
- Query rewrite into manual vocabulary (known misses: "cut off at the edges" -> Fit to Screen;
  "control my soundbar" -> Anynet+ / HDMI-CEC).
- Acceptance: hit@5 >= keyword baseline (golden 19/20, tickets 34/40) and better hit@1.

### R2 Answering and safety – must
- Router: in scope / out of scope / unclear. Out of scope -> hand-over. Unclear -> one clarifying question.
- Evidence gate; grounded answers with citations; keep "contact support if…".
- Menu-path check: any menu path in an answer that is not in the corpus menu tree -> block or hand over.
- PII masking before any LLM call. Trap passages p0020 (warranty) and p0138 (repair) must not produce
  warranty or repair answers.

### R3 Evaluation – must
- Runner: test set x preset -> results/<date>_<preset>_<fingerprint>.jsonl. Extend the existing 3-model evaluation.
- Retrieval: hit@1, hit@5, MRR, with a hand-checked list of extra acceptable passages.
- Answers: correct / partly correct / wrong, by meaning against must_include; faithfulness; citation precision.
- Routing: confusion matrix answer / clarify / hand-over; hand-over precision and recall.
- Cost and speed per answer from the token log.
- Report counts with confidence intervals; export a CSV of measured rates for the business team.
- Trade-off chart: answered share vs wrong-answer rate across gate thresholds (for the presentation).

### R6 Tickets – must
- Every conversation is a ticket from the first message. Fields follow tickets_tv.csv plus bot fields:
  ticket_id, created, channel, model_series, category, type, priority, subject, summary (masked), steps_tried,
  source_passage_ids, status, route, bot_confidence, turns, tokens, cost_eur, resolution_confirmed,
  related_ticket_id, preset, settings_fingerprint.
- Status: BOT_ACTIVE -> RESOLVED_BY_BOT | HANDED_OVER -> RESOLVED_BY_AGENT | TIER2; ABANDONED = unknown,
  never counted as resolved. Bot hand-over and tier-2 escalation are separate.
- Storage: tickets.jsonl or SQLite; created and updated in run_turn(); only masked summaries stored.
- "Did this help?" (yes/no) sets resolution_confirmed.

### R7 Email – should (reduced)
- handle_email(subject, body, thread) -> decision + draft: strip signatures and quoted replies, mask PII
  (names, e-mail, phone, address, serial, order numbers), split into questions, route each question,
  answer in-scope parts, hand over the rest in the same reply, draft for agent approval (no auto-send).
- Non-English email -> hand over and log the language.
- Test with the email/web-form tickets (blind) and ~10 own synthetic emails (signature + quoted thread,
  multiple questions, mixed with warranty, PII-heavy, German).

### R8 Demo UI – must
Streamlit, wide layout, designed for a large projector (test at 1920x1080). No business or cost numbers on
screen (they are in the separate presentation).

Live demo page (split screen):
- Left, CUSTOMER: permanent "You're chatting with an AI assistant" notice; large-font chat bubbles; sources as
  small chips (p0223) with the passage text on hover/expand; "Did this help?" buttons after answers.
- Right, AGENT CONSOLE: live queue of HANDED_OVER tickets (id, subject, category, priority); selecting one shows
  summary, steps tried, sources and a suggested reply (agent assist). New tickets appear without a page reload
  of the customer side.
- Bottom, WHY THIS ANSWER strip, per turn: Router, Search, Gate, Menu paths, PII masked, each as passed (green),
  handed over (amber) or blocked (red), with a one-line reason. Collapsible. No cost figures here.

Email page: paste an email or load one from tickets_tv.csv (email / web-form) -> masked text, detected questions,
decision per question, draft reply with Approve / Edit / Reject.

Sidebar (collapsed in presenter mode):
- Demo scenario buttons, each fills and sends a message:
  1 How-to with sources ("Which picture mode is easiest on the eyes?")
  2 Catches a mistake (TV-0027: recording to a USB stick)
  3 Knows its limits (warranty question -> hand-over -> ticket in queue)
  4 Refuses to invent (question tempting an invented menu -> menu-path check blocks)
  5 Privacy (message with e-mail address and serial number -> shown masked in the trace)
  6 Email (two questions + warranty request) -> opens the Email page with it loaded
  Scenarios the engine cannot do yet are shown disabled with "coming soon", and enabled automatically
  once the engine supports them.
- Reset demo: clears chat, trace and the demo ticket queue.
- Replay mode: record each scenario once with the live gateway to demo/replays/<scenario>.json; when enabled,
  scenarios replay from file and the trace shows "replay". Fallback if the gateway or network fails.
- Presenter mode: larger fonts, hides settings and debug output.
- Settings expander: existing preset system (model, temperature, retrieval options).

Look: fictional "Smart Tech" brand text, one accent colour, clean cards; colour only for meaning.

### R9 Bounded agent – could (only after R1–R3)
- Settings mode "agent": the model chooses one action per step from search_manual(query), ask_customer(question),
  create_handover(summary), check_menu_path(path); returned as JSON if the gateway has no tool calling.
- Max 3 steps per message; tools read-only except create_handover; evidence gate and menu-path check run after
  the model regardless of its choice; every step logged and shown in the trace.
- Evaluate "pipeline" vs "agent" on the same sets (quality, wrong answers, cost, latency) before choosing.

## 7. Priorities
1. R1 retrieval + retrieval metrics.
2. R2 router, gate, menu-path check, PII, hand-over + R6 tickets.
3. R3 evaluation: extended set, comparison, trade-off chart, CSV export.
4. R8 demo UI (split screen, trace strip, scenarios, replay, presenter mode).
5. R7 email function + Email page.
6. R9 bounded agent, if time allows.

## 8. Definition of done for any change
- `python3 run.py ui` and `python3 run.py chat` work.
- Evaluation re-run on golden + extended (and email set if affected); before/after numbers reported.
- No secrets, raw customer text or generated indexes committed. README updated if commands or structure changed.