# R10 — Giving speaker B a job, and proving it with a blind A/B

**Implementation plan. Follow it as written.**

Audience: a junior/mid-level developer on this codebase.
Source of the requirement: [`docs/thesisound-pipeline-audit.md`](thesisound-pipeline-audit.md) §10 row **R10**, §6.4.

> R10 🟨P2 — «گوینده‌ی دوم filler است» → «prompt سناریو را طوری تغییر بده که B وظیفه‌ی مشخص داشته باشد (پرسش از محدودیت/اعتراض)، سپس blind A/B»
> **Quality بالا** · Latency ~۰ · Cost کم · Effort کم · Risk متوسط · Confidence **Medium**

This is a **quality** change to the only stage the audit rates as genuinely good
(§7: Persian Script Generation — `Keep as-is`, «کیفیت خروجی واقعاً خوب»). Handle it
accordingly: the failure mode of this PR is making a working stage worse. Every design
decision below is already made; do not substitute your own. If you believe a decision is
wrong, stop and raise it before writing code.

---

## 1. What the change is, and three things that reframe it

The audit's instruction is "change the script prompt so B has a defined job". Before you
open that file, three facts, all measured against
`workspaces/f781a5c7-…/script/script-draft.json` and the shipped prompts on 2026-08-11.

### 1.1 The defect, re-verified

| | turns | editorial | words | editorial words |
|---|--:|--:|--:|--:|
| **A** | 11 | 1 | 835 | 37 |
| **B** | 11 | **10** | 386 | 346 |
| total | 22 | 11 | 1,221 | 383 = **31.4%** |

(The audit says 1,112 words / 32%; it tokenised differently. Same picture, and 31.4% is the
number `\w+` produces, which is what `ScriptChecker` already uses.)

Per segment, B's substantive turns and the editorial word share:

| segment | turns | claims | minutes | B turns | B substantive | editorial words |
|---|--:|--:|--:|--:|--:|---|
| seg-001 | 6 | 1 | 2.5 | 3 | **1** | 122/307 = 39.7% |
| seg-002 | 6 | 2 | 3.5 | 3 | **0** | 98/342 = 28.7% |
| seg-003 | 6 | 2 | 2.5 | 3 | **0** | 88/368 = 23.9% |
| seg-004 | 4 | 1 | 1.5 | 2 | **0** | 75/204 = 36.8% |

The shape is identical in every segment: B opens with a recap, A states a claim, B restates
it as a question, A affirms and restates. Four of A's eleven turns open with a bare
affirmation — «بله، دقیقاً» / «دقیقاً همین‌طور است» / «دقیقاً» / «کاملاً درست است» — and
three of the four segments open with a B recap turn («در بخش قبل…», «تا اینجا…» twice).

### 1.2 The prompt already asks for exactly what the audit wants

`prompts/persian_script_segment/1.0.0/system.md:5`, shipped and in force during that run:

> "B is an intelligent interlocutor who asks useful questions, tests distinctions, and
> requests clarification without becoming comic relief. Avoid repetitive greetings, filler,
> fake enthusiasm, and summary padding."

**That is the recommendation, already implemented, and it produced 10 editorial turns out
of 11.** So "reword the prompt more firmly" is not a plan — it is the thing that already
failed. R10 needs structural pressure, not better prose.

The reason it fails is visible in the data model. `ScriptTurnDraft.require_grounding`
(`script.py:54-60`) forces a substantive turn to carry claim **and** evidence IDs. A
segment with 2.5 minutes of airtime and one claim cannot fill the time with substantive
turns, so the cheapest legal way to fill it is `editorial_only=True`. The constraint was
satisfied by **relabelling**, which is exactly what the audit observed:
«قاعده رعایت شده — اما با برچسب‌زدن نیمی از turnها به‌عنوان editorial».

Any fix that can be satisfied by relabelling will be.

### 1.3 The mechanism the audit asks for already exists, and no prompt reads it

`EpisodeSegment.speaker_dynamic` (`domain.py:320-326`) is a required field on every segment:

```python
    speaker_dynamic: Literal["explanation", "questioning", "critique", "comparison", "recap"]
```

The episode planner sets it, `episode.py:91` carries it, and
`PersianScriptWriterService.write_segment` passes the whole segment into the prompt as
`{{ segment }}`. So the model already receives a per-segment instruction about the speaker
dynamic — and:

```bash
grep -rn "speaker_dynamic" prompts/
```

