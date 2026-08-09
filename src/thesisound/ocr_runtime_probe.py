
from __future__ import annotations

import json
import platform
import sys

from thesisound import ocr_worker
from thesisound.services import ocr_contracts, ocr_planner, paddle_ocr_runtime
from thesisound.services.parser_identity import module_fingerprint, package_version

_SCHEMA_VERSION = 1
_PACKAGES = ("paddleocr", "paddlepaddle", "pymupdf", "pillow", "pypdf")


def probe() -> dict[str, object]:
    """Describe this interpreter's OCR runtime without importing any of it.

    Runs inside whatever interpreter THESISOUND_OCR_PYTHON points at -- often a
    separate virtualenv from the web/CLI process (see LocalOcrParser). The
    packages and code that actually produce OCR text live there, not in the
    calling process, so identity() cannot see them without asking this
    interpreter directly. Only distribution metadata is read here, never the
    packages themselves, so this stays cheap even when they are heavyweight.
    """

    modules = module_fingerprint(
        sys.modules[paddle_ocr_runtime.__name__],
        sys.modules[ocr_planner.__name__],
        sys.modules[ocr_worker.__name__],
        sys.modules[ocr_contracts.__name__],
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "python": platform.python_version(),
        "packages": {name: package_version(name) for name in _PACKAGES},
        "modules": modules,
    }


def main() -> None:
    sys.stdout.write(json.dumps(probe(), ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
