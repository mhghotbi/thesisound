# 12 — A Stop Budget for the Build

Date: 2026-08-13 · Status: proposed · Effort: M · Source: two independent MVP readiness audits both finding the human gate count too high, plus two `raise` sites that spec 09's own remediation ladder added the day after those audits were written

Specs 09, 10 and 11 asked, one failure at a time, *should this stop the build?* This spec asks the prior question: **how many times may a build stop at all?**

The distinction matters because the two kinds of stop are counted in different places and by different people. An approval screen is designed deliberately and reviewed as UX. A validator `raise` is added defensively and reviewed as correctness. To the user they are the same event — a click, a context switch, and a chance they do not come back. Counting them separately is exactly how the total drifted past what anyone chose.

This spec puts them on one budget, then spends that budget.

## 1. Measured problem

### 1.1 Every point where the current build hands control to a human

| # | Where | What the user supplies | Spec 11 D1 reason | Verdict |
|---|---|---|---|---|
| 1 | [`corpus/confirm`](../../src/thesisound/web/source_routes.py:737) | which sources are in | 2 (changeable input) + 3 (consent — the largest single spend) | **keep** |
| 2 | [`episode/prepare`](../../src/thesisound/web/episode_routes.py:195) | **nothing** | **none** | **remove** |
| 3 | [`script/approve`](../../src/thesisound/web/script_routes.py:99) | plan approval; duration and priority renegotiation | 1 (asymmetry) + 3 (consent) | **keep** |
| 4 | [`audio/generate`](../../src/thesisound/web/audio_routes.py:90) | 7 form fields, 5 of which already have defaults | 3 (consent) + 1 (voice) | **keep, one click** |
| 5 | [`script/review`](../../src/thesisound/web/script_routes.py:143) — conditional | accept, or send back with a reason | 4 (integrity) | **keep the choice, drop the screen** |
| 6 | [`script_grounding_remediation.py:65`](../../src/thesisound/services/script_grounding_remediation.py:65) | **nothing** | claims 4 — **does not hold** | **defect** |
| 7 | [`script_grounding_remediation.py:111`](../../src/thesisound/services/script_grounding_remediation.py:111) | **nothing** | claims 4 — **does not hold** | **defect** |

Two corrections to the audits, both in the same direction:

- Their count of six is stale. [`03-inline-research-brief.md`](03-inline-research-brief.md) shipped, merging brief confirmation into the creation form, and the source-selection and corpus-confirmation gates are one click, not two. The live count of deliberate stops is **four**.
- Neither audit could see rows 6 and 7. Spec 09 added them on 2026-08-13, the day after. **The programme that was supposed to remove stops added two.** That is not an argument against spec 09; it is the argument for a budget, because nothing in spec 09 required anyone to look at the total.

### 1.2 The two undeclared stops fail their own justification

Both raises in [`script_grounding_remediation.py`](../../src/thesisound/services/script_grounding_remediation.py) declare `stop_reason="integrity_breach"` — spec 11 D1 reason 4. Read against that clause's own wording, *"shipping the artifact would break the product's core promise"*:

**Line 65 — a turn cites a claim that carries no evidence.** The passage is genuinely unsupported, so it must not be spoken. But excising it does not ship it. The promise is kept by removing one passage, and spec 09 D3 is explicit that rung 3 requires stating why rungs 1 and 2 do not apply. Rung 2 applies here. The comment says excision "would hide an upstream ledger fault" — a real concern, and the wrong remedy: hiding it from the *listener* is correct, hiding it from *us* is the thing to prevent, and that is a telemetry problem (D6), not a reason to destroy the episode.

**Line 111 — excision would drop the script below 80% of its duration band.** A shorter episode is a shorter episode. Nothing about it is unsupported, misattributed, or misleading. This stops a build on a quality preference and files it under integrity.

Both are, in the exact words the user used about the earlier failures, defects the user is asked to press a button about while holding no information the system lacks.

### 1.3 `episode/prepare` is a button with nothing behind it

