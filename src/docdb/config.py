from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCDB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_base_url: str = "http://localhost:11434/v1"
    extract_model: str = "granite4.1:3b"
    agent_model: str = "granite4.1:3b"
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    keep_alive: str = "5m"

    db_path: Path = Path("./storage/docdb.sqlite")
    data_dir: Path = Path("./data")

    agent_max_iters: int = Field(default=8, ge=1, le=20)
    sql_max_limit: int = Field(default=100, ge=1, le=1000)

    # Stage 3 — LLM extraction tuning.
    # Relation extraction is more error-prone than entity extraction on
    # small Ollama models; this flag lets the user turn it off without
    # rebuilding the type registry.
    extract_relations: bool = True
    extraction_prompt_max_bytes: int = Field(default=30_000, ge=2_000, le=200_000)
    agent_prompt_max_bytes: int = Field(default=20_000, ge=2_000, le=150_000)
    text2sql_prompt_max_bytes: int = Field(default=30_000, ge=2_000, le=200_000)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
