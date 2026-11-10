"""One entry point for every AI call: a local LLM served by Ollama, with structured JSON
output, logged, with an offline fallback.

Each feature passes a JSON schema plus a `demo` function that produces the same shape
from simple rules. Ollama constrains the model's output to the schema, so the answer is
always JSON of that shape. The demo path runs when no local model is available, and also
when a call fails, so the app keeps working (and says which path answered).
"""
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AIRequest

logger = logging.getLogger(__name__)

DEMO_MODEL = "rules-v1"
JSON_INSTRUCTION = "\n\nRespond with one JSON object that matches the required schema, and nothing else."
STATUS_TTL_SECONDS = 15.0


@dataclass
class AIResult:
    data: dict
    provider: str  # "local", "demo", or "demo-fallback"
    model: str


class AIError(Exception):
    pass


def _base_url() -> str:
    return get_settings().local_llm_url.rstrip("/")


_status_cache: tuple[float, bool, str] | None = None


def local_model_available() -> tuple[bool, str]:
    """Is the Ollama server up with the configured model pulled? Checked at most every 15 s."""
    global _status_cache
    now = time.monotonic()
    if _status_cache and now - _status_cache[0] < STATUS_TTL_SECONDS:
        return _status_cache[1], _status_cache[2]
    model = get_settings().local_llm_model
    try:
        response = httpx.get(f"{_base_url()}/api/tags", timeout=2.0)
        response.raise_for_status()
        names = {name for m in response.json().get("models", []) for name in (m.get("name"), m.get("model"))}
        if model in names or f"{model}:latest" in names:
            available, reason = True, ""
        else:
            available, reason = False, f"Model {model} isn't downloaded. Run: ollama pull {model}"
    except (httpx.HTTPError, ValueError) as e:
        available, reason = False, f"No local model server at {_base_url()} ({type(e).__name__})"
    _status_cache = (now, available, reason)
    return available, reason


def _resolved_provider() -> str:
    """"local" or "demo". In auto mode the local model is used only when it's available."""
    setting = get_settings().ai_provider
    if setting in ("local", "demo"):
        return setting
    return "local" if local_model_available()[0] else "demo"


def provider_status() -> tuple[str, str]:
    if _resolved_provider() == "local":
        return "local", get_settings().local_llm_model
    return "demo", DEMO_MODEL


def _call_local(system: str, prompt: str, schema: dict, max_tokens: int) -> tuple[dict, int, int]:
    settings = get_settings()
    body = {
        "model": settings.local_llm_model,
        "messages": [
            {"role": "system", "content": system + JSON_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        # Constrained decoding: the model can only produce JSON matching this schema.
        "format": schema or "json",
        "stream": False,
        "keep_alive": settings.local_llm_keep_alive,
        "options": {
            "temperature": 0,
            # Ollama silently drops the start of a prompt longer than its context window,
            # so set it explicitly instead of relying on the small default.
            "num_ctx": settings.local_llm_context,
            "num_predict": min(max_tokens, settings.local_llm_max_output),
        },
    }
    try:
        response = httpx.post(f"{_base_url()}/api/chat", json=body, timeout=settings.local_llm_timeout_seconds)
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach the local model at {_base_url()}: {type(e).__name__}") from e
    if response.status_code != 200:
        raise AIError(f"The local model server answered {response.status_code}: {response.text[:300]}")
    out = response.json()
    if out.get("done_reason") == "length":
        raise AIError("The model's answer was cut off.")
    text = ((out.get("message") or {}).get("content") or "").strip()
    if not text:
        raise AIError("The model returned no answer.")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise AIError("The model's answer wasn't a JSON object.")
    return data, out.get("prompt_eval_count") or 0, out.get("eval_count") or 0


LOG_TEXT_LIMIT = 30_000


def _clip(text: str) -> str:
    """Prompts can include a whole page of HTML; the log keeps the start of it."""
    return text if len(text) <= LOG_TEXT_LIMIT else text[:LOG_TEXT_LIMIT] + f"\n... ({len(text) - LOG_TEXT_LIMIT:,} more characters)"


def run_json(
    *,
    db: Session,
    workspace_id: str,
    user_id: str | None,
    feature: str,
    system: str,
    prompt: str,
    schema: dict,
    demo: Callable[[], dict],
    max_tokens: int = 4096,
) -> AIResult:
    """Run one structured AI task and record it in the AI activity log."""
    settings = get_settings()
    log = AIRequest(workspace_id=workspace_id, user_id=user_id, feature=feature, input_text=_clip(prompt))
    start = time.perf_counter()
    result: AIResult

    if _resolved_provider() == "local":
        try:
            data, tokens_in, tokens_out = _call_local(system, prompt, schema, max_tokens)
            result = AIResult(data, "local", settings.local_llm_model)
            log.input_tokens, log.output_tokens = tokens_in, tokens_out
        except (AIError, json.JSONDecodeError) as e:
            # Keep the feature usable: answer from the rule-based path, and log why.
            logger.exception("Local model call failed for %s; using rule-based fallback", feature)
            log.success = False
            log.error = f"{type(e).__name__}: {e}"
            result = AIResult(demo(), "demo-fallback", DEMO_MODEL)
    else:
        result = AIResult(demo(), "demo", DEMO_MODEL)

    log.provider, log.model = result.provider, result.model
    log.output_text = json.dumps(result.data, ensure_ascii=False)
    log.latency_ms = int((time.perf_counter() - start) * 1000)
    db.add(log)
    return result


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(properties: dict) -> dict:
    """A strict object schema: every property required, nothing extra allowed."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


STR = {"type": "string"}
STR_LIST = {"type": "array", "items": STR}
