from __future__ import annotations

import os

from thesisound.adapters.parsers.docling_adapter import _offline_model_environment


def test_docling_conversion_environment_is_forced_offline(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "runtime-secret")
    with _offline_model_environment(enabled=True):
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        assert "HF_TOKEN" not in os.environ
    assert os.environ["HF_TOKEN"] == "runtime-secret"