Verbatim, the screen that precedes it ([`episode.html:22`](../../src/thesisound/web/templates/projects/episode.html:22)):

> منابع آماده‌اند؛ حالا سقف واقعی گفتار را محاسبه می‌کنیم

One heading, one sentence, one button, no input. The user confirmed the corpus on the previous screen and has learned nothing since. Under D1 the click carries no reason at all — not consent (already given, and to a larger spend), not information (none requested), not integrity (nothing has been produced yet).

### 1.4 The registry does not know the real shape

[`GATE_REGISTRY`](../../src/thesisound/services/gates.py:21) has twelve entries, five of them `actor="human"`. It has no entry for starting audio, which is a human stop. And `source-selection-confirmed` points at [`source_routes.py:610`](../../src/thesisound/web/source_routes.py:610), which is inside the source-*deletion* handler; the gate it names is enforced 127 lines later. A registry that neither counts the stops nor locates them cannot be the thing that holds a budget — until it is fixed, which is D1's job.

## 2. Design

### D1 — The budget: three stops

Between corpus confirmation and audio start, a build may hand control to the user **at most three times**:

| Stop | Reason it exists | Cannot be removed because |
|---|---|---|
| **Sources** | D1.2 + D1.3 | the user chooses what the episode is made of, and this authorises the largest spend |
| **Plan** | D1.1 + D1.3 | coverage, duration and priorities are the user's intent, not inferable — this is the negotiation [`05-plan-priorities.md`](05-plan-priorities.md) is built around |
| **Audio** | D1.3 + D1.1 | TTS is the irreversible spend, and voice is a preference |

Everything before the first stop is the entry form; everything after the third is the artifact. The final-listen gate is not counted — it is not a stop in a build, it is the product being used.

Two enforcement mechanisms, because a rule with no mechanism is what produced §1.1:

1. `GATE_REGISTRY` gains an `audio-start` entry, `script-review-decision` becomes non-blocking (D4), and a test asserts that exactly three registry entries are `actor="human"` and blocking on the build path.
2. Every raise that stops a build carries a `stop_reason`. A test asserts each maps to a D1 reason **and** that the raise site's own comment states why the two lower rungs of spec 09 D3 do not apply. §1.2 is what happens when only the first half is checked.

The corollary is the point: **a fourth stop cannot be added without removing one or amending this spec.** Same role as spec 09 D4, one level up.

### D2 — Fold `episode/prepare` into corpus confirmation

Confirming the corpus queues coverage and planning as well. The user's next screen is the plan.

Safe because nothing crosses the removed click: consent was already given to a larger spend one screen earlier (~$0.5 extraction vs ~$0.1 planning, audit §6–7), no information was requested, and the plan stop still stands between this and anything irreversible.

The insufficient-coverage branch is untouched. It stops under reason 2 with the one message both audits singled out as correctly written, and it keeps `episode/duration` and `episode/reopen-inputs`.

**Accepted trade:** today a user could, in principle, change the target duration on the pre-plan screen. In practice that screen offers no such control — the duration form appears only in the blocked and planned branches — so nothing is lost, and [`episode/duration`](../../src/thesisound/web/episode_routes.py:249) remains available at the plan stop with its existing cost hint.

### D3 — Grounding degrades; it does not stop

| Situation | Today | Under this spec |
|---|---|---|
| Turn's evidence misses its claims' evidence, but the claims *have* evidence | repair, `grounding_repaired` | unchanged |
| Turn cites a claim with **no** evidence | **raise** ([:65](../../src/thesisound/services/script_grounding_remediation.py:65)) | excise the turn, `turn_excised`, record an `ungrounded_claim` fault |
| Turn cites no known claim at all | excise | unchanged |
| Excision empties a segment | **raise** ([:111](../../src/thesisound/services/script_grounding_remediation.py:111)) | excise the whole segment, including its editorial turns, one note |
| Excision drops the script under its duration band | **raise** ([:111](../../src/thesisound/services/script_grounding_remediation.py:111)) | keep it, one `duration_shortfall` note, let the ceiling decide |
| Excision would empty the script | raise | **raise — the only survivor** |

