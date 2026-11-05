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
| `python3 run.py api` | Start the web API for the Lovable UI at http://localhost:8000 (docs at `/docs`) |
| `python3 run.py test-gateway` | Send one test message to the gateway |

To add a task, add one line to `TASKS` at the top of `run.py`.

### Evaluation and search scripts

Not `run.py` tasks yet; run them with the project's Python:

| Command | What it does |
|---|---|
| `.venv/bin/python measure_search.py` | Search quality only, no model calls: is the right passage in the top 1 / 3 / 5? Raw vs enriched vs enriched + glossary, golden set only. `--tickets` adds the blind ticket set: final run only |
| `.venv/bin/python eval_run.py --dry-run` | Show what the model would receive for the first question; no call, no credentials needed |
| `.venv/bin/python eval_run.py [--preset NAME] [--corpus none\|raw\|enriched] [--set golden\|tickets] [--limit N]` | Run a test set with a preset (default `baseline`); `--corpus` overrides the preset's search |
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
| `ACCESS_CODE` | for the API | | Code testers enter in the Lovable UI; every API request must send it |
| `API_PRESET` | no | `gemini-3.5-flash` | Preset the API uses when the UI does not pick one (default: `default_preset`) |
| `API_PRESETS` | no | `baseline,gemini-3.5-flash,gpt-5-minimal` | Presets testers may pick in the UI (default: all) |
| `API_MODELS` | no | `gpt-4o,gemini-3.5-flash,gpt-5` | Models testers may pick in the settings panel (default: all in `config.MODEL_RULES`) |
| `ALLOW_PRIVATE_NETWORK` | no | `1` | Lets a hosted page call the API on your own computer (local testing only) |
| `ALLOWED_ORIGIN_REGEX` | no | | Sites allowed to call the API from a browser (default: Lovable and localhost) |

## Settings and presets

All assistant settings live in `settings.json`: `defaults` plus named presets (`baseline` and `strict-0.0` on gpt-4o, `gemini-3.5-flash` and `gpt-5-minimal` with the parameters those models need, see `results/model_comparison_20261105.md`). A preset stores only what differs from the defaults. `config.py` loads them, and recreates `settings.json` from built-in defaults if it is missing.

- **Search settings** are part of each preset: `use_manual`, `search_questions` (also search the generated customer questions), `glossary` (add manual words for customer words from `data/glossary.csv`), `top_k` and `follow_up_search`. All presets use the raw search today; a preset with `"search_questions": true, "glossary": true` gives the enriched search in every front end.
- **Fingerprint:** every combination of settings gets an 8-character code, shown in the UI sidebar and written to every log line. The same fingerprint means the same model, temperature, max tokens, conversation memory, system prompt, AI disclosure, extra parameters and search settings. Since 5 November the search settings are included, so all fingerprints changed once (`baseline` is now `f7a3ba0d`; the earlier evaluation fingerprint `a9a0f383` is now `703d30f8` for the raw search and `f44b3bd4` for the enriched search). Earlier runs stay comparable through their `_settings.json` files.
- **Not in the fingerprint:** the corpus and glossary file contents, the passage instructions in `assistant.py`, and which model version the gateway serves under the name `gpt-4o`.
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
| `api.py` | Web API (FastAPI) for the Lovable UI: `/config`, `/chat`, `/feedback`, protected by an access code |
| `Dockerfile`, `requirements-api.txt` | Container for hosting the API (no Streamlit) |
| `run.py` | npm-style task runner |
| `eval_run.py` | Evaluation: test set x preset, with `--corpus` for the corpus comparison steps |
| `measure_search.py` | Search hit rates, no model calls |
| `make_search_questions.py` | Generates `data/search_questions.jsonl` |
| `data/` | The organisers' files plus our generated search questions (see Data and licences) |
| `results/` | Evaluation runs: one CSV and one settings file per run |
| `requirements.txt` | Python packages |
| `.env.example` | Template for `.env` |

## How an answer is made

