
# Thesisound OCR benchmark

The benchmark compares complete pipelines, not incomparable model-card scores.

## Screening corpus

Use 24 cells and five pages per cell: 120 pages total.

```text
2 source types: born-digital, scanned/image PDF
× 3 language states: Persian, English, mixed Persian+English
× 2 quality states: good, degraded
× 2 layouts: simple, complex
```

Complex pages must include columns, headings, footnotes, tables, formulas, and embedded images. Degraded samples should prefer real scan failures: low contrast, skew, blur, compression, photocopy, screen photo, warp, and low resolution.

Source files with copyright restrictions remain outside Git. Add them under `benchmarks/ocr/runtime/corpus/`.

## Ground truth

Each page needs:

- logical text;
- ordered blocks and coordinates;
- headings, paragraphs, footnotes, tables, and formulas;
- line-level text and coordinates.

For Persian, report both raw and normalized scores. Normalization must not hide ZWNJ, Persian/Arabic glyph, digit, or punctuation failures.

## Metrics

Text:

- CER, WER, exact-line accuracy, normalized edit similarity;
- script accuracy, ZWNJ accuracy, numeric fidelity.

Structure:

- reading-order edit distance;
- block detection F1/IoU;
- page locator preservation;
- table TEDS and cell CER;
- formula match;
- heading hierarchy and footnote attachment accuracy.

Resources:

- cold start and time to first page;
- end-to-end document time including model load;
- steady inference throughput;
- peak RSS/PSS and VRAM;
- render/detect/recognize/layout/VLM stage timing.

Router:

- percentage native, lightweight OCR, layout OCR, and VLM fallback;
- false-native rate;
- unnecessary-VLM rate;
- failed-fallback rate.

After screening, expand to 300–500 real Thesisound pages before production selection.
