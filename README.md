# Smart Tech Support Assistant (Hackathon, Track A)

An AI support assistant for **Smart Tech Inc.**, a fictional European smart-TV maker. It answers TV how-to and troubleshooting questions and hands everything else to a human agent. The goal is to lower cost per contact by at least 15% (from EUR 7.37 to EUR 6.26) without adding wrong or invented advice.

> **Status: working prototype with retrieval.** Chat (command line and web UI) on the EU-hosted LLM gateway, answering from the TV manual: keyword search (BM25) finds the 3 best passages for each question, and answers cite their passage ids. Not built yet: scope router, evidence gate, hand-over summary and agent-assist view (see Roadmap).

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/biswaskc57/hackathon-chatbot.git
cd hackathon-chatbot
cp .env.example .env          # then fill in CLIENT_ID and CLIENT_SECRET
python3 run.py build          # once: creates .venv and installs the packages
python3 run.py ui             # opens the web UI at http://localhost:8501
```

Ask the project manager for the gateway credentials. Never commit `.env`.

The organisers' data files are already in `data/`. Without `data/corpus.jsonl` the assistant stops with an error instead of answering without the manual.

## Tasks

`run.py` works like `npm run`. It uses the project's `.venv` by itself, so you don't need to activate it.

| Command | What it does |
|---|---|
| `python3 run.py` | List all tasks |
| `python3 run.py build` | Create `.venv` and install `requirements.txt` |
| `python3 run.py ui` | Start the Streamlit web UI |
| `python3 run.py chat` | Start the command-line chat |
| `python3 run.py test-gateway` | Send one test message to the gateway |

To add a task, add one line to `TASKS` at the top of `run.py`.

### Evaluation and search scripts

Not `run.py` tasks yet; run them with the project's Python:

| Command | What it does |
|---|---|
| `.venv/bin/python measure_search.py` | Search quality only, no model calls: is the right passage in the top 1 / 3 / 5? Raw vs enriched, golden set and tickets (tickets as totals only) |
| `.venv/bin/python eval_run.py --corpus raw --set golden --dry-run` | Show what the model would receive for the first question; no call, no credentials needed |
| `.venv/bin/python eval_run.py --corpus none\|raw\|enriched --set golden\|tickets [--limit N]` | Run an evaluation step and write the results to `results/` |
| `... eval_run.py --corpus raw --model gpt-5 --params '{"temperature": 1, "reasoningEffort": "minimal"}'` | Same, with another model and the parameters it needs (changes the fingerprint). See `results/model_comparison_20261105.md` |
| `.venv/bin/python make_search_questions.py [--limit N]` | Generate customer-style search questions for each passage (needs the gateway; resumes where it stopped) |


## Configuration (`.env`)

| Variable | Required | Example | Meaning |
|---|---|---|---|
| `CLIENT_ID` | yes | | Gateway client ID |
| `CLIENT_SECRET` | yes | | Gateway client secret |
| `MODEL` | no | `gpt-4o` | Model for `run.py test-gateway` only. Answers use the model of the active preset in `settings.json` |
| `MODELS` | no | `gpt-4o,gpt-4.1` | Extra models offered in the UI dropdown (models used in presets are added automatically) |
| `LLM_BASE_URL` | no | | Override the gateway address |

## Settings and presets

All assistant settings live in `settings.json`: `defaults` plus named presets (`baseline`, `strict-0.0`). A preset stores only what differs from the defaults. `config.py` loads them, and recreates `settings.json` from built-in defaults if it is missing.

- **Fingerprint:** every combination of settings gets an 8-character code, shown in the UI sidebar and written to every log line. The same fingerprint means the same model, temperature, max tokens, conversation memory, system prompt, AI disclosure and extra parameters.
- **Not in the fingerprint:** the corpus and search (logged separately as `corpus` and `retrieved_ids`), the passage instructions in `assistant.py`, and which model version the gateway serves under the name `gpt-4o`.
- **The system prompt exists twice:** in `settings.json` (used) and in `config.py` (fallback). Change both.

## Project structure

| File | Purpose |
|---|---|
| `llm_client.py` | Client for the LLM gateway: retries, readable errors, token usage parsing; moves system instructions into the first user message |
| `config.py` | Settings, presets from `settings.json`, fingerprint |
| `settings.json` | Default settings and named presets (model, temperature, system prompt, ...) |
| `assistant.py` | Conversation engine shared by the UI, the command line and the evaluation: searches the manual, builds the messages, calls the gateway, logs the turn |
| `retrieval.py` | BM25 keyword search over the manual passages; optional search-only questions per passage |
| `chat.py` | Command-line chat (`--preset`, `--list-presets`) |
| `app.py` | Streamlit web UI with presets, a settings panel and session statistics |
| `run.py` | npm-style task runner |
| `eval_run.py` | Evaluation for every comparison step (`--corpus none`, `raw` or `enriched`) |
| `measure_search.py` | Search hit rates, no model calls |
| `make_search_questions.py` | Generates `data/search_questions.jsonl` |
| `data/` | The organisers' files plus our generated search questions (see Data and licences) |
| `results/` | Evaluation runs: one CSV and one settings file per run |
| `requirements.txt` | Python packages |
| `.env.example` | Template for `.env` |

## How an answer is made

1. The customer's **current message** is searched in the manual (`retrieval.py`, BM25 keyword search). The 3 best passages are taken.
2. The passages go into the **current user message, before the question**, with instructions: answer only from these passages, read menu paths without arrows ("Settings Picture Picture Mode") as Settings > Picture > Picture Mode, cite the passage ids, and if the passages do not answer the question, say so and offer a human colleague. The system prompt itself is unchanged.
3. If **no passage matches**, the model is told so explicitly, so that it hands over instead of answering from its own knowledge.
4. The conversation history keeps the customer's **plain messages**; earlier passages are not resent, so token cost does not grow with every turn.
5. If `data/corpus.jsonl` is **missing**, the assistant stops with a clear error rather than answering without the manual.

Known limits: the search looks only at the current message, so short follow-ups ("still nothing") search poorly; BM25 matches words, not meaning. The UI uses the raw corpus; the enriched search (passages plus generated questions) is used in the evaluation, and switching the UI to it is an open team decision.

## UI settings

The sidebar changes these settings live; each change applies from the next message:

- Model (dropdown, or type any model name)
- Temperature (0–0.2 recommended for support answers)
- Maximum answer length (`maxTokens`)
- Conversation memory (how many earlier question-and-answer pairs are resent)
- System prompt (editable)
- Extra gateway parameters as JSON, e.g. `{"topP": 0.9}`
- AI disclosure text shown at the start of each conversation
- Preset selector, **Reset to preset** and **Save as preset** (saved to `settings.json`); the sidebar shows the active preset and its fingerprint

## Notes on the gateway

- The LLM runs behind a gateway hosted on Azure Container Apps in **Sweden Central** (EU).
- The gateway accepts only the roles `user` and `assistant`, not `system`. `llm_client.py` therefore moves the system instructions to the start of the first user message on every call.
- The API uses camelCase parameter names (`maxTokens`).

## Logging and privacy

- Every answer is logged to `logs/conversation_log.jsonl`: source (`ui`, `cli` or `eval-...`), preset and settings fingerprint, model and settings, `corpus` (`none`, `raw` or `enriched`), `retrieved_ids` (the passage ids sent to the model), input and output tokens, and response time. The token log is the basis for the cost-per-answer figure in the business case.
- Passage ids are not personal data, so logging them is safe.
- The log stores **only the length** of messages, never the customer's text.
- The assistant tells users it is an AI (EU AI Act) and asks them not to share personal data (GDPR).
- `logs/` and `.env` are git-ignored.

## Evaluation

We compare three versions of the assistant in which **only the corpus changes**:

| Step | `--corpus` | What the model gets |
|---|---|---|
| 1 | `none` | No manual: GPT-4o's own knowledge |
| 2 | `raw` | The 3 best passages from the original corpus |
| 3 | `enriched` | The same, but the search also uses the generated customer-style questions |

- **Fixed settings:** every run uses the `eval` settings defined in `eval_run.py` on top of the `baseline` preset: temperature 0, max 800 tokens, no conversation memory, and the baseline prompt plus one line asking for all relevant steps in one answer. Fingerprint `a9a0f383`. If the prompt in `settings.json` changes, the fingerprint changes and earlier steps must be rerun.
- **Test sets:** `golden_seed.csv` (20 questions) is the development set, run as often as needed. `tickets_tv.csv` (40) is held out: run once per step, only after the prompt is frozen, and never inspect ticket misses or use tickets to write prompts, questions or glossary entries. Our own out-of-scope set (warranty, repairs, returns, orders, accessories, prices) is still to be written.
- **Results files:** each run writes `results/corpus-<step>_<set>_<time>.csv` with one row per question (retrieved ids, search hit, cited ids, hints for menu paths and bold terms not found in the manual, tokens) and empty columns for scoring by hand: correct / partly / wrong / hand-over, and invented content y/n. The hints are pointers for the scorer, not verdicts. A `_settings.json` file records the exact settings.
- **Customer-style questions:** `data/search_questions.jsonl` holds 5 questions per passage, generated by GPT-4o from the passage text only (never from the tickets or golden questions). They are used for search only and never shown to customers. One-off cost: 105,972 input and 16,045 output tokens, about $0.43 at list price. Spot-check them and set `"reviewed": true` on the ones checked.

### Results so far (4 to 5 November 2026)

| Search (right passage found) | Top 1 | Top 3 | Top 5 |
|---|---|---|---|
| Golden, raw | 14/20 | 18/20 | 19/20 |
| Golden, enriched | 14/20 | 19/20 | 19/20 |
| Tickets, raw | 26/40 | 33/40 | 35/40 |
| Tickets, enriched | 27/40 | 35/40 | 38/40 |

Answer quality on the golden set, step 2 (one scorer, first pass, scoring rule not yet agreed): 13 correct, 5 correct with small additions from outside the manual, 1 hand-over (Q12), 1 wrong (Q14). In step 1 the model invents features that are not in the manual, such as an "Eye Comfort" picture mode. Cost per answer at list price: about $0.003 in step 1 and $0.0045 in step 2. These are small samples: they illustrate the effect and support no statistical claims.

## Roadmap

1. **Retrieval (RAG)**, done: BM25, 3 best passages, cited passage ids, enriched search with generated questions. Next: a glossary for named concepts (e.g. soundbar or set-top box → Anynet+, Universal Remote), searching follow-ups together with the previous question, and deciding whether the UI uses the enriched search.
2. **Scope router**, not started: in scope, out of scope (warranty, orders, prices) or unclear. Also pending: the prompt's scope wording (hand over when answering needs the customer's own account, order or contract data).
3. **Evidence gate and grounding check**, not started: answer only when the manual supports it, otherwise hand over. Tests showed that a keyword-score threshold alone is not enough.
4. **Guided troubleshooting**: the prompt gives one or two checks at a time; search on follow-up messages still needs improving.
5. **Hand-over to an agent** with a ticket summary; **agent-assist view** for hotline agents. Not started.
6. **Evaluation**: pipeline done; steps 1 and 2 run on the golden set, step 3 search measured. Still to do: agree the scoring rule, freeze the prompt, write the out-of-scope set, run the tickets once per step.

## Data and licences

- `data/corpus.jsonl` (204 passages), `data/golden_seed.csv` (20 questions) and `data/tickets_tv.csv` (40 tickets) are the organisers' files. The corpus is based on RAGBench (`emanual` subset), CC BY 4.0, modified by the hackathon organisers. The golden questions, tickets and client fact sheet were written by the organisers for this event.
- `data/search_questions.jsonl` was generated by us with GPT-4o from the corpus passages.
- `results/step1_*` files come from the first step-1 script (since replaced by `eval_run.py --corpus none`) and are kept as the original step-1 runs.
