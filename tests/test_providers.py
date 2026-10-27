import json

import httpx
import pytest
from conftest import remember

from memlikehuman.config import ProviderConfig
from memlikehuman.models import EventInput
from memlikehuman.providers import OpenAIProvider, ProviderError


def provider(handler):
    return OpenAIProvider(
        ProviderConfig(base_url="https://example.test/v1", model="test"),
        httpx.MockTransport(handler),
    )


def test_openai_compatible_extraction_schema_and_key(monkeypatch):
    monkeypatch.setenv("MEMLIKEHUMAN_API_KEY", "test-key")

    def handle(request):
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert "UNTRUSTED" in payload["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"memories": []}'}}]})

    result = provider(handle).extract(
        EventInput(event_id="1", text="你好", role="user", source="test")
    )
    assert result.memories == []


def test_remote_errors_do_not_leak_secrets():
    p = provider(lambda _: httpx.Response(401, text="private-key and private-conversation"))
    with pytest.raises(ProviderError) as error:
        p.embed(["内容"])
    assert str(error.value) == "Provider HTTP 401"


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [{"index": 0, "embedding": []}],
        [{"index": 1, "embedding": [1]}],
        [{"index": 0, "embedding": [0, 0]}],
    ],
)
def test_invalid_embedding_response_rejected(vectors):
    with pytest.raises(ProviderError):
        provider(lambda _: httpx.Response(200, json={"data": vectors})).embed(["test"])


def test_embedding_model_version_and_semantic_retrieval(engine, scope):
    mid = remember(engine, scope, text="我喜欢热茶")
    engine.embedder = provider(
        lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]})
    )
    engine.reindex(scope)
    result = engine.recall(scope, "温暖的饮品", search_mode="semantic")
    assert result["memories"][0]["id"] == mid
    old = engine.embedder.fingerprint
    engine.embedder.config.version = "2"
    assert engine.embedder.fingerprint != old
    assert engine.recall(scope, "温暖的饮品", search_mode="semantic")["memories"] == []
    assert engine.recall(scope, "温暖的饮品", search_mode="semantic")["warnings"]
    engine.reindex(scope)
    assert engine.store.vectors(scope, old) == []
    assert engine.recall(scope, "温暖的饮品", search_mode="semantic")["memories"][0]["id"] == mid


def test_embedding_failure_keeps_old_index_and_raw_data(engine, scope):
    mid = remember(engine, scope)
    good = provider(
        lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]})
    )
    engine.embedder = good
    engine.reindex(scope)
    engine.embedder = provider(lambda _: httpx.Response(503))
    with pytest.raises(ProviderError):
        engine.reindex(scope)
    assert engine.store.vectors(scope, good.fingerprint)
    assert engine.store.read(scope, mid)["source_event"]["text"] == "我现在住上海"
    result = engine.recall(scope, "上海", search_mode="semantic")
    assert result["memories"] and result["warnings"]


def test_credentials_not_allowed_in_config_urls():
    with pytest.raises(ValueError):
        ProviderConfig(base_url="https://user:secret@example.test/v1")
    with pytest.raises(ValueError):
        ProviderConfig(api_key_env="sk-secret")


def test_automatic_extraction_adds_semantic_index(engine, scope):
    from memlikehuman.models import Extraction, MemoryCandidate

    class Extractor:
        def extract(self, event):
            return Extraction(
                memories=[
                    MemoryCandidate(
                        content=event.text,
                        kind="preference",
                        basis="user_statement",
                        source_quote=event.text,
                    )
                ]
            )

    engine.extractor = Extractor()
    engine.embedder = provider(
        lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]})
    )
    result = engine.record(scope, "auto-vector", "我喜欢热茶", "user", "test")
    assert result["state"] == "done"
    assert engine.recall(scope, "温暖的饮品", search_mode="semantic")["memories"]


def test_vector_failure_does_not_fail_durable_extraction(engine, scope):
    from memlikehuman.models import Extraction, MemoryCandidate

    class Extractor:
        def extract(self, event):
            return Extraction(
                memories=[
                    MemoryCandidate(
                        content=event.text,
                        kind="fact",
                        basis="user_statement",
                        source_quote=event.text,
                    )
                ]
            )

    engine.extractor = Extractor()
    engine.embedder = provider(lambda _: httpx.Response(500))
    result = engine.record(scope, "embed-fail", "我住杭州", "user", "test")
    assert result["state"] == "done" and result["durable"]
    assert result["warning"]
    assert engine.store.memories(scope)[0]["content"] == "我住杭州"