returns **nothing**. Neither the writer's system prompt nor the planner's prompt ever names
the field. The planner's only rule about it is the enum restated as a sentence
(`prompts/episode_plan/1.1.0/system.md`: "Segment dynamics must be one of explanation,
questioning, critique, comparison, or recap") — the five values with no guidance on when
each applies.

The consequence, in the real plan: **`explanation`, `comparison`, `explanation`, `recap`.
`questioning` and `critique` — the two dynamics that would give B a job — were never
chosen.** R10 is not "invent a role for B". It is "connect a field that already exists to
the prompt that already receives it".

### 1.4 Two of the four segments cannot support a non-filler B at all

This is the finding that decides the shape of the deterministic floor in §3.

seg-001 has **one** claim and 2.5 minutes. If you require B to carry a substantive turn
there, B must cite the same claim A just cited — which is precisely the
A→B→A restatement the audit is complaining about. Check the real script: seg-001 turns
003/004/005 are A, B, A, **all three on `clm-d47c35b404043ad8`**. The observed script
already satisfies "B carries a substantive turn" in that segment. The naive rule not only
fails to fix seg-001, it *mandates* the defect.

Claim density per segment-minute: 0.40, 0.57, 0.80, 0.67 — six claims across ten minutes,
about 204 words per claim at 130 wpm. **A two-voice dialogue where B carries its own
material needs at least two claims in the segment.** Two of four segments do not have them.

So: the writer-side fix has a ceiling, and the ceiling is set by the episode planner. §2
keeps the planner out of this PR and §8.4 says why, but the plan must **measure** density
and name it, or the first person to see the floor fail will "fix" it by loosening the floor.

### 1.5 The causal chain, in order

1. `episode_plan` picks `speaker_dynamic` with no guidance → `explanation`/`recap`.
2. `episode_plan` has no claim-density rule → a segment gets 2.5 minutes for one claim.
3. `persian_script_segment` never reads `speaker_dynamic` → B has only generic prose.
4. `ScriptTurnDraft.require_grounding` makes `editorial_only=True` the cheapest legal filler.
5. `ScriptChecker` has no editorial-share or speaker-balance check → G8 sees nothing.
6. G10 shows the reviewer `substantive turns: 11` and nothing about who spoke them.

This PR addresses 3, 5 and 6, and *measures* 1 and 2 so the follow-up is evidence-led.

### 1.6 Out of the blocks — do not redo

- The writer is already per-segment and already validated deterministically
  (`_validate_segment_draft`, `persian_script_writer.py:66-88`). You are extending that
  function, not building a new validation layer.
- `ScriptCheckReport` already carries `word_count`, `estimated_minutes` and
  `substantive_turn_count`, and `script.html:110-113` already renders them. You are adding
  to a row that exists.

---

## 2. Scope

### In scope

| # | Change | File |
|---|---|---|
| 1 | `persian_script_segment/1.1.0` — reads `speaker_dynamic`, states B's job per dynamic, knows its position in the episode | `prompts/persian_script_segment/1.1.0/{contract.json,system.md,user.md}` |
| 2 | `segment_index` / `segment_count` variables, `SpeakerBalancePolicy`, extended `_validate_segment_draft` | `src/thesisound/services/persian_script_writer.py` |
| 3 | Pass position + policy from the pipeline | `src/thesisound/services/script_pipeline_service.py` |
| 4 | `script_speaker_balance_enabled` setting | `src/thesisound/config.py`, `.env.example` |
| 5 | New measured fields + `low`-severity issues in the deterministic checks | `src/thesisound/services/script_checks.py`, `src/thesisound/script.py` |
| 6 | Show the new numbers at G10 | `src/thesisound/web/templates/projects/script.html` |
| 7 | `thesisound script-ab-export` for the blind A/B | `src/thesisound/script_cli.py` |
| 8 | Tests | `tests/test_script_speaker_balance.py` (new), `tests/test_script_quality.py`, `tests/test_ui_language_contract.py` (run, not edited) |

### Explicitly out of scope — do not touch

- **The episode planner and its prompt.** `speaker_dynamic` selection and claim density are
  the real ceiling (§1.4) and fixing them is R10b (§8.4). They are out of this PR for one
  reason: changing the planner *and* the writer at once makes the blind A/B in §8
  uninterpretable — you would not know which change did the work. Measure first.
- **`prompts/persian_script_segment/1.0.0`.** Not one byte. It is the control arm.
- **The `script_reviser` and `script_verifier` prompts** (R6 territory), `script_quality.py`'s
  weights, the `script_quality_gate_enabled` flag.
- **Promoting the new check issues above `low` severity.** See D6; that is a follow-up
  gated on the A/B.
- The `ScriptTurnDraft.require_grounding` rule. It is correct; the problem is what the model
  does *around* it.
- Anything in the corpus stages. R8/R9 are unrelated and in flight — see D10.

---

## 3. Locked design decisions

Read all ten before writing code.

### D1 — The prompt names the dynamic; the validator makes it stick

Two halves of one intervention, and neither works alone:

- Prompt alone was already tried and failed (§1.2).
- A validator alone just causes retries, because the model is not told what is wanted.

Do not ship one without the other, and do not treat them as separable arms of the
experiment. Arm A is "1.0.0 + policy off"; arm B is "1.1.0 + policy on".

### D2 — The floor is conditioned on claim count, because the naive rule mandates the defect

`_validate_segment_draft` gains three rules. Read §1.4 before you touch the thresholds.

| | Rule | Applies when | Fails on the observed run |
|---|---|---|---|
| **F1** | editorial words ≤ 25% of segment words | always, except the opening segment where the cap is 35% | seg-001 (39.7%), seg-002 (28.7%), seg-004 (36.8%) |
| **F2** | at least one B turn is substantive | `len(segment.claim_ids) >= 2` **only** | seg-002, seg-003 |
| **F3** | no claim appears in more than 2 turns of the segment | always | seg-001 (one claim across three turns) |

The `>= 2` condition on F2 is the whole point: applied to a one-claim segment it would force
A and B onto the same claim, which is the restatement pattern. **Do not remove that
condition to "make the rule uniform".**

The opening-segment allowance exists because segment 1 legitimately carries the greeting;
seg-001 still fails at 39.7%, so the allowance costs nothing on the observed data.

Together the three rules bite on **4 of 4** observed segments. That is the calibration
target: the floor must reject the script the audit is complaining about.

### D3 — The floor raises on early attempts and degrades to a check issue on the last

`persian_script_segment` ships `max_attempts: 2` — exactly **one** retry. A hard failure on
the final attempt would abort the whole script build for a stylistic rule, on a stage whose
output the audit calls good.

So mirror the established idiom in `_extract_block` (`evidence_extractor.py:242-249`):
raise `DeterministicValidationError` while attempts remain — `ModelRunner` appends the
repair instruction and retries — and on the final attempt record the violation and return
without raising. The violations then surface as `ScriptCheckIssue`s at G8 (D6) and as
numbers at G10.

**A script build must never fail because of R10.**

### D4 — One setting, defaulting on, and it is also the kill switch

```python
    script_speaker_balance_enabled: bool = True
```

On, because the evidence says prompt-only does not work and there is no point shipping the
half we know fails. Off restores today's validator exactly, which is what arm A of the A/B
needs and what you flip if the floor causes retry churn in practice.

The setting gates **only the floor**, never the prompt version — prompt selection is
`--prompt-version`, and mixing the two mechanisms would make the arms ambiguous.

### D5 — 1.1.0 becomes the production default, and that is acceptable here

`PromptLoader._resolve_version_dir` returns the highest version when `prompt_version is
None`, and production passes `None`. So creating `1.1.0` repoints production the moment it
merges. For R8 that was a reason to defer a prompt change; here it is acceptable, and the
difference is worth understanding rather than copying:

- The script stage sits behind **two** gates the corpus stages do not have — G8 deterministic
  checks and **G10 human review**. Nothing reaches audio without a person reading it.
- The current behaviour is a *measured* defect (31.4% unevidenced words), not a hypothetical
  risk. Staying on 1.0.0 is not the safe option; it is the known-bad option.
- Rollback is total and instant: 1.0.0 stays on disk and `--prompt-version 1.0.0` reaches it
  forever.

Say all three in the PR description. Do **not** generalise this to other stages.

### D6 — G8 reports the new findings at `low` severity; the numbers are fields, not issues

Severity routing in `script_pipeline_service.py:332,353`: a `blocking` issue makes
`checks.verdict == "reject"`, which **skips the verifier entirely** and forces the reviser;
any `high` or `medium` issue makes the verdict `revise`, which also runs the reviser — a
strong-tier model call. On the observed run every segment would trip the new rules, so
anything above `low` means a reviser call on essentially every episode until the writer
reliably satisfies the floor.

Worse, the reviser cannot always fix it: `script_pipeline_service.py:380` zips original and
revised turns with `strict=True`, so a revision **cannot add or remove turns**. "This
segment needs one more substantive B turn" is not always a rewrite.

Therefore:

- New issues (`speaker_balance`, `restatement`) are **`low`**. They appear in the report,
  they change no routing, they cost nothing.
- The *measurements* go on `ScriptCheckReport` as first-class fields, always populated,
  independent of severity — the same way `word_count` and `substantive_turn_count` already
  are. Fields are what the human at G10 and the A/B in §8 actually read.

Promoting to `high` is a follow-up, gated on the A/B showing the writer can satisfy the
floor (§8.4).

### D7 — New report fields default, so old artifacts still load

`ScriptCheckReport` is persisted. Give every new field a default, exactly as
`EvidenceExtractionPlan` does for its R5 counters (`source_analysis.py:77-80`), and put the
same one-line comment saying why.

### D8 — The writer is told where it is in the episode

Add `segment_index` and `segment_count` variables. Three of four segments opened with a B
recap turn because the writer has no idea whether anything came before it — it is called
once per segment with no history. A recap in segment 1 is wrong and a recap in every segment
is padding; the model cannot know which without being told.

This is not optional polish: it removes one of the two structural sources of B's editorial
turns, and it costs about twenty characters of prompt.

### D9 — The A/B is blind, pre-registered, and rates whole episodes

An unblinded read of two scripts by the person who wrote the prompt is not evidence.
`script-ab-export` (§5 Step 7) writes the two scripts with a deterministic, content-derived
arm assignment into `arm-1.md` / `arm-2.md`, plus `key.json` that the rater does not open
until scores are recorded. The rating sheet is written **before** the scripts are read.

Objective metrics (editorial share, B substantive turns, claim repeats, opener repeats) are
printed for both arms alongside — those are not blind, they are arithmetic.

### D10 — Merge order against R8 and R9

R10 touches `persian_script_writer.py`, `script_checks.py`, `script.py`,
`script_pipeline_service.py`, `config.py`, `.env.example`. R8 and R9 touch the corpus stages
and `observability.py`. The only shared files are `config.py` and `.env.example`, and only
by appending a field.

Land in whatever order they finish; on conflict, keep all settings and put them in the order
the files already use (worker knobs together, then script knobs). Do not rebase any of the
three onto the others' behaviour.

---

## 4. Invariants that must not change

| # | Invariant | Guarded by |
|---|---|---|
| I1 | With `script_speaker_balance_enabled=False`, `_validate_segment_draft` behaves exactly as today | every existing test in `tests/test_script_pipeline.py` / `test_script_quality.py`, unedited |
| I2 | A substantive turn still requires claim **and** evidence IDs | `ScriptTurnDraft.require_grounding`, untouched |
| I3 | An editorial turn still may not carry claim or evidence IDs | `_validate_segment_draft`'s existing third rule |
| I4 | Claims and evidence outside the segment/pack are still rejected | the existing first two rules |
| I5 | A script build never fails because of a speaker-balance violation | D3; §6.2 B4 |
| I6 | `checks.verdict` routing is unchanged — no new issue reaches `medium` or above | §6.3 C3 |
| I7 | An old `checks.json` still loads | D7; §6.3 C5 |
| I8 | `persian_script_segment/1.0.0` is byte-identical and still reachable | `git diff`; §6.4 P1 |
| I9 | The G10 page stays Persian-only and within the vocabulary contract | `tests/test_ui_language_contract.py`, run unedited |

**Accepted behaviour changes, and only these three.** Name all three in the PR:

1. `persian_script_segment` resolves to 1.1.0 by default (D5).
2. Segments may take one extra model attempt when the floor is unmet (bounded by
   `max_attempts: 2`, so at most one).
3. `ScriptCheckReport` gains fields and may gain `low` issues; no verdict changes.

---

## 5. Implementation

### Step 1 — `prompts/persian_script_segment/1.1.0/`

`contract.json`: copy 1.0.0, set `"version": "1.1.0"`. **Leave `max_attempts` at 2** — D3
makes the final attempt non-fatal, so raising it would just buy more strong-tier calls.

`system.md`: 1.0.0 has four paragraphs, at lines 1, 3, 5 and 7. Keep **1, 2 and 4 verbatim**
— they carry the grounding, no-outside-knowledge and prompt-injection rules and are not what
R10 is changing. Replace only the third paragraph, the speaker one at line 5, with:

```markdown
Use two speakers. A is the precise explainer. B is a working interlocutor with a job that
changes per segment, given by SEGMENT_JSON.speaker_dynamic:

- explanation  — B asks what the distinction rules out, and what would be true if it were
                 dropped. Not "so you mean X?".
- questioning  — B presses on scope: which cases the claim covers and which it does not.
- critique     — B raises the strongest objection the supplied evidence itself licenses,
                 and marks it as an objection rather than a correction.
- comparison   — B holds the two sides apart and asks which one a hard case falls under.
- recap        — B names what is still unsettled, not what was already said.

Rules for B, in every dynamic:
- Never restate A's previous turn as a question. If B's turn can be removed without losing
  anything, it must not be written.
- When the segment supplies more than one claim, B carries at least one of them itself, and
  a different one from the claim A has just used.
- Never open a turn with a bare affirmation of the other speaker.

Rules for both speakers:
- Editorial turns are transitions only, and must stay under a quarter of the segment's words.
- Do not restate a claim that has already been spoken in this segment.
- SEGMENT_POSITION says where this segment sits. Only the first segment introduces the
  episode, and no segment opens by summarising the previous one.
- Avoid repetitive greetings, filler, fake enthusiasm, and summary padding.
```

Keep `{{ segment_index }}` / `{{ segment_count }}` out of `system.md` — the position belongs
in the user message where the other per-call data lives, and duplicating it across both
templates gives two places to keep in sync for no benefit.

`user.md`: copy 1.0.0 and add the position line before the closing instruction:

```markdown
<SEGMENT_POSITION>
{{ segment_index }} of {{ segment_count }}
</SEGMENT_POSITION>
```

`_render` (`prompt_loader.py:150`) is plain substitution — every `{{ name }}` must be a
supplied variable and nothing else is allowed, so `segment_index` and `segment_count` are
real variables (Step 2), not something the template computes.

Write the prompt in English, as every other prompt in this repository is. The *output* is
Persian; the instructions are not.

### Step 2 — `src/thesisound/services/persian_script_writer.py`

**2a.** The policy value object, module level:

```python
@dataclass(frozen=True, slots=True)
class SpeakerBalancePolicy:
    """The deterministic floor under speaker B's role (audit R10).

    Thresholds are calibrated against the 2026-08-09 script: with these values all four
    of its segments fail at least one rule, which is the point -- that script is the
    defect. `min_claims_for_b_substantive` is load-bearing and is not a tunable: in a
    one-claim segment, requiring B to be substantive forces B onto the same claim A just
    used, which *is* the restatement pattern R10 exists to remove.
    """

    enabled: bool = True
    max_editorial_word_ratio: float = 0.25
    opening_segment_editorial_word_ratio: float = 0.35
    min_claims_for_b_substantive: int = 2
    max_turns_per_claim: int = 2
```

**2b.** `PersianScriptWriterService.__init__` takes `policy: SpeakerBalancePolicy | None = None`
and stores `self.policy = policy or SpeakerBalancePolicy()`. Defaulting here rather than
requiring it keeps every existing test construction working (I1 needs the *disabled* path
to be reachable, not the default to be off).

**2c.** `write_segment` gains keyword-only `segment_index: int = 1` and
`segment_count: int = 1`, adds them to `variables`, and threads a per-call mutable counter
into the validator the way `_extract_block` does:

```python
        attempt = {"n": 0}
        max_attempts = _segment_max_attempts(self.model_runner, prompt_version)
        violations: list[str] = []
        ...
            validator=lambda draft: _validate_segment_draft(
                draft,
                allowed_claim_ids=allowed_claims,
                allowed_evidence_ids=allowed_evidence,
                segment=segment,
                policy=self.policy,
                is_opening=segment_index == 1,
                attempt=attempt,
                max_attempts=max_attempts,
                violations=violations,
            ),
```

`violations` is filled on the final attempt (D3) and returned alongside the turns so the
pipeline can hand it to the checker. Widen the return type to a small dataclass rather than
growing the tuple to four — `write_segment` already returns a 3-tuple and a 4-tuple is where
call sites start getting indices wrong.

**2d.** Extend `_validate_segment_draft`. The existing three rules stay first, unchanged and
unconditional. Then:

```python
    if not policy.enabled:
        return
    attempt["n"] += 1
    failures = _speaker_balance_failures(draft, segment, policy, is_opening=is_opening)
    if not failures:
        return
    if attempt["n"] < max_attempts:
        raise DeterministicValidationError("; ".join(failures))
    # Final attempt: a stylistic floor must never abort a script build (plan D3). Record
    # it instead; ScriptChecker turns these into low-severity issues the G10 reviewer sees.
    violations.extend(failures)
```

`_speaker_balance_failures` is a pure function over `(draft, segment, policy, is_opening)`
returning a list of human-readable strings — pure so §6.1 can table-test it without a model.
It implements F1, F2 and F3 from D2 and nothing else. Word counting uses the same
`re.compile(r"\w+", re.UNICODE)` as `script_checks.py`; import it or duplicate the two-line
constant, do not invent a third tokeniser — the numbers must be comparable across files.

Order the messages F1, F2, F3 deterministically; they end up in a repair instruction and in
an artifact, and a set-ordered message makes diffs unreadable.

### Step 3 — `script_pipeline_service.py`

At the `write_segment` call site, pass `segment_index=index` (1-based) and
`segment_count=len(plan.segments)` from the existing enumeration over plan segments, and
collect the returned violations per segment into a `dict[str, list[str]]` that is handed to
`run_checks`. Do not recompute the violations in the checker: the writer knows which attempt
was final, and the checker does not.

Construct the writer with the policy at the composition roots that build it —
find them with:

```bash
grep -rn "PersianScriptWriterService(" src/
```

### Step 4 — `config.py` and `.env.example`

After the audio/script block in `config.py`, next to `script_quality_gate_enabled`:

```python
    # Audit R10: the deterministic floor under speaker B. On, because the shipped prompt
    # already asked for an interlocutor in prose and got 10 filler turns out of 11 -- the
    # prompt half alone is the configuration we have evidence fails. Off restores the
    # pre-R10 validator exactly and is how the control arm of the blind A/B is run.
    script_speaker_balance_enabled: bool = True
```

`.env.example`, in the **Audio** block next to `THESISOUND_SCRIPT_QUALITY_GATE_ENABLED`:

```
# Speaker-balance floor for the script writer (audit R10). Set to false, together with
# `write-script --prompt-version 1.0.0`, to reproduce the pre-R10 behaviour exactly.
THESISOUND_SCRIPT_SPEAKER_BALANCE_ENABLED=true
```

### Step 5 — `script.py` and `script_checks.py`

**5a.** Two new `issue_type` values in the `Literal` (`script.py:71-83`): `"speaker_balance"`
and `"restatement"`. Append them before `"other"`; the list is persisted, so do not reorder
the existing entries.

**5b.** New defaulted fields on `ScriptCheckReport`:

```python
    # Defaulted so reports written before R10 still load.
    editorial_word_ratio: float = Field(default=0.0, ge=0, le=1)
    speaker_a_word_count: int = Field(default=0, ge=0)
    speaker_b_word_count: int = Field(default=0, ge=0)
    speaker_b_substantive_turn_count: int = Field(default=0, ge=0)
    claims_per_segment_minute: float = Field(default=0.0, ge=0)
```

`claims_per_segment_minute` is §1.4's ceiling made visible: total distinct claim IDs across
segments divided by `episode_plan.estimated_duration_minutes`. On the observed episode it is
0.60. When the floor starts failing, this is the number that says whether the writer or the
planner is at fault — without it, someone will loosen the floor.

**5c.** `ScriptChecker.check` gains an optional
`speaker_balance_violations: dict[str, list[str]] | None = None` and:

- computes the five fields above from `script.turns` in the loop it already runs;
- emits one `low` `speaker_balance` issue per violation string passed in;
- emits a `low` `restatement` issue for each A-turn opening with a bare affirmation, matched
  against a module constant seeded with the four observed forms:

```python
# Observed on the 2026-08-09 script: 4 of speaker A's 11 turns opened by affirming B before
# repeating what B had just restated. Prefix match after whitespace normalisation, not a
# substring search -- "دقیقاً" mid-sentence is ordinary Persian and not a defect.
_AFFIRMATIVE_OPENERS = ("بله، دقیقاً", "دقیقاً همین‌طور است", "دقیقاً", "کاملاً درست است")
```

Note that `«دقیقاً»` is a prefix of `«دقیقاً همین‌طور است»`; match longest-first or the
report will name the wrong form.

Nothing else in `check` changes, and **no new issue may be created above `low`** (I6).

### Step 6 — G10 · `web/templates/projects/script.html`

Add to the stat row at lines 110-113, in the same style as the existing
`{{ checks.substantive_turn_count | fa_num }} گفتهٔ مستند`. Two numbers: the editorial word
share, and B's substantive turn count.

Do not invent vocabulary. The wording is governed by
[`docs/05-ui-redesign/03-product-language.md`](05-ui-redesign/03-product-language.md), and
`tests/test_ui_language_contract.py` holds a forbidden-term list that includes «شواهد» and
«ادعا». Copy the register of the adjacent stat, then run that test — it is the contract, not
a style suggestion. If the term you want is on the forbidden list, the answer is a different
term, not an edit to the list.

### Step 7 — `thesisound script-ab-export`

```
thesisound script-ab-export <project-a> <project-b> --out <dir>
```

Writes `arm-1.md`, `arm-2.md`, `key.json`, `metrics.md`.

- Arm assignment is deterministic and content-derived: sort the two project ids as strings
  and assign in that order. Deterministic so the export is reproducible; the rater simply
  must not look at `key.json`, which is the whole discipline here.
- Each `arm-N.md` contains only speaker labels and spoken text — no turn ids, no segment ids,
  no claim ids, no `editorial_only` flags, no project id. Anything that reveals which arm is
  which defeats the export.
- `metrics.md` holds the objective numbers for both arms side by side (D9): editorial word
  ratio, per-speaker words and turns, B substantive turns, claims per segment-minute, count
  of claims used in more than two turns, count of affirmative openers.
- `key.json` maps arm → project id, and nothing else.

---

## 6. Tests

New module `tests/test_script_speaker_balance.py`, except where noted. Do not edit the
existing script tests; if you need to, I1 is broken.

### 6.1 The floor as a pure function

Table-test `_speaker_balance_failures` directly — no model, no runner. Build drafts with a
small helper.

| # | Case | Expect |
|---|---|---|
| A1 | 25% editorial words exactly, non-opening | no F1 failure (boundary is inclusive) |
| A2 | 26% editorial words, non-opening | F1 failure |
| A3 | 30% editorial words, opening segment | no F1 failure (35% allowance) |
| A4 | 36% editorial words, opening segment | F1 failure |
| A5 | 2-claim segment, B has only editorial turns | F2 failure |
| A6 | 2-claim segment, one B turn substantive | no F2 failure |
| A7 | **1-claim segment, B has only editorial turns** | **no F2 failure** — D2's condition; if this test fails you have removed the thing that stops the rule mandating the defect |
| A8 | one claim used in 3 turns | F3 failure |
| A9 | one claim used in 2 turns | no F3 failure |
| A10 | `policy.enabled=False` | no failures at all, for every case above |
| A11 | a clean draft | empty list |
| A12 | a draft failing all three | exactly three messages, in F1/F2/F3 order |

**A13 — the calibration test.** Reconstruct the four observed segments from the shapes in
§1.1 (turn counts, speaker sequence, editorial flags, claim ids, word counts — synthesise the
text, do not copy the Persian) and assert **every one of the four fails at least one rule**,
with the specific expected failures per segment from D2's table. This is the test that says
the floor is calibrated against the defect rather than against nothing.

### 6.2 The writer

- **B1** with the policy enabled and a runner that returns a failing draft on attempt 1 and a
  clean one on attempt 2, `write_segment` returns the clean turns and no violations.
- **B2** the repair instruction reaching the second attempt contains the F-rule messages —
  assert on the `user_prompt` the fake runner receives, so the retry is actually informative.
- **B3** with `policy.enabled=False`, a failing draft is accepted unchanged and the runner is
  called **once** (I1).
- **B4 (I5)** a runner that returns a failing draft on **every** attempt: `write_segment`
  returns normally, the turns are the last draft's, and `violations` is non-empty. It must not
  raise — parametrise over `max_attempts` in `{1, 2, 3}`.
- **B5** `segment_index` and `segment_count` reach the rendered prompt: render the real
  1.1.0 template through `PromptLoader` and assert `"2 of 4"` appears and no `{{` remains.
  (The R1 lesson: a prompt no test renders is a prompt that can silently break.)
- **B6** the existing three validation rules still fire with the policy both on and off —
  claims outside the segment, evidence outside the pack, editorial turn carrying ids (I2-I4).

### 6.3 The checks report

- **C1** the five new fields are computed correctly on a known script; assert
  `editorial_word_ratio` to 3 decimal places on a hand-counted fixture.
- **C2** violations passed in become exactly that many `low` `speaker_balance` issues.
- **C3 (I6)** a report containing only the new issue types still has
  `verdict == "pass"`, and `script_pipeline_service` therefore does not call the reviser.
  Assert the verdict, and assert the reviser was not called.
- **C4** the affirmative-opener matcher: hits each of the four observed forms as a prefix;
  does **not** hit «دقیقاً» appearing mid-sentence; reports the longest matching form when
  two overlap.
- **C5 (I7)** a `ScriptCheckReport` JSON payload without any of the new fields validates,
  with zeros — mirror `test_old_extraction_artifacts_default_failure_kind_to_none`
  (`tests/test_evidence_fanout.py:229`).
- **C6** `claims_per_segment_minute` on a 6-claim, 10-minute plan is 0.60.

### 6.4 Prompt and contract

- **P1 (I8)** `persian_script_segment/1.0.0` is unchanged: assert its rendered length for a
  fixed variables dict equals a locked constant, and that `load_contract(...,
  version="1.0.0").max_attempts == 2`.
- **P2** 1.1.0's contract has `version == "1.1.0"`, `output_model == "SegmentScriptDraft"`,
  `model_tier == "strong"`, `max_attempts == 2`.
- **P3** `PromptLoader().load_bundle("persian_script_segment", vars)` with no version pin
  resolves to **1.1.0** — the D5 default change, asserted rather than assumed.
- **P4** 1.1.0's system prompt still contains the untrusted-data sentence and the
  no-outside-knowledge sentence carried over verbatim from 1.0.0. Assert the exact strings:
  those are the injection and grounding rules, and this PR is the most likely place to lose
  them by accident.

### 6.5 Export command

- **E1** `script-ab-export` writes four files; `arm-1.md` and `arm-2.md` contain no project
  id, no turn id, no segment id, no claim id, and no `editorial_only` string.
- **E2** arm assignment is deterministic: run it twice, same mapping.
- **E3** `metrics.md` reports both arms and the six objective metrics from Step 7.

### 6.6 Hygiene

- Do not copy the Arendt script text into a fixture. Synthesise Persian of the right shape;
  the tests are about counts and flags, not content.
- Run `tests/test_ui_language_contract.py` after Step 6, unedited (I9).
- No test may change a threshold on `SpeakerBalancePolicy` to make itself pass. If a test
  needs different thresholds, construct a policy explicitly and say why in a comment.

---

## 7. Verification

```bash
uv run ruff check .
```

```bash
uv run pytest tests/test_script_speaker_balance.py tests/test_script_pipeline.py tests/test_script_quality.py tests/test_script_run.py tests/test_prompt_rendering.py tests/test_ui_language_contract.py tests/test_web_script_flow.py -v
```

```bash
uv run pytest
```

Then by hand:

- [ ] `git diff prompts/persian_script_segment/1.0.0/` is empty.
- [ ] `grep -rn "speaker_dynamic" prompts/persian_script_segment/1.1.0/` returns a hit.
- [ ] `grep -rn "PersianScriptWriterService(" src/` — every production site passes the policy.
- [ ] `grep -n "severity=" src/thesisound/services/script_checks.py` — the two new issue types
      are `low` and nothing else changed severity.
- [ ] `ScriptTurnDraft.require_grounding` and the first three rules of
      `_validate_segment_draft` are unchanged.
- [ ] `min_claims_for_b_substantive` is still `2` and still carries its comment.
- [ ] `docs/05-ui-redesign/03-product-language.md` sanity-checked for the two new labels.
- [ ] Replay: run `ScriptChecker` over the committed
      `workspaces/f781a5c7-…/script/script-draft.json` and confirm the report now shows
      `editorial_word_ratio ≈ 0.314`, `speaker_b_substantive_turn_count == 1`,
      `claims_per_segment_minute == 0.60`, and `verdict` **unchanged from the stored
      `checks.json`**. Paste that into the PR. It is the cheapest possible proof that the
      measurement is right and the routing is not.

**No live provider run in this PR.** §8 needs approval first.

---

## 8. The blind A/B (needs approval — ~2 script builds)

Stop and ask before running this.

### 8.1 Setup

Two projects from the **same** episode plan, so the only difference is the writer. The corpus
and plan are already paid for: `workspaces/_shared/document-maps/` holds this EPUB's map, and
the approved plan is in `workspaces/f781a5c7-…/project.json`. Copy that plan and its glossary
into both arms rather than re-planning — a re-plan would change segments, and then you are
comparing plans, not prompts.

```bash
# Arm A -- pre-R10 behaviour, exactly
THESISOUND_SCRIPT_SPEAKER_BALANCE_ENABLED=false thesisound write-script <project-a> --prompt-version 1.0.0
```

```bash
# Arm B -- R10
thesisound write-script <project-b>
```

Both must resolve the same `strong` model. Confirm from the run records before rating; a
model difference invalidates the comparison. Cost is roughly two script builds — on the
observed run, `script_segment` was 79,480 input and 6,694 output tokens across 8 runs.

### 8.2 Pre-register the rating sheet, then export

Write the sheet **before** reading either script. Five items, each 1-5, one rater minimum,
three preferred, no discussion between raters until all have scored:

1. Does B contribute anything A did not already say?
2. Does B ever test, limit, or object to a claim?
3. Is the dialogue free of A→B→A restatement?
4. Is the Persian natural and speakable?
5. Is the terminology consistent with the glossary?

Items 4 and 5 are the guard rails: R10 must not buy B's role at the cost of the thing the
audit says already works. **A win on 1-3 with a loss on 4-5 is not a win.**

```bash
thesisound script-ab-export <project-a> <project-b> --out ./ab-r10
```

Read `arm-1.md` and `arm-2.md`. Score. Only then open `key.json`.

### 8.3 The decision

| Outcome | Do |
|---|---|
| Arm B wins items 1-3 and does not lose 4-5 | Keep 1.1.0 as default. Then promote the G8 issues from `low` to `high` in a follow-up, since the writer has demonstrably satisfied the floor. |
| Arm B wins 1-3 but loses 4-5 | Keep 1.1.0, keep the issues at `low`, and open a narrower prompt revision. The floor is right; the prose is doing damage. |
| No difference, or arm B loses | Revert the default to 1.0.0 and set `script_speaker_balance_enabled=false`. Then read `metrics.md`: if arm B's `claims_per_segment_minute` is still ≈0.6, the writer was never the binding constraint and R10b (§8.4) is the real work. |

Record in the PR: both project ids, the resolved model, the prompt versions, the raters, the
pre-registered sheet, and `n = 1 episode, 1 corpus, 1 language, 1 duration`. The audit's
Constraint 1 applies here too — one episode is not evidence that this generalises.

### 8.4 R10b — the follow-up this PR deliberately does not do

§1.4 shows the writer-side ceiling. Two planner-side changes, in one later PR, after the A/B:

1. **`episode_plan`'s prompt should say what the five `speaker_dynamic` values mean and when
   to choose them.** It currently only restates the enum, and the planner picked
   `explanation`/`comparison`/`explanation`/`recap` — never `questioning`, never `critique`.
2. **A claim-density rule**, so a segment is not allocated 2.5 minutes for one claim. The
   natural form is a minimum claims-per-minute in the planner prompt plus a deterministic
   check in the plan validator, mirroring the floor this PR adds to the writer.

Both change what a human approves at G7, so they need their own validation — which is why
they are not in this PR: changing the planner and the writer together would make the §8 A/B
uninterpretable.

---

## 9. Definition of done

1. Steps 1-7 implemented exactly as specified.
2. §6.1-6.6 written and passing, including the A13 calibration test and the A7 one-claim
   exemption.
3. Full `uv run pytest` and `uv run ruff check .` green.
4. §7 checklist walked, including the replay against the committed real script, pasted into
   the PR.
5. PR description states: the three accepted behaviour changes from §4; that 1.1.0 becomes
   the default and why that is acceptable *here* specifically (D5); that the shipped 1.0.0
   prompt **already** asked for an interlocutor and got 10 filler turns out of 11 (§1.2);
   that `speaker_dynamic` already existed and no prompt read it (§1.3); that two of four
   observed segments cannot support a non-filler B at any prompt (§1.4); and that the A/B
   has **not** been run.

**Do not** change the episode planner, promote the new issues above `low`, bundle R8 or R9,
or "improve" the verifier while you are in the tree. One recommendation, one PR.
