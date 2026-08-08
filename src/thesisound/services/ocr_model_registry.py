
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_COMMITISH = re.compile(r"^[0-9a-f]{7,64}$")
_INVENTORY_NAME = ".thesisound-model-inventory.json"
CORE_MODEL_NAMES = (
    "pp-ocrv6-medium-det",
    "bina-0.2-rizehpizeh",
    "pp-ocrv6-small-rec",
    "pp-doclayout-v3",
)
VLM_MODEL_NAME = "paddleocr-vl-1.6"


class ModelNotProvisionedError(RuntimeError):
    """Raised when runtime model files are absent or fail integrity checks."""


class ModelAnchor(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OcrModelSpec(BaseModel):
    name: str
    role: str
    repo_id: str
    revision: str
    required: bool = True
    allow_patterns: list[str] = Field(default_factory=list)
    anchors: list[ModelAnchor] = Field(default_factory=list)

    def validate_revision(self) -> None:
        if self.revision in {"main", "master", "latest"} or not _COMMITISH.fullmatch(
            self.revision
        ):
            raise ValueError(
                f"Model {self.name!r} must use a pinned commit or commit prefix, "
                f"not {self.revision!r}."
            )


class OcrModelLock(BaseModel):
    schema_version: Literal[1]
    models: list[OcrModelSpec]

    def by_name(self) -> dict[str, OcrModelSpec]:
        values = {model.name: model for model in self.models}
        if len(values) != len(self.models):
            raise ValueError("Model lock contains duplicate model names.")
        for model in self.models:
            model.validate_revision()
        return values


class ModelVerification(BaseModel):
    name: str
    status: Literal["ready", "missing", "corrupt", "invalid_lock"]
    detail: str
    model_dir: Path | None = None
    resolved_revision: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"


class ProvisionedInventory(BaseModel):
    schema_version: Literal[1] = 1
    name: str
    repo_id: str
    requested_revision: str
    resolved_revision: str
    provisioned_at: datetime
    files: dict[str, str]


class OcrModelRegistry:
    """Provision and verify OCR models without loading them into memory.

    Network access exists only in :meth:`provision`. Runtime code calls
    :meth:`require` and receives a deterministic MODEL_NOT_PROVISIONED error
    rather than triggering an implicit model download.
    """

    def __init__(self, lock_path: Path, model_root: Path) -> None:
        self.lock_path = lock_path.expanduser().resolve()
        self.model_root = model_root.expanduser().resolve()

    @classmethod
    def from_environment(cls) -> OcrModelRegistry:
        return cls(
            Path(os.getenv("THESISOUND_OCR_MODEL_LOCK", "models.lock.json")),
            Path(os.getenv("THESISOUND_OCR_MODEL_ROOT", ".thesisound/models")),
        )

    def load_lock(self) -> OcrModelLock:
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ModelNotProvisionedError(
                f"MODEL_NOT_PROVISIONED: model lock not found at {self.lock_path}"
            ) from exc
        lock = OcrModelLock.model_validate(payload)
        lock.by_name()
        return lock

    def model_dir(self, name: str) -> Path:
        spec = self.load_lock().by_name().get(name)
        if spec is None:
            raise KeyError(f"Unknown OCR model: {name}")
        return self.model_root / spec.name / spec.revision

    def verify(self, name: str) -> ModelVerification:
        try:
            spec = self.load_lock().by_name()[name]
        except (KeyError, ValueError, ModelNotProvisionedError) as exc:
            return ModelVerification(name=name, status="invalid_lock", detail=str(exc))

        directory = self.model_root / spec.name / spec.revision
        inventory_path = directory / _INVENTORY_NAME
        if not directory.is_dir() or not inventory_path.is_file():
            return ModelVerification(
                name=name,
                status="missing",
                detail=f"Not provisioned at {directory}",
                model_dir=directory,
            )
        try:
            inventory = ProvisionedInventory.model_validate_json(
                inventory_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            return ModelVerification(
                name=name,
                status="corrupt",
                detail=f"Inventory is unreadable: {exc}",
                model_dir=directory,
            )
        if inventory.repo_id != spec.repo_id or inventory.requested_revision != spec.revision:
            return ModelVerification(
                name=name,
                status="corrupt",
                detail="Inventory provenance does not match models.lock.json.",
                model_dir=directory,
                resolved_revision=inventory.resolved_revision,
            )
        if not _FULL_SHA.fullmatch(inventory.resolved_revision):
            return ModelVerification(
                name=name,
                status="corrupt",
                detail="Provisioning did not resolve the model to a full immutable commit SHA.",
                model_dir=directory,
                resolved_revision=inventory.resolved_revision,
            )
        for relative, expected in inventory.files.items():
            path = directory / relative
            if not path.is_file():
                return ModelVerification(
                    name=name,
                    status="corrupt",
                    detail=f"Missing provisioned file: {relative}",
                    model_dir=directory,
                    resolved_revision=inventory.resolved_revision,
                )
            actual = _sha256(path)
            if actual != expected:
                return ModelVerification(
                    name=name,
                    status="corrupt",
                    detail=f"Checksum mismatch: {relative}",
                    model_dir=directory,
                    resolved_revision=inventory.resolved_revision,
                )
        for anchor in spec.anchors:
            path = directory / anchor.path
            if not path.is_file() or _sha256(path) != anchor.sha256:
                return ModelVerification(
                    name=name,
                    status="corrupt",
                    detail=f"Pinned anchor failed verification: {anchor.path}",
                    model_dir=directory,
                    resolved_revision=inventory.resolved_revision,
                )
        return ModelVerification(
            name=name,
            status="ready",
            detail=f"Verified {len(inventory.files)} files.",
            model_dir=directory,
            resolved_revision=inventory.resolved_revision,
        )

    def verify_all(self) -> list[ModelVerification]:
        try:
            names = list(self.load_lock().by_name())
        except (ValueError, ModelNotProvisionedError) as exc:
            return [
                ModelVerification(name="model-lock", status="invalid_lock", detail=str(exc))
            ]
        return [self.verify(name) for name in names]

    def require(self, names: tuple[str, ...] | list[str]) -> dict[str, Path]:
        failures: list[ModelVerification] = []
        paths: dict[str, Path] = {}
        for name in names:
            result = self.verify(name)
            if not result.ready or result.model_dir is None:
                failures.append(result)
            else:
                paths[name] = result.model_dir
        if failures:
            detail = "; ".join(f"{item.name}: {item.detail}" for item in failures)
            raise ModelNotProvisionedError(f"MODEL_NOT_PROVISIONED: {detail}")
        return paths

    def core_ready(self) -> bool:
        return all(self.verify(name).ready for name in CORE_MODEL_NAMES)

    def provision(self, names: list[str] | None = None, *, force: bool = False) -> list[Path]:
        """Download explicitly requested snapshots and write a full checksum inventory."""

        try:
            from huggingface_hub import HfApi, snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "Provisioning requires huggingface-hub. Run with "
                "`uv run --with huggingface-hub thesisound models provision`."
            ) from exc

        specs = self.load_lock().by_name()
        selected = names or list(specs)
        unknown = sorted(set(selected) - set(specs))
        if unknown:
            raise ValueError(f"Unknown OCR models: {', '.join(unknown)}")
        self.model_root.mkdir(parents=True, exist_ok=True)
        api = HfApi(token=os.getenv("HF_TOKEN") or None)
        written: list[Path] = []
        for name in selected:
            spec = specs[name]
            target = self.model_root / spec.name / spec.revision
            current = self.verify(name)
            if current.ready and not force:
                written.append(target)
                continue
            info = api.model_info(spec.repo_id, revision=spec.revision)
            resolved = str(info.sha or "")
            if not _FULL_SHA.fullmatch(resolved) or not resolved.startswith(spec.revision):
                raise RuntimeError(
                    f"Could not resolve {spec.repo_id}@{spec.revision} to a full commit SHA."
                )
            parent = target.parent
            parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=f".{spec.name}-", dir=parent))
            try:
                snapshot_download(
                    repo_id=spec.repo_id,
                    revision=resolved,
                    local_dir=temporary,
                    allow_patterns=spec.allow_patterns or None,
                    token=os.getenv("HF_TOKEN") or None,
                )
                files = {
                    path.relative_to(temporary).as_posix(): _sha256(path)
                    for path in sorted(temporary.rglob("*"))
                    if path.is_file() and path.name != _INVENTORY_NAME
                }
                inventory = ProvisionedInventory(
                    name=spec.name,
                    repo_id=spec.repo_id,
                    requested_revision=spec.revision,
                    resolved_revision=resolved,
                    provisioned_at=datetime.now(UTC),
                    files=files,
                )
                (temporary / _INVENTORY_NAME).write_text(
                    inventory.model_dump_json(indent=2) + "\n",
                    encoding="utf-8",
                )
                _verify_anchor_files(temporary, spec)
                if target.exists():
                    shutil.rmtree(target)
                temporary.replace(target)
                written.append(target)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return written

    def runtime_environment(self) -> dict[str, str]:
        """Return an offline-only child-process environment with no Hub credential."""

        environment = dict(os.environ)
        for key in (
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
        ):
            environment.pop(key, None)
        environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "HF_DATASETS_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "DO_NOT_TRACK": "1",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                "THESISOUND_OCR_MODEL_ROOT": str(self.model_root),
                "THESISOUND_OCR_MODEL_LOCK": str(self.lock_path),
            }
        )
        return environment


def _verify_anchor_files(root: Path, spec: OcrModelSpec) -> None:
    for anchor in spec.anchors:
        path = root / anchor.path
        if not path.is_file():
            raise RuntimeError(f"Provisioned snapshot is missing anchor {anchor.path}")
        actual = _sha256(path)
        if actual != anchor.sha256:
            raise RuntimeError(
                f"Anchor checksum mismatch for {spec.name}/{anchor.path}: {actual}"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
