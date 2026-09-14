from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class ConfigError(RuntimeError):
    """Raised when a command needs a setting/key that isn't configured."""


@dataclass(frozen=True)
class Settings:
    raw_data_dir: Path = field(default_factory=lambda: Path(os.environ.get("COMPANY_ANALYZER_RAW_DATA_DIR", "data/raw")))
    schema_path: Path = field(default_factory=lambda: Path(__file__).parent / "db" / "schema.sql")

    supabase_db_url: str | None = field(default_factory=lambda: os.environ.get("SUPABASE_DB_URL") or None)

    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "mock"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None)
    openai_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY") or None)

    opendart_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENDART_API_KEY") or None)
    naver_client_id: str | None = field(default_factory=lambda: os.environ.get("NAVER_CLIENT_ID") or None)
    naver_client_secret: str | None = field(default_factory=lambda: os.environ.get("NAVER_CLIENT_SECRET") or None)

    def require_db_url(self) -> str:
        if not self.supabase_db_url:
            raise ConfigError(
                "Missing SUPABASE_DB_URL. In the Supabase dashboard: your project -> Connect -> "
                "'Direct connection' tab -> copy the URI (postgresql://postgres:[PASSWORD]@db.<ref>.supabase.co:5432/postgres), "
                "fill in your DB password, and set it in .env (see .env.example)."
            )
        return self.supabase_db_url

    def require_opendart_key(self) -> str:
        if not self.opendart_api_key:
            raise ConfigError(
                "Missing OPENDART_API_KEY. Register for free at https://opendart.fss.or.kr "
                "and set it in .env (see .env.example)."
            )
        return self.opendart_api_key

    def require_naver_keys(self) -> tuple[str, str]:
        if not self.naver_client_id or not self.naver_client_secret:
            raise ConfigError(
                "Missing NAVER_CLIENT_ID/NAVER_CLIENT_SECRET. Register for free at "
                "https://developers.naver.com and set them in .env (see .env.example)."
            )
        return self.naver_client_id, self.naver_client_secret

    def require_llm_key_for(self, provider: str) -> str:
        if provider == "anthropic":
            if not self.anthropic_api_key:
                raise ConfigError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set in .env.")
            return self.anthropic_api_key
        if provider == "openai":
            if not self.openai_api_key:
                raise ConfigError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set in .env.")
            return self.openai_api_key
        raise ConfigError(f"Unknown LLM provider '{provider}'. Expected one of: mock, anthropic, openai.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
