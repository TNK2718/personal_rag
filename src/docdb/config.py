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
    # Both agent and extract default to gemma4:e2b. granite4.1:3b/8b
    # garbled Japanese inside tool-call JSON arguments; gemma4:e2b
    # passes the probe set verbatim (~2B effective). Keeping a single
    # model loaded for both paths also halves model-swap overhead in
    # Ollama. See memory note project-granite-tool-call-garble.
    extract_model: str = "gemma4:e2b"
    agent_model: str = "gemma4:e2b"
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    keep_alive: str = "5m"
    # Ollama defaults num_ctx to 2048 regardless of the model's true context
    # length, which silently truncates our 20KB system prompt + tool defs and
    # makes small models emit token-soup. Override per request.
    num_ctx: int = Field(default=16_384, ge=2_048, le=131_072)

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

    # Cross-document entity canonicalization. When enabled, every entity
    # produced by the normaliser is embedded and KNN-matched against
    # entities_vec; matches under ``entity_dedup_distance`` get merged
    # into the existing row (its canonical_name wins, the new surface
    # form becomes an alias). 0.35 ≈ cosine_sim 0.83 on unit-normalised
    # bge-m3 — start conservative, easy to tune.
    entity_dedup_enabled: bool = True
    entity_dedup_distance: float = Field(default=0.35, ge=0.0, le=2.0)

    # Query-time mention resolution. Mirrors the ingest-side fuzzy dedup
    # but runs in the opposite direction: at query time we KNN-search
    # ``entities_vec`` from the question's embedding and inject the
    # matches into the text2sql prompt so generated SQL filters by
    # ``entities.id`` instead of ``LIKE``. The whole-question vector is
    # noisier than ingest's typed canonical_name embedding, so the
    # threshold is intentionally far looser than ``entity_dedup_distance``.
    #
    # Empirical bge-m3 distances (Japanese, this corpus, 2026-05):
    #   ingest:  ``person: 田中太郎``       → d=0.000 (exact match)
    #   query:   ``田中太郎``                → d≈0.67
    #   query:   ``田中太郎のタスクを見せて`` → d≈0.81
    #   noise:   unrelated tasks            → d≈0.93+
    # 0.85 includes both bare names and full-sentence mentions while
    # filtering most unrelated rows; tune via ``DOCDB_QUERY_RESOLUTION_DISTANCE``.
    query_resolution_enabled: bool = True
    query_resolution_top_k: int = Field(default=15, ge=1, le=50)
    query_resolution_distance: float = Field(default=0.85, ge=0.0, le=2.0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
