"""Unit test for src.vectorstore.embedder.warm_up — provider branching only,
no real model load (that's covered live by the vanilla RAG timing check in
the INGEST-005 commit)."""

from src.vectorstore import embedder


def test_warm_up_loads_local_model_when_provider_is_local(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_provider", "local")
    calls = []
    monkeypatch.setattr(embedder, "_local_model", lambda: calls.append(True))

    embedder.warm_up()

    assert calls == [True]


def test_warm_up_is_noop_when_provider_is_openai(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_provider", "openai")
    calls = []
    monkeypatch.setattr(embedder, "_local_model", lambda: calls.append(True))

    embedder.warm_up()

    assert calls == []
