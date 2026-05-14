from __future__ import annotations


def test_defaults_use_qwen3_4b_for_both_extract_and_agent() -> None:
    # The default agent model is the safe side (4b) so memory-constrained
    # machines do not implicitly load two models. Switching to qwen3:8b is
    # opt-in via DOCDB_AGENT_MODEL.
    from docdb.config import Settings

    s = Settings()
    assert s.extract_model == "qwen3:4b"
    assert s.agent_model == "qwen3:4b"
    assert s.embed_model == "bge-m3"
    assert s.embed_dim == 1024


def test_env_prefix_overrides_settings(monkeypatch) -> None:
    monkeypatch.setenv("DOCDB_AGENT_MODEL", "qwen3:8b")
    monkeypatch.setenv("DOCDB_AGENT_MAX_ITERS", "12")
    monkeypatch.setenv("DOCDB_OLLAMA_BASE_URL", "http://example:9999/v1")

    from docdb.config import Settings

    s = Settings()
    assert s.agent_model == "qwen3:8b"
    assert s.agent_max_iters == 12
    assert s.ollama_base_url == "http://example:9999/v1"


def test_unrelated_env_vars_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv("UNRELATED_THING", "boom")

    from docdb.config import Settings

    Settings()  # must not raise
