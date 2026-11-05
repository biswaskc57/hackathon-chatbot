"""All assistant settings in one place, with named presets stored in settings.json.

A preset only stores what differs from "defaults", so presets stay short and readable.
Used by chat.py, app.py and (later) the evaluation scripts.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

DEFAULT_SYSTEM_PROMPT = """You are the Smart Tech Inc. virtual support assistant for Smart Tech TVs.
You are an AI, and you never pretend to be a human.

Scope:
- Help with how-to questions (menus, settings, features) and troubleshooting (picture, sound, network, remote, apps, power).
- For warranty, repairs, returns, orders, accessories, prices, or account questions, say that a human colleague will help and do not answer them yourself.

Style:
- Be short and clear. Give numbered steps and menu paths like Settings > Picture > Picture Mode.
- For troubleshooting, give one or two checks at a time and ask whether they helped.
- If you are not sure, say so and offer to hand over to a human agent. Never invent menu names or features.
- Do not ask for personal data such as name, address, phone number or serial number."""

DEFAULT_AI_DISCLOSURE = (
    "Hi, I'm the Smart Tech virtual assistant, an AI. "
    "I can help with questions about your Smart Tech TV's settings and common problems. "
    "Please don't share personal details such as your name, address or serial number."
)


@dataclass
class Settings:
    model: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 600
    history_turns: int = 10          # earlier question/answer pairs resent with each call
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    ai_disclosure: str = DEFAULT_AI_DISCLOSURE
    extra_params: dict = field(default_factory=dict)  # sent as-is to the gateway, e.g. {"topP": 0.9}
    preset: str = "custom"           # name only; not part of the fingerprint

    def gateway_params(self) -> dict:
        """Parameters for the gateway call, in the gateway's own names."""
        return {"temperature": self.temperature, "maxTokens": int(self.max_tokens), **self.extra_params}

    def values(self) -> dict:
        """Everything that changes the assistant's behaviour (excludes the preset name)."""
        data = asdict(self)
        data.pop("preset")
        return data

    def fingerprint(self) -> str:
        """Short id of the exact settings, so log lines and evaluation runs can be compared."""
        raw = json.dumps(self.values(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


SETTING_NAMES = [f.name for f in fields(Settings) if f.name != "preset"]


# What each gateway model needs to give a complete answer (tested 5 November 2026, see
# results/model_comparison_20261105.md). temperature: the only value the model accepts (None: any).
# min_max_tokens: hidden reasoning uses the answer budget, so smaller limits cut answers off.
MODEL_RULES: dict[str, dict] = {
    "gpt-4o": {"note": "baseline"},
    "gemini-3.5-flash": {"extra": {"reasoningEffort": "minimal"}, "note": "best value"},
    "gpt-5": {"temperature": 1, "extra": {"reasoningEffort": "minimal"}, "note": "temperature fixed at 1"},
    "claude-opus-4-8": {"note": "safest, most expensive"},
    "gpt-5-nano": {"temperature": 1, "extra": {"reasoningEffort": "minimal"}, "note": "cheapest, weaker"},
    "gemini-3.1-flash-lite": {"extra": {"reasoningEffort": "minimal"}, "note": "cheap, weaker"},
    "claude-opus-4-6": {"extra": {"reasoningEffort": "none"}, "note": "older Opus"},
    "gemini-2.5-pro": {"min_max_tokens": 3000, "note": "slow (10+ s)"},
    "gemini-3.1-pro-preview": {"extra": {"reasoningEffort": "low"}, "min_max_tokens": 3000, "note": "slow (10+ s)"},
    "sonar-pro": {"note": "web-search model, not for manual-only answers"},
    "sonar-reasoning-pro": {"note": "web-search model, not for manual-only answers"},
}


def apply_model_rules(settings: Settings) -> Settings:
    """Give a model the options it needs: fixed temperature, reasoning effort, minimum answer budget.

    Extra parameters from another model (e.g. reasoningEffort for Gemini) are replaced by this model's own.
    Unknown models are returned unchanged.
    """
    rules = MODEL_RULES.get(settings.model)
    if rules is None:
        return settings
    changes: dict = {"extra_params": dict(rules.get("extra", {}))}
    if rules.get("temperature") is not None:
        changes["temperature"] = rules["temperature"]
    if rules.get("min_max_tokens"):
        changes["max_tokens"] = max(int(settings.max_tokens), rules["min_max_tokens"])
    return replace(settings, **changes)


def _default_store() -> dict:
    return {
        "default_preset": "baseline",
        "defaults": Settings().values(),
        "presets": {
            "baseline": {},
            "strict-0.0": {"temperature": 0.0, "max_tokens": 400},
        },
    }


def load_store(path: Path = SETTINGS_FILE) -> dict:
    """Read settings.json; create it with the built-in defaults if it does not exist."""
    if not path.exists():
        save_store(_default_store(), path)
    with path.open(encoding="utf-8") as f:
        store = json.load(f)
    store.setdefault("defaults", {})
    store.setdefault("presets", {"baseline": {}})
    store.setdefault("default_preset", next(iter(store["presets"])))
    return store


def save_store(store: dict, path: Path = SETTINGS_FILE) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def list_presets(path: Path = SETTINGS_FILE) -> list[str]:
    return list(load_store(path)["presets"])


def default_preset(path: Path = SETTINGS_FILE) -> str:
    return load_store(path)["default_preset"]


def load_settings(preset: str | None = None, path: Path = SETTINGS_FILE) -> Settings:
    """Built-in defaults <- settings.json "defaults" <- the preset's own overrides."""
    store = load_store(path)
    name = preset or store["default_preset"]
    if name not in store["presets"]:
        raise KeyError(f"Unknown preset '{name}'. Available: {', '.join(store['presets'])}")
    merged = Settings().values()
    merged.update({k: v for k, v in store["defaults"].items() if k in SETTING_NAMES})
    merged.update({k: v for k, v in store["presets"][name].items() if k in SETTING_NAMES})
    return Settings(**merged, preset=name)


def save_preset(name: str, settings: Settings, path: Path = SETTINGS_FILE) -> str:
    """Save settings as a preset, storing only the values that differ from "defaults"."""
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", name):
        raise ValueError("Preset names use letters, digits, '.', '_' or '-' (max 40 characters).")
    store = load_store(path)
    base = Settings().values()
    base.update({k: v for k, v in store["defaults"].items() if k in SETTING_NAMES})
    store["presets"][name] = {k: v for k, v in settings.values().items() if base.get(k) != v}
    save_store(store, path)
    return name
