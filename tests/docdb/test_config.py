from __future__ import annotations


def test_default_models() -> None:
    # Both extract and agent default to gemma4:e2b after the granite4.1
    # tool-call garble investigation; see memory note
    # project-granite-tool-call-garble.
    from docdb.config import Settings

    s = Settings(_env_file=None)
    assert s.extract_model == "gemma4:e2b"
    assert s.agent_model == "gemma4:e2b"
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


def test_query_resolution_defaults() -> None:
    from docdb.config import Settings

    s = Settings(_env_file=None)
    assert s.query_resolution_enabled is True
    assert s.query_resolution_top_k == 15
    assert s.query_resolution_distance == 0.85


def test_query_resolution_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DOCDB_QUERY_RESOLUTION_ENABLED", "false")
    monkeypatch.setenv("DOCDB_QUERY_RESOLUTION_TOP_K", "25")
    monkeypatch.setenv("DOCDB_QUERY_RESOLUTION_DISTANCE", "0.7")

    from docdb.config import Settings

    s = Settings()
    assert s.query_resolution_enabled is False
    assert s.query_resolution_top_k == 25
    assert s.query_resolution_distance == 0.7
