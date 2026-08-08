
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from thesisound.services.ocr_model_registry import OcrModelRegistry


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _registry(tmp_path: Path) -> tuple[OcrModelRegistry, Path]:
    payload = b"weights"
    lock = {
        "schema_version": 1,
        "models": [
            {
                "name": "test-model",
                "role": "test",
                "repo_id": "example/test",
                "revision": "abcdef0",
                "required": True,
                "anchors": [{"path": "model.bin", "sha256": _digest(payload)}],
            }
        ],
    }
    lock_path = tmp_path / "models.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return OcrModelRegistry(lock_path, tmp_path / "models"), lock_path


def test_registry_reports_missing_without_downloading(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    result = registry.verify("test-model")
    assert result.status == "missing"


def test_registry_verifies_inventory_and_all_files(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    directory = registry.model_dir("test-model")
    directory.mkdir(parents=True)
    (directory / "model.bin").write_bytes(b"weights")
    inventory = {
        "schema_version": 1,
        "name": "test-model",
        "repo_id": "example/test",
        "requested_revision": "abcdef0",
        "resolved_revision": "a" * 40,
        "provisioned_at": "2026-08-08T00:00:00Z",
        "files": {"model.bin": _digest(b"weights")},
    }
    (directory / ".thesisound-model-inventory.json").write_text(
        json.dumps(inventory), encoding="utf-8"
    )
    assert registry.verify("test-model").status == "ready"
    (directory / "model.bin").write_bytes(b"changed")
    assert registry.verify("test-model").status == "corrupt"


def test_runtime_environment_is_offline_and_removes_token(tmp_path: Path, monkeypatch) -> None:
    registry, _ = _registry(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "secret")
    environment = registry.runtime_environment()
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert "HF_TOKEN" not in environment