1. The customer's **current message** is searched in the manual (`retrieval.py`, BM25 keyword search). The 3 best passages are taken. If the message matches the manual poorly (best score below 8.5, e.g. "I tried that but it didn't help"), it is treated as a follow-up and searched together with the customer's last 2 earlier messages. A new question scores higher and is searched on its own, so a change of topic is not mixed with the old one.
2. The passages go into the **current user message, before the question**, with instructions: answer only from these passages, read menu paths without arrows ("Settings Picture Picture Mode") as Settings > Picture > Picture Mode, cite the passage ids, and if the passages do not answer the question, say so and offer a human colleague. The system prompt itself is unchanged.
3. If **no passage matches**, the model is told so explicitly, so that it hands over instead of answering from its own knowledge.
4. The conversation history keeps the customer's **plain messages**; earlier passages are not resent, so token cost does not grow with every turn.
5. If `data/corpus.jsonl` is **missing**, the assistant stops with a clear error rather than answering without the manual.

Known limits: BM25 matches words, not meaning. The follow-up threshold (8.5) was set on the golden questions and 10 follow-up phrases: real questions scored 9.8 or more, follow-ups 7.5 or less. A follow-up with strong manual words of its own ("still no sound from the soundbar") is searched on its own. The UI uses the raw corpus; the enriched search (passages plus generated questions) is used in the evaluation, and switching the UI to it is an open team decision.

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

## Web API (for the Lovable UI)

The Lovable app is only the front end. It calls `api.py`, which runs the same engine (`assistant.run_turn`) as the Streamlit UI and the evaluation, so what testers see is what we measured. No database is needed.

- **Access:** every request except `/health` needs the header `X-Access-Code` (set `ACCESS_CODE` in `.env`). The gateway credentials stay on the server and never go to the browser or to Lovable.
- **Conversation state** lives in the browser. Send the `history` from the previous `/chat` response with the next message. The returned history is trimmed to the preset's conversation memory, so keep your own list for display.
- **Browsers** may call the API only from Lovable sites and localhost (`ALLOWED_ORIGIN_REGEX`).

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | no code needed | `{"ok": true}` |
| `GET /config` | | AI disclosure text, default preset, presets with their values (model, temperature, max tokens, memory, system prompt), models testers can pick (with notes and rules), limits, search |
| `POST /chat` | `{"message", "history": [{"role", "content"}], "conversation_id"?, "preset"?, "settings"?: {"model", "temperature", "max_tokens", "history_turns", "system_prompt"}}`; `settings` holds only the changes from the preset | `answer`, `history`, `conversation_id`, `turn`, `preset` ("name (edited)" when changed), `model`, `fingerprint`, `retrieved_ids`, `usage`, `latency_s`, `settings` (the effective settings) |
| `POST /feedback` | `{"conversation_id", "turn", "rating": "up"\|"down", "reason"?, "preset"?}`; reason is one of `wrong`, `incomplete`, `invented`, `should_hand_over`, `too_long`, `other` | `{"ok": true}` |

Limits: messages up to 2,000 characters, history up to 40 messages, roles `user` and `assistant` only; temperature 0–1, max tokens 50–4,000, memory 0–20 turns, system prompt up to 8,000 characters.

