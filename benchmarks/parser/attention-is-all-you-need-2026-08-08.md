# Parser benchmark: Attention Is All You Need

Date: 2026-08-08  
Workflow run: `31243393532`  
Benchmark commit: `a6293c1dcc5811cd4c2fac64beb2dbf79c5cc995`

## Purpose

This benchmark compares the real Thesisound Docling and MinerU adapters on one non-trivial academic PDF. It is not a synthetic fixture and it is not intended to prove a universal winner.

The selected paper is **Attention Is All You Need**, arXiv `1706.03762v7`. It is useful for this test because its 15 pages contain:

- two-column academic prose;
- display equations;
- model diagrams and extracted labels;
- footnotes and references;
- four tables, including multi-row headers;
- appendix visualisations containing many repeated short tokens.

The PDF was downloaded from `https://arxiv.org/pdf/1706.03762` during the workflow. The tested file SHA-256 was:

```text
bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697
```

The PDF itself is not committed to this repository.

## Environment

| Component | Version |
|---|---:|
| GitHub runner | `ubuntu-latest`, CPU |
| Python | 3.12.13 |
| uv | 0.12.3 |
| Docling | 2.118.1 |
| MinerU | 3.4.4 |
| MinerU backend | `pipeline` |

The workflow artifact digest was:

```text
sha256:d85f19f90eb99b3e830ffcb6975790190c1b091422a90e3d85bf817c2a3d6380
```

## Automatic results

| Metric | Docling | MinerU |
|---|---:|---:|
| Status | success | success |
| Duration | 305.86 s | 139.99 s |
| Quality verdict | pass | pass |
| Safe for claim extraction | yes | yes |
| Blocks | 500 | 137 |
| Parsed characters | 52,201 | 43,478 |
| Page coverage | 100% | 100% |
| Locator coverage | 100% | 100% |
| Heading coverage | 99.8% | 100% |
| Substantive duplicate ratio | 0% | 0% |
| Automatic score | 100 | 100 |

MinerU completed this CPU run about **2.18 times faster**, a **54.2% duration reduction** relative to Docling.

## A quality-gate defect found by the benchmark

The first successful comparison incorrectly marked Docling unsafe because 52.6% of its blocks were exact duplicates. Inspection of the normalized output showed that these were mostly legitimate short tokens from appendix visualisations, such as `<pad>`, `the`, punctuation, and individual diagram labels.

The old metric treated a duplicated three-character token the same as a duplicated paragraph. That was wrong.

The metric was changed to measure the share of **substantive duplicated characters in normalized blocks of at least 80 characters**. Tests were added for both repeated short tokens and repeated long paragraphs. After the correction, both parsers passed with a 0% substantive duplicate ratio.

This is the main reason this benchmark was worth running: it found a flaw in Thesisound's evaluator, not merely a difference between third-party parsers.

## Manual audit

Automatic scores are insufficient here. They verify coverage, locators, headings, duplication, and obvious corruption, but they do not know that an equation should exist or that a table row has been semantically merged.

### Shared strengths

Both outputs preserved:

- the paper title and abstract;
- the main section order through references;
- page provenance for all 15 pages;
- the main result values `28.4` and `41.8`;
- all four tables as structured blocks;
- the section on scaled dot-product attention and the section 6 results narrative.

### Docling

Observed structure:

- 500 blocks;
- median block length: 6 characters;
- 349 blocks shorter than 20 characters;
- 4 table blocks;
- 0 formula blocks in the normalized output.

Strengths:

- Table 2 was represented as a clean Markdown table with correctly separated model rows and columns.
- Prose reading order, headings, and page locators were accurate.
- Table rendering was generally easier to inspect than MinerU's HTML output.

Problems:

- The displayed scaled dot-product attention equation was absent between the two surrounding paragraphs. The same pattern affected the other display equations: no formula blocks survived normalization.
- Internal labels from Figure 2 and appendix token visualisations were emitted as many tiny blocks. This is not duplicate content, but it is poor segmentation for evidence extraction.
- Picture blocks contained unavailable-image placeholders because image generation is not enabled in the current Docling adapter.

### MinerU

Observed structure:

- 137 blocks;
- median block length: 198 characters;
- 24 blocks shorter than 20 characters;
- 4 table blocks;
- 5 formula blocks.

Strengths:

- The attention, multi-head attention, feed-forward, positional-encoding, and learning-rate equations were retained as formula blocks.
- Blocks were substantially more semantic and less fragmented.
- Extracted figure images were retained.
- Table 2 preserved the key BLEU values and row identities.

Problems:

- Generated LaTeX contains excessive spacing inside operators and identifiers, for example the letters of `Attention` and `softmax` are separated.
- Table 4 merged some neighboring row and cell contents in its HTML representation.
- Mathematical and front-matter cleanup is still required before direct display to a user.

## Decision

For the current Thesisound ingestion pipeline:

> **Use MinerU as the primary parser for formula-heavy, multi-column, scanned, or visually complex academic PDFs.**

The decision is not based on the tied automatic score. It is based on the manual audit:

- MinerU preserved display equations;
- it produced fewer and more meaningful blocks;
- it retained figure assets;
- it was about 2.18 times faster in this CPU run.

Docling should remain available for text-heavy or table-heavy, formula-light documents. On this paper it produced cleaner tables, but losing display equations is unacceptable when those equations may support later claims.

## Router implication

The router should use the following policy until a broader corpus is tested:

```text
image-only or OCR-needed PDF       -> MinerU
multi-column / formula-heavy PDF   -> MinerU
plain text-bearing PDF or book     -> Docling first, MinerU fallback
EPUB / Office / simple structured  -> Docling first
```

Quality gates remain mandatory. No parser should be trusted purely because the router selected it.

## Limitations

This result has medium confidence and must not be generalized too far:

- only one English technical paper was tested;
- no Persian OCR was tested;
- no scanned book, ordinary prose book, or EPUB was tested;
- runtime was measured on a GitHub-hosted CPU runner;
- automatic scores do not yet assess equation recall or table-cell semantic accuracy;
- the next corpus should contain at least one Persian scan, one prose book chapter, one social-science paper, and one EPUB.

## Reproduction

The committed workflow downloads the same PDF, records versions and SHA-256, runs both real adapters, persists normalized outputs, verifies both parsers completed, and uploads the full evidence bundle.

```bash
uv run thesisound compare-parsers \
  path/to/attention-is-all-you-need.pdf \
  --artifact-root artifacts/parser-benchmark \
  --output benchmark.json
```

The machine-readable result is stored beside this report in `attention-is-all-you-need-2026-08-08.json`.
