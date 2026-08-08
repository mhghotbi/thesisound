# Persian OCR benchmark protocol

This benchmark is intentionally split by task. A line recognizer must not be compared directly with a full-page OCR pipeline unless a detector and reading-order reconstruction stage are added.

## Test tracks

### Track A — text-line recognition

Input: a content-tight horizontal image containing one Persian line.

Primary corpus:

- `mohajesmaeili/Persian_Arabic_TextLine_Image_Ocr_Small`, deterministic Persian-only subset from the `Test` split.

Systems:

- Tesseract `fas`, PSM 7 baseline;
- `WeightedAI/Persian_OCR`;
- `Reza2kn/Bina-0.2-RizehPizeh`;
- `mohajesmaeili/Qwen3-VL-2B-Persian-Arabic-Ocr-v1.0` on GPU.

Metrics:

- raw CER and normalized Persian CER;
- raw WER and normalized Persian WER;
- exact-line accuracy;
- initialization time;
- mean and total inference latency;
- failed-sample count;
- per-sample predictions retained for audit.

### Track B — full-page OCR

Input: one Persian document page with no pre-cropped lines.

Primary corpus:

- `mshojaei77/persian-ocr-bench`, 100 manually labelled real Persian document images;
- a deterministic subset of `Reza2kn/persian-handwriting-pages-369k` for synthetic handwriting stress testing;
- locally generated clean printed pages and degraded variants for controlled tests.

Systems:

- Tesseract `fas`, automatic page segmentation;
- Docling;
- MinerU;
- Bina 0.2 paired with an explicit detector and RTL reading-order reconstruction;
- `Reza2kn/Bina-0.1-Koochik` through Surya OCR 2 on an NVIDIA runner.

Metrics:

- page CER/WER after shared normalization;
- exact page match where realistic;
- line recall and reading-order accuracy;
- heading, table, formula and locator preservation;
- page latency and peak memory;
- output fragmentation;
- human audit of at least 10 representative pages.

### Track C — controlled degradation

Each clean printed page is rendered into these deterministic variants:

- clean 300-DPI scan;
- 150-DPI downsample;
- Gaussian blur;
- low contrast;
- JPEG compression;
- small rotation;
- perspective distortion;
- salt-and-pepper noise;
- mixed Persian/Latin/digit text;
- ZWNJ and Persian punctuation stress cases.

This track measures robustness independently from dataset composition.

## Persian normalization

The scorer records both raw and normalized metrics. Normalization applies:

- Unicode NFKC;
- Arabic `ي/ك` to Persian `ی/ک` mapping;
- Arabic and Persian digits to one comparison representation;
- diacritic removal;
- bidi-control removal;
- whitespace and punctuation-spacing normalization;
- ZWNJ preservation by default.

The raw prediction is always retained. Normalized metrics must never hide the original output.

## Fair-comparison rules

1. Full-page and line-level results are reported separately.
2. A recognizer paired with a detector is named as a pipeline, not as the recognizer alone.
3. Public model-card numbers are not mixed with measurements from this repository.
4. Runtime comparisons require the same runner, precision, batch size and sample set.
5. GPU and CPU latency appear in separate tables.
6. Any failed initialization is retained as a benchmark result.
7. Automatic metrics are followed by manual review of RTL order, tables, formulas and segmentation.
8. Dataset license and provenance are recorded before results are used for a product decision.

## Current execution status

- The line benchmark workflow is executable on GitHub-hosted CPU runners.
- Bina 0.1 and Qwen3-VL-2B require a separate NVIDIA workflow; their BF16/2B configurations are not treated as CPU baselines.
- Full-page parser benchmarking is a separate workflow because Docling/MinerU measure document structure in addition to transcription accuracy.

## Reproduction

```bash
python benchmarks/persian_ocr/run_line_benchmark.py \
  --systems tesseract,weightedai,bina02 \
  --limit 50 \
  --offset 0 \
  --output line-results.json
```

The workflow stores full predictions and errors in its artifact. Summary values alone are insufficient for accepting an OCR model.
