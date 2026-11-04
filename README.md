# Smart Tech Support Assistant (Hackathon, Track A)

An AI support assistant for **Smart Tech Inc.**, a fictional European smart-TV maker. It answers TV how-to and troubleshooting questions and hands everything else to a human agent. The goal is to lower cost per contact by at least 15% (from EUR 7.37 to EUR 6.26) without adding wrong or invented advice.

> **Status: early version.** A working chat (command line and web UI) on the EU-hosted LLM gateway. Retrieval from the TV manual (RAG) is the next step and is **not** in this version yet.

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

## Configuration (`.env`)

| Variable | Required | Example | Meaning |
|---|---|---|---|
| `CLIENT_ID` | yes | | Gateway client ID |
| `CLIENT_SECRET` | yes | | Gateway client secret |
| `MODEL` | no | `gpt-4o` | Default model (`gpt-4o` is the model in use) |
| `MODELS` | no | `gpt-4o,gpt-4.1` | Models offered in the UI dropdown |
| `LLM_BASE_URL` | no | | Override the gateway address |

## Project structure

| File | Purpose |
|---|---|
| `llm_client.py` | Client for the LLM gateway: retries, readable errors, token usage parsing |
| `chat.py` | Command-line chat; also holds the default system prompt and the AI disclosure text |
| `app.py` | Streamlit web UI with a model settings panel and session statistics |
| `run.py` | npm-style task runner |
| `requirements.txt` | Python packages |
| `.env.example` | Template for `.env` |

## UI settings

The sidebar changes these settings live; each change applies from the next message:

- Model (dropdown, or type any model name)
- Temperature (0–0.2 recommended for support answers)
- Maximum answer length (`maxTokens`)
- Conversation memory (how many earlier question-and-answer pairs are resent)
- System prompt (editable)
- Extra gateway parameters as JSON, e.g. `{"topP": 0.9}`

## Notes on the gateway

- The LLM runs behind a gateway hosted on Azure Container Apps in **Sweden Central** (EU).
- The gateway accepts only the roles `user` and `assistant`, not `system`. `llm_client.py` therefore moves the system instructions to the start of the first user message on every call.
- The API uses camelCase parameter names (`maxTokens`).

## Logging and privacy

- Every answer is logged to `logs/conversation_log.jsonl`: model, settings, input and output tokens, and response time. The token log is the basis for the cost-per-answer figure in the business case.
- The log stores **only the length** of messages, never the customer's text.
- The assistant tells users it is an AI (EU AI Act) and asks them not to share personal data (GDPR).
- `logs/` and `.env` are git-ignored.

## Roadmap

1. **Retrieval (RAG)** over the 204 manual passages, with cited passage ids
2. Scope router: in scope, out of scope (warranty, orders, prices) or unclear
3. Evidence gate and grounding check: answer only when the manual supports it, otherwise hand over
4. Guided troubleshooting: one check at a time, following the manual's troubleshooting structure
5. Hand-over to an agent with a ticket summary; agent-assist view for hotline agents
6. Evaluation on the golden set, our own extended test set and the tickets (blind run)

## Data and licences

The TV manual corpus is based on RAGBench (`emanual` subset), CC BY 4.0, modified by the hackathon organisers. The golden questions, tickets and client fact sheet were written by the organisers for this event.
