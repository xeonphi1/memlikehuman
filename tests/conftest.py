import pytest

from memlikehuman.engine import Engine
from memlikehuman.models import Extraction, MemoryCandidate, Scope


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path / "data")


@pytest.fixture
def scope():
    return Scope()


def remember(
    engine, scope, event_id="e1", text="我现在住上海", at="2026-01-01T00:00:00Z", **kwargs
):
    role = kwargs.pop("role", "user")
    engine.record(scope, event_id, text, role, "synthetic-test", occurred_at=at)
    candidate = MemoryCandidate(
        content=kwargs.pop("content", text),
        kind=kwargs.pop("kind", "fact"),
        basis=kwargs.pop("basis", "user_statement"),
        source_quote=kwargs.pop("source_quote", text),
        **kwargs,
    )
    return engine.store.apply_extraction(scope, event_id, Extraction(memories=[candidate]))[0]