**Model rules:** testers can pick any model in `config.MODEL_RULES` (restrict with `API_MODELS`). The API gives each model what it needs to answer completely: gpt-5 and gpt-5-nano always get temperature 1 and `reasoningEffort: minimal`, the Gemini Flash models `minimal`, the Gemini Pro models at least 3,000 tokens, claude-opus-4-6 `none`. Options for another model (e.g. Gemini's reasoning effort) are dropped when the model changes. Changed settings get their own fingerprint, so they show up separately in the log.

**Hosting:** Lovable's hosted app cannot reach `localhost`. For a short test session, expose the local API with a tunnel. For team testing over several days, run the container on a small cloud service (e.g. Azure Container Apps in Sweden Central, next to the gateway): `docker build -t smarttech-api .` and set `CLIENT_ID`, `CLIENT_SECRET` and `ACCESS_CODE` as secrets there. Logs inside the container are lost when it is replaced, so mount a volume on `/app/logs`.

## Notes on the gateway

- The LLM runs behind a gateway hosted on Azure Container Apps in **Sweden Central** (EU).
- The gateway accepts only the roles `user` and `assistant`, not `system`. `llm_client.py` therefore moves the system instructions to the start of the first user message on every call.
- The API uses camelCase parameter names (`maxTokens`).

## Logging and privacy

- Every answer is logged to `logs/conversation_log.jsonl`: source (`ui`, `cli`, `api` or `eval-...`), preset and settings fingerprint, model and settings, `corpus` (`none`, `raw` or `enriched`), `retrieved_ids` (the passage ids sent to the model), `search_used_earlier` (true when a follow-up was searched with earlier messages), input and output tokens, and response time. The token log is the basis for the cost-per-answer figure in the business case.
- Passage ids are not personal data, so logging them is safe.
- The log stores **only the length** of messages, never the customer's text.
- Tester ratings from the API go to `logs/feedback_log.jsonl`: conversation id, turn, up or down, a reason from a fixed list, and the preset. No free text, so no personal data.
- The assistant tells users it is an AI (EU AI Act) and asks them not to share personal data (GDPR).
- `logs/` and `.env` are git-ignored.

## Evaluation

We compare three versions of the assistant in which **only the corpus changes**:

| Step | `--corpus` | What the model gets |
|---|---|---|
| 1 | `none` | No manual: GPT-4o's own knowledge |
| 2 | `raw` | The 3 best passages from the original corpus |
| 3 | `enriched` | The same, but the search also uses the generated customer-style questions and the glossary |

- **Fixed settings:** every run uses the `eval` settings defined in `eval_run.py` on top of the chosen preset (default `baseline`): temperature 0, max 800 tokens, no conversation memory, and the preset's prompt plus one line asking for all relevant steps in one answer. The preset name in results is `eval-<preset>`. If the prompt in `settings.json` changes, the fingerprint changes and earlier steps must be rerun.
- **Test sets:** `golden_seed.csv` (20 questions) is the development set, run as often as needed. `tickets_tv.csv` (40) is held out: run once per step, only after the prompt is frozen, and never inspect ticket misses or use tickets to write prompts, questions or glossary entries. Ticket *search* hit rates were printed during development until 5 November, and glossary entries written from tickets were removed that day; the answer-level ticket run has not been done. Our own out-of-scope set (warranty, repairs, returns, orders, accessories, prices) is still to be written.
- **Results files:** each run writes `results/<date>_<preset>_<fingerprint>_<set>.jsonl` (one line per case, for scripts) and a `.csv` with the same name: one row per question (retrieved ids, search hit, cited ids, hints for menu paths and bold terms not found in the manual, tokens) and empty columns for scoring by hand: correct / partly / wrong / hand-over, and invented content y/n. The hints are pointers for the scorer, not verdicts. A `_settings.json` file records the exact settings.
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

1. **Retrieval (RAG)**, done: BM25, 3 best passages, cited passage ids, enriched search with generated questions. Follow-ups are searched together with earlier messages (5 November). Glossary for named concepts (`data/glossary.csv`, from the golden set only). Next: see `results/project_analysis_20261105.md` (ingest clean-up, hybrid search, query rewriting, rerank).
2. **Scope router**, not started: in scope, out of scope (warranty, orders, prices) or unclear. Also pending: the prompt's scope wording (hand over when answering needs the customer's own account, order or contract data).
3. **Evidence gate and grounding check**, not started: answer only when the manual supports it, otherwise hand over. Tests showed that a keyword-score threshold alone is not enough.
4. **Guided troubleshooting**: the prompt gives one or two checks at a time; follow-up messages are now searched with the earlier question (in 17 of 20 test conversations the assistant kept troubleshooting instead of handing over).
5. **Hand-over to an agent** with a ticket summary; **agent-assist view** for hotline agents. Not started.
6. **Evaluation**: pipeline done; steps 1 and 2 run on the golden set, step 3 search measured. Still to do: agree the scoring rule, freeze the prompt, write the out-of-scope set, run the tickets once per step.

## Data and licences

- `data/corpus.jsonl` (204 passages), `data/golden_seed.csv` (20 questions) and `data/tickets_tv.csv` (40 tickets) are the organisers' files. The corpus is based on RAGBench (`emanual` subset), CC BY 4.0, modified by the hackathon organisers. The golden questions, tickets and client fact sheet were written by the organisers for this event.
- `data/search_questions.jsonl` was generated by us with GPT-4o from the corpus passages.
- `results/step1_*` files come from the first step-1 script (since replaced by `eval_run.py --corpus none`) and are kept as the original step-1 runs.
