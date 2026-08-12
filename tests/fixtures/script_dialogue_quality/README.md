# Script dialogue quality gate calibration fixture

Frozen reconstruction of the 2026-08-09 dialogue defect used to calibrate
`docs/07-specs/02-script-dialogue-quality-gate.md`:

- 22 turns, speaker sequence `ABABABBABABABABABABABA`
- speaker word counts 757 : 355
- ~35% editorial words (above the 25% whole-script floor)
- 8 filler openers («دقیقاً») on non-substantive turns
- 1 substantive speaker-B turn of 11

`speaker_balance_violations.json` carries the per-segment F1 strings that C1 binds.
