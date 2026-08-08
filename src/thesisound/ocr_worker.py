
from __future__ import annotations

import argparse
import os
from pathlib import Path

from thesisound.services.ocr_contracts import OcrWorkerRequest
from thesisound.services.paddle_ocr_runtime import parse_with_local_models


def main() -> None:
    parser = argparse.ArgumentParser(description="One-document offline OCR worker")
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    _enforce_offline_environment()
    request = OcrWorkerRequest.model_validate_json(
        args.request.read_text(encoding="utf-8")
    )
    parsed = parse_with_local_models(request)
    request.output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = request.output_path.with_suffix(request.output_path.suffix + ".tmp")
    temporary.write_text(parsed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(request.output_path)


def _enforce_offline_environment() -> None:
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        os.environ.pop(key, None)
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "DO_NOT_TRACK": "1",
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        }
    )


if __name__ == "__main__":
    main()
