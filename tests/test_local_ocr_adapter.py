
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from thesisound.adapters.parsers.local_ocr_adapter import LocalOcrParser
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.ocr_model_registry import CORE_MODEL_NAMES


class FakeRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def core_ready(self) -> bool:
        return True

    def require(self, names):
        return {name: self.root / name for name in names}

    def runtime_environment(self):
        return {"PATH": "/usr/bin", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


def test_adapter_runs_one_short_lived_offline_worker(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    inspection = DocumentInspection(
        path=source.resolve(),
        mime_type="application/pdf",
        extension=".pdf",
        file_size_bytes=9,
        sha256="a" * 64,
        page_count=1,
        image_only_ratio=1,
    )

    def runner(command, timeout_seconds, environment):
        assert command[1:3] == ["-m", "thesisound.ocr_worker"]
        assert timeout_seconds == 20
        assert environment["HF_HUB_OFFLINE"] == "1"
        request_path = Path(command[-1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert set(CORE_MODEL_NAMES).issubset(request["model_dirs"])
        output = Path(request["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        parsed = ParsedDocument(
            parser_name="local-ocr",
            parser_version="test",
            blocks=[
                ParsedBlock(
                    source_block_key="page-1-line-1",
                    text="متن آزمایشی",
                    page_start=1,
                    page_end=1,
                    kind="text",
                )
            ],
        )
        output.write_text(parsed.model_dump_json(), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    parser = LocalOcrParser(
        registry=FakeRegistry(tmp_path),
        output_root=tmp_path / "out",
        timeout_seconds=20,
        python_command="python",
        runner=runner,
    )
    parsed = parser.parse(source, inspection)
    assert parsed.parser_name == "local-ocr"
    assert parsed.blocks[0].page_start == 1
