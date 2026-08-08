
# 28 — Self-hosted multilingual OCR

## Decision

Thesisound does not use one OCR model for every PDF. Routing is page-oriented and selects the cheapest adequate path:

```text
healthy digital page
→ native text extraction

scan or broken text layer
→ PP-OCRv6 medium detector
→ Bina 0.2 for Persian lines
→ PP-OCRv6 small recognizer for English/Latin lines

complex columns, footnotes, tables, formulas
→ PP-DocLayoutV3 for regions and reading order
→ lightweight line recognizers

failed quality/structure gate
→ PaddleOCR-VL-1.6 for that page only
```

The fallback VLM is disabled by default. It must be explicitly provisioned and enabled.

## Resource lifecycle

There is no always-warm OCR service. `LocalOcrParser` spawns one process for one document, processes all relevant pages, writes `parsed-document.json`, and exits. Process exit releases Python/Paddle RSS and GPU VRAM. At zero traffic, model cost is disk only.

## Provisioning

Models are declared in `models.lock.json`. The lock pins a commit or commit prefix and anchor SHA-256. Provisioning resolves every prefix to a full immutable commit SHA, downloads into a temporary directory, hashes every file, verifies anchors, writes `.thesisound-model-inventory.json`, and atomically moves the snapshot into the model root.

```bash
uv run --with huggingface-hub thesisound models list
uv run --with huggingface-hub thesisound models provision
uv run thesisound models verify
```

Production behavior on a missing or corrupt model is:

```text
MODEL_NOT_PROVISIONED
```

It is never an implicit download.

## Isolated OCR environment

Paddle dependencies are intentionally not part of the normal web/CI environment. Build a separate environment:

```bash
python -m venv .venv-ocr
.venv-ocr/bin/python -m pip install \
  paddlepaddle \
  "paddleocr[doc-parser]>=3.3,<4" \
  pymupdf pillow pypdf

export THESISOUND_OCR_PYTHON="$PWD/.venv-ocr/bin/python"
```

Windows:

```powershell
py -3.12 -m venv .venv-ocr
.venv-ocr\Scripts\python.exe -m pip install `
  paddlepaddle "paddleocr[doc-parser]>=3.3,<4" pymupdf pillow pypdf
$env:THESISOUND_OCR_PYTHON = "$PWD\.venv-ocr\Scripts\python.exe"
```

## Offline enforcement

Runtime receives explicit local paths for every model and these flags:

```dotenv
HF_HUB_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
HF_DATASETS_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

The worker strips Hub tokens. Infrastructure must additionally deny runtime egress+ environment variables are defense in depth, not the primary network boundary.

## Manual test

```bash
uv run thesisound models parse sample.pdf --output parse.json
uv run thesisound models parse hard.pdf --enable-vlm --output hard-parse.json
```

## Production gate

Do not claim OCR quality from model-card scores. Use the benchmark matrix in `benchmarks/ocr/README.md`. The first screening gate is 120 pages; the production gate is 300–500 representative pages. Measure text, reading order, structure, cold start, peak RSS/VRAM, and unnecessary VLM fallback rate.
