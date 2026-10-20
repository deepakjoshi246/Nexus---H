import pytest


@pytest.fixture(autouse=True)
def disable_remote_model_calls(monkeypatch):
    monkeypatch.setenv("NEXUS_H_ENABLE_MODEL_ADVISORY", "false")