The last row is a genuine reason 4 and the only one: there is no artifact left, so there is nothing to degrade and nothing to disclose. It is also close to unreachable unless the ledger upstream is broken, which is precisely when stopping is right.

Removing an editorial turn along with its segment is deliberate. Editorial turns are framing for substance that is no longer there; leaving them produces a segment that introduces a point it never makes.

Cumulative degradation stays bounded — by [`exceeds_degradation_ceiling`](../../src/thesisound/services/quality_notes.py:70) alone. Today a floor kills the build and a ceiling routes it to review, two mechanisms for one concern with the harsher one firing first. After this spec there is one threshold in one place, and its consequence is `review_required`, never `rejected`.

**Case B is an upstream fault, not a script fault.** A claim reaching the writer with no evidence means the failure happened in extraction or reconciliation. Excising is the correct listener-facing remedy and the wrong place to fix it. D6 is what stops that from becoming permanent.

### D4 — The integrity stop shares the audio screen

`review_required` currently means a separate `SCRIPT_REVIEW_REQUIRED` screen, before the user may reach audio. The two choices on it — accept, or send back — are the two choices they face on the audio screen anyway.

Move them there. When notes are present, the audio screen renders `notable` notes above the fold (already required by spec 11 D3) with two buttons: **«صدا بساز»** and **«بازنویسی کن»**. The first writes the review decision — `disposition="accepted"`, reviewer from the session, `reason_code="accepted_with_notes"` — and starts audio in the same request.

Nothing is weakened: same two choices, same audit trail, same named reviewer, `send_back` unchanged and its reason still required, where it is actually informative. What is removed is one navigation and a mandatory free-text field on the path the reviewer takes when they agree.

This is the spec's central exchange, so state it plainly: **a stop is being traded for a disclosure.** It is only honest if the disclosure is on the same screen as the button, before the click. §4.8 is that guarantee.

### D5 — Audio starts in one click

`voice_a` and `voice_b` gain defaults in [`audio_direction.py:26`](../../src/thesisound/services/audio_direction.py:26); the route accepts a bare submit; the seven-field direction form becomes an optional disclosure the user opens if they want it. Preferences already persist, so a returning user's choices are still theirs.

### D6 — Count what was absorbed, with the thresholds set first

Per-run counters, kept **separate** — a flood of harmless Case A hides a small number of serious Case B:

| Counter | What it means | Pre-committed trigger |
|---|---|---|
| `grounding_repaired` | the writer mislabels links it was given — engineering defect, no listener impact | >20% of substantive turns across 5 consecutive runs → fix the writer prompt, not the repair |
| `turn_excised` (evidence-less claim) | a claim reached the writer unsupported — upstream data fault | any occurrence in 2 consecutive runs → investigate extraction and reconciliation |
| `turn_excised` (unknown claim) | the writer invented an id | any occurrence → prompt or schema defect |
| `duration_shortfall` | excision cost measurable length | >10% of runs → the ceiling is too permissive |
| automatic retries ([`10`](10-automatic-run-recovery.md)) | recovery becoming the normal path | any run needing 2 → look at routing before anything else |

The numbers are provisional and will move once there is data. What is not provisional is that they exist **before** the data does. A degradation path shipped without a pre-committed trigger does not get measured and fixed later; it gets normalised. Spec 09 §4.7 already names this as the regression that matters most — this is its instrumentation.

## 3. Non-goals

- **Removing the three remaining stops.** Each is held by a named D1 reason, and the plan stop in particular is a product feature, not overhead.
- **Auto-approving a plan.** Reason 1 holds permanently: the system cannot infer what the user wants covered.
- **Changing what counts as an integrity breach.** D3 narrows the *remedy*, not the definition. A passage that cannot be grounded is still never spoken.
- **Weakening `script_outcome`.** Verification and the ceiling are unchanged; what changes is that they become the only route to review, instead of competing with raises that pre-empt them.
- **Removing `send_back`, the review record, or reviewer identity.**
- **Tuning the ceiling.** D6 produces the evidence for that; this spec does not spend it.

