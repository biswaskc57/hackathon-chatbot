"""Client for the EU-hosted LLM gateway (Azure Container Apps, Sweden Central).

Reusable from chat.py, the RAG pipeline and the evaluation scripts.
Credentials and settings come from environment variables (.env).
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = (
    "https://ca-backend-mciai-prod.mangoforest-0c569892.swedencentral.azurecontainerapps.io"
)
RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """Raised when the gateway returns an error we cannot recover from."""


class APIClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
        max_retries: int = 2,
    ):
        self.api_key = api_key or os.environ["CLIENT_ID"]
        self.api_secret = api_secret or os.environ["CLIENT_SECRET"]
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def create_chat_completion(self, model: str, messages: list, **kwargs) -> dict:
        url = f"{self.base_url}/api/v1/llm/chat"
        headers = {
            "X-Client-ID": self.api_key,
            "X-Client-Secret": self.api_secret,
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": fold_system_messages(messages), **kwargs}

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise LLMError(f"Network error calling the gateway: {exc}") from exc

            if response.ok:
                return response.json()

            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                time.sleep(2 * (attempt + 1))
                continue

            # Show the gateway's own error message instead of a bare status code.
            raise LLMError(f"Gateway returned {response.status_code}: {response.text[:500]}")

        raise LLMError("Gateway call failed after retries.")


def fold_system_messages(messages: list) -> list:
    """The gateway accepts only 'user' and 'assistant' roles.

    Move any 'system' content to the start of the first user message, so the
    instructions are sent with every call while the history stays intact.
    """
    system_text = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [dict(m) for m in messages if m["role"] != "system"]
    if not system_text:
        return rest

    for m in rest:
        if m["role"] == "user":
            m["content"] = (
                f"[Instructions for the assistant]\n{system_text}\n\n"
                f"[Customer message]\n{m['content']}"
            )
            break
    else:
        rest.insert(0, {"role": "user", "content": system_text})
    return rest


def parse_usage(response: dict) -> dict:
    """Return input, output and total tokens, whatever names the gateway uses."""
    usage = (response.get("data") or {}).get("usage") or {}

    def first(*keys):
        for key in keys:
            if usage.get(key) is not None:
                return usage[key]
        return None

    return {
        "input_tokens": first("promptTokens", "inputTokens", "prompt_tokens", "input_tokens"),
        "output_tokens": first("completionTokens", "outputTokens", "completion_tokens", "output_tokens"),
        "total_tokens": first("totalTokens", "total_tokens"),
        "raw_usage": usage,
    }


if __name__ == "__main__":
    # Quick connectivity test: python llm_client.py
    api = APIClient()
    model = os.getenv("MODEL", "gpt-4o")
    reply = api.create_chat_completion(
        model=model,
        messages=[{"role": "user", "content": "Hello, how can you help me?"}],
        temperature=0.2,
        maxTokens=200,
    )
    print(f"Response: {reply['data']['content']}")
    print(f"Usage: {parse_usage(reply)}")