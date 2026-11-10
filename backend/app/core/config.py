"""Settings, read from environment variables (and backend/.env)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_name: str = "Gleaner"
    # SQLite needs no setup; point this at Postgres for a real deployment, e.g.
    # postgresql+psycopg://gleaner:gleaner@localhost:5432/gleaner
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'gleaner.db'}"

    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_expires_minutes: int = 60 * 12

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Where this backend is reachable. The built-in practice store is served from here.
    public_base_url: str = "http://127.0.0.1:8000"

    # ---- Crawler ----
    # Run the scheduler and run queue inside the API process. Set to false to run
    # them separately with `python -m app.worker` (or in tests).
    run_worker: bool = True
    max_concurrent_runs: int = 2
    request_timeout_seconds: float = 20.0
    max_response_bytes: int = 5_000_000
    max_retries: int = 3
    # The crawler refuses private and loopback addresses (SSRF protection), except these
    # hosts. The default lets it reach the practice store this backend serves.
    allowed_private_hosts: list[str] = ["127.0.0.1", "localhost"]
    # Headless Chromium for pages that need JavaScript. Optional: pip install playwright
    # && playwright install chromium.
    browser_enabled: bool = True

    # AI: a local LLM served by Ollama (https://ollama.com).
    #   "auto"  = use the local model when the server is up and the model is downloaded,
    #             otherwise offline rules ("demo").
    #   "local" = always use it; failed calls fall back to the rules and are logged.
    #   "demo"  = offline rules only.
    ai_provider: str = "auto"
    local_llm_url: str = "http://localhost:11434"
    local_llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    # Tokens of prompt plus answer the model can see at once.
    local_llm_context: int = 20480
    local_llm_max_output: int = 4096
    local_llm_timeout_seconds: float = 300.0
    # How long Ollama keeps the model loaded between calls.
    local_llm_keep_alive: str = "30m"


@lru_cache
def get_settings() -> Settings:
    return Settings()