## 4. Acceptance criteria

1. A build from three ready sources at default duration, with one degraded turn, completes with exactly three user actions.
2. Removing `episode/prepare` does not remove the insufficient-coverage stop, and that stop keeps its current message verbatim.
3. A turn citing a claim with no evidence is excised and the build completes; the run records an `ungrounded_claim` fault.
4. A script losing 30% of its length to excision completes and ends `review_required`, never `rejected`.
5. The only surviving raise in `script_grounding_remediation` is the empty-script case, and its comment states why rungs 1 and 2 do not apply.
6. Exactly three `GATE_REGISTRY` entries are human and blocking on the build path, and every one resolves to the line that actually enforces it.
7. Accepting a degraded script from the audio screen writes a review record indistinguishable from today's `/script/review` accept.
8. Audio cannot start on a script carrying `notable` notes unless those notes were rendered on the same screen as the button. **This is the regression that matters most: the whole spec trades stops for disclosure, and an undisclosed degradation makes it a strictly worse product than the one it replaces.**

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_happy_path_takes_exactly_three_user_actions` | D1, §4.1 |
| `test_corpus_confirmation_queues_planning` | D2 |
| `test_insufficient_coverage_still_stops_with_its_message` | D2, §4.2 |
| `test_evidence_less_claim_is_excised_not_raised` | D3, §4.3 |
| `test_emptied_segment_is_excised_whole` | D3 |
| `test_duration_shortfall_notes_instead_of_raising` | D3 |
| `test_heavy_excision_ends_review_required_not_rejected` | D3, §4.4 |
| `test_empty_script_is_the_only_grounding_raise` | D3, §4.5 |
| `test_every_human_gate_maps_to_a_stop_reason` | D1, §4.6 |
| `test_gate_registry_pointers_resolve_to_enforcement` | D1, §4.6 |
| `test_audio_screen_accept_writes_the_review_record` | D4, §4.7 |
| `test_audio_start_requires_rendered_notes_when_degraded` | D4, §4.8 |
| `test_audio_starts_with_no_direction_fields` | D5 |
| `test_repair_and_excise_are_counted_separately` | D6 |

## 6. Sequencing

**D3 → D6 → D2 → D4 → D5.**

D3 first: it is the only part addressing a failure users are hitting now. D6 immediately after, and not later — it must be live before D3's absorbed failures start disappearing, or the first weeks of exactly the data we need are lost. D2, D4 and D5 are path shortening; they are independent of each other and can ship in any order, though D4 depends on spec 11 D3's note rendering already being in place.

D1's registry work lands with D4, since that is when the human-gate set actually changes.

## 7. Related

- [`09-degrade-instead-of-fail.md`](09-degrade-instead-of-fail.md) — the remedy ladder this spec finishes applying; D3 here removes the two rung-3 escapes it left behind.
- [`11-failure-disclosure-and-stop-criteria.md`](11-failure-disclosure-and-stop-criteria.md) — supplies D1's four reasons and `QualityNote`; this spec makes the four reasons countable rather than only checkable one at a time.
- [`10-automatic-run-recovery.md`](10-automatic-run-recovery.md) — removes the accidental stops this spec does not budget for.
- [`03-inline-research-brief.md`](03-inline-research-brief.md) — the first gate removal, and the precedent for merging a confirmation into a screen the user already visits.
- [`05-plan-priorities.md`](05-plan-priorities.md) — why the plan stop is a negotiation worth keeping rather than a ceremony.
- [`thesisound-mvp-readiness-audit-fa.html`](../thesisound-mvp-readiness-audit-fa.html), [`thesisound-mvp-readiness-audit-2026-08-12-fa.html`](../thesisound-mvp-readiness-audit-2026-08-12-fa.html) — both call the gate count too high; §1.1 corrects their number and adds what they could not have seen.
