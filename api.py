"""Web API for the Lovable chat UI (or any other front end). Same engine as the Streamlit UI and the evaluation.

Run:  python3 run.py api        http://localhost:8000, interactive docs at /docs

- Every request except /health needs the header X-Access-Code (ACCESS_CODE in .env). Share the code with
  testers; the gateway credentials never leave this server.
- No database: the conversation lives in the browser. Each /chat call sends the history and gets the updated
  history back. Turns are logged by assistant.run_turn (lengths only, never the customer's text).
- /feedback stores a thumbs up or down and an optional reason from a fixed list, again without any text.
"""

import hmac
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from assistant import LLMError, new_conversation_id, run_turn
from config import MODEL_RULES, Settings, apply_model_rules, default_preset, list_presets, load_settings
from llm_client import APIClient

load_dotenv()

ACCESS_CODE = os.getenv("ACCESS_CODE", "")
DEFAULT_PRESET = os.getenv("API_PRESET") or default_preset()   # preset used when the UI does not pick one
# Presets testers may choose in the UI. Empty: all presets in settings.json.
ALLOWED_PRESETS = [p.strip() for p in os.getenv("API_PRESETS", "").split(",") if p.strip()]
# Models testers may pick in the settings panel. Empty: every model in config.MODEL_RULES.
ALLOWED_MODELS = [m.strip() for m in os.getenv("API_MODELS", "").split(",") if m.strip() in MODEL_RULES] or list(MODEL_RULES)
LIMITS = {"temperature": [0.0, 1.0], "max_tokens": [50, 4000], "history_turns": [0, 20], "system_prompt_chars": 8000}
# Browsers may call the API only from these sites: Lovable previews and published apps, and localhost.
ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX",
    r"https://([a-z0-9-]+\.)*(lovable\.app|lovableproject\.com|lovable\.dev)|http://(localhost|127\.0\.0\.1)(:\d+)?",
)
# Lets a hosted page (the Lovable preview) call this API on your own computer (Chrome's Private Network Access).
# Only for local testing; the access code is still required.
ALLOW_PRIVATE_NETWORK = os.getenv("ALLOW_PRIVATE_NETWORK", "") == "1"
FEEDBACK_LOG = Path(__file__).resolve().parent / "logs" / "feedback_log.jsonl"

app = FastAPI(title="Smart Tech Support Assistant API", version="1")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ORIGIN_REGEX,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Access-Code"],
    allow_private_network=ALLOW_PRIVATE_NETWORK,
)

_client: APIClient | None = None


def client() -> APIClient:
    global _client
    if _client is None:
        _client = APIClient()  # reads CLIENT_ID and CLIENT_SECRET from the environment
    return _client


def require_access_code(x_access_code: str = Header(default="")) -> None:
    if not ACCESS_CODE:
        raise HTTPException(503, "The server has no ACCESS_CODE set.")
    if not hmac.compare_digest(x_access_code.encode(), ACCESS_CODE.encode()):
        raise HTTPException(401, "Wrong or missing access code.")


def presets() -> list[str]:
    available = list_presets()
    return [p for p in ALLOWED_PRESETS if p in available] if ALLOWED_PRESETS else available


