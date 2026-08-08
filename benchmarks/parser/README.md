# Parser benchmarks

This directory contains committed benchmark results and manual audits. Source PDFs and generated parser artifacts are not committed.

## Reports

- [Attention Is All You Need — 2026-08-08](attention-is-all-you-need-2026-08-08.md)
- [Machine-readable result](attention-is-all-you-need-2026-08-08.json)

## Interpretation rule

Automatic scores are quality gates, not a full measure of extraction fidelity. Every benchmark must also inspect:

- reading order;
- display-equation recall;
- table row and cell semantics;
- heading hierarchy;
- locator accuracy;
- fragmentation;
- omitted and duplicated content.

A parser is selected from the combination of machine metrics and manual audit, not from runtime or score alone.
