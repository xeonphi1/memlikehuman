import sys
from types import SimpleNamespace

from memlikehuman.tokens import TokenCounter


def test_unavailable_tokenizer_uses_labeled_estimate(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    counter = TokenCounter("unknown")
    assert counter.method == "conservative_utf8_bytes_estimate"
    assert counter.count("中文") == 6


def test_asset_failure_falls_back_without_breaking_restore(monkeypatch):
    def fail(_):
        raise OSError("cache or network unavailable")

    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace(encoding_for_model=fail))
    counter = TokenCounter("known-model")
    assert counter.count("test") == 4
    assert "estimate" in counter.method


def test_real_optional_tokenizer_with_local_encoding(monkeypatch):
    import pytest

    pytest.importorskip("tiktoken")
    import tiktoken.model
    import tiktoken.registry

    # Real tokenizer implementation, deterministic local vocabulary, no asset download.
    encoding = tiktoken.Encoding(
        name="memlikehuman-test",
        pat_str=r"[\s\S]+",
        mergeable_ranks={bytes([i]): i for i in range(256)},
        special_tokens={},
    )
    monkeypatch.setitem(tiktoken.registry.ENCODINGS, "memlikehuman-test", encoding)
    monkeypatch.setitem(
        tiktoken.model.MODEL_TO_ENCODING, "memlikehuman-test-model", "memlikehuman-test"
    )
    counter = TokenCounter("memlikehuman-test-model")
    assert counter.method == "exact_text_tokenizer"
    assert counter.count("中文 hello") == len(encoding.encode("中文 hello"))