# ---------- request and response shapes ----------
class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class SettingsOverride(BaseModel):
    """Changes on top of the preset, from the UI's settings panel. Leave a field out to keep the preset's value."""
    model: str | None = Field(default=None, max_length=60)
    temperature: float | None = Field(default=None, ge=LIMITS["temperature"][0], le=LIMITS["temperature"][1])
    max_tokens: int | None = Field(default=None, ge=LIMITS["max_tokens"][0], le=LIMITS["max_tokens"][1])
    history_turns: int | None = Field(default=None, ge=LIMITS["history_turns"][0], le=LIMITS["history_turns"][1])
    system_prompt: str | None = Field(default=None, min_length=1, max_length=LIMITS["system_prompt_chars"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[Message] = Field(default_factory=list, max_length=40)
    conversation_id: str | None = Field(default=None, max_length=40)
    preset: str | None = None
    settings: SettingsOverride | None = None


class EffectiveSettings(BaseModel):
    """The settings actually used for the answer, after the model's own rules were applied."""
    model: str
    temperature: float
    max_tokens: int
    history_turns: int
    extra_params: dict
    edited: bool          # true when they differ from the preset


class Usage(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class ChatResponse(BaseModel):
    answer: str
    history: list[Message]
    conversation_id: str
    turn: int
    preset: str
    model: str
    fingerprint: str
    retrieved_ids: list[str] | None
    usage: Usage
    latency_s: float
    settings: EffectiveSettings


class FeedbackRequest(BaseModel):
    conversation_id: str = Field(max_length=40)
    turn: int = Field(ge=1, le=100)
    rating: Literal["up", "down"]
    reason: Literal["wrong", "incomplete", "invented", "should_hand_over", "too_long", "other"] | None = None
    preset: str | None = None


# ---------- endpoints ----------
@app.get("/health")
def health() -> dict:
    return {"ok": True}


def preset_values(s: Settings) -> dict:
    return {"model": s.model, "temperature": s.temperature, "max_tokens": s.max_tokens,
            "history_turns": s.history_turns, "system_prompt": s.system_prompt, "search": s.search_label()}


@app.get("/config", dependencies=[Depends(require_access_code)])
def get_config() -> dict:
    """What the UI needs before the first message: AI disclosure, presets with their values, models, limits."""
    s = load_settings(DEFAULT_PRESET)
    return {
        "ai_disclosure": s.ai_disclosure,
        "default_preset": DEFAULT_PRESET,
        "presets": [{"name": p, **preset_values(load_settings(p))} for p in presets()],
        "models": [{"name": m, "note": MODEL_RULES[m].get("note", ""),
                    "fixed_temperature": MODEL_RULES[m].get("temperature"),
                    "min_max_tokens": MODEL_RULES[m].get("min_max_tokens")} for m in ALLOWED_MODELS],
        "limits": LIMITS,
        "search": s.search_label(),   # of the default preset; each preset has its own search settings
    }


def build_settings(preset: str, override: SettingsOverride | None) -> tuple[Settings, bool]:
    """The preset, plus the UI's changes, plus the model's own rules. Returns (settings, edited)."""
    base = load_settings(preset)
    changes = override.model_dump(exclude_none=True) if override else {}
    if not changes:
        return base, False
    if "model" in changes and changes["model"] not in ALLOWED_MODELS:
        raise HTTPException(400, f"Unknown model '{changes['model']}'. Available: {', '.join(ALLOWED_MODELS)}")
    settings = apply_model_rules(replace(base, **changes))
    edited = settings.fingerprint() != base.fingerprint()
    return (replace(settings, preset=f"{preset} (edited)") if edited else base), edited


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_access_code)])
def chat(req: ChatRequest) -> ChatResponse:
    name = req.preset or DEFAULT_PRESET
    if name not in presets():
        raise HTTPException(400, f"Unknown preset '{name}'. Available: {', '.join(presets())}")
    settings, edited = build_settings(name, req.settings)
    history = [m.model_dump() for m in req.history]
    conversation_id = req.conversation_id or new_conversation_id()
    turn = sum(m["role"] == "user" for m in history) + 1
    try:
        result = run_turn(client(), history, req.message.strip(), settings, conversation_id, turn,
                          source="api")
    except LLMError as exc:
        raise HTTPException(502, f"The assistant could not answer: {exc}") from exc
    u = result.usage
    return ChatResponse(
        answer=result.answer,
        history=result.history,
        conversation_id=conversation_id,
        turn=turn,
        preset=settings.preset,
        model=settings.model,
        fingerprint=settings.fingerprint(),
        retrieved_ids=result.retrieved_ids,
        usage=Usage(input_tokens=u["input_tokens"], output_tokens=u["output_tokens"], total_tokens=u["total_tokens"]),
        latency_s=round(result.latency_s, 2),
        settings=EffectiveSettings(model=settings.model, temperature=settings.temperature,
                                   max_tokens=settings.max_tokens, history_turns=settings.history_turns,
                                   extra_params=settings.extra_params, edited=edited),
    )


@app.post("/feedback", dependencies=[Depends(require_access_code)])
def feedback(req: FeedbackRequest) -> dict:
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **req.model_dump()}
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}
