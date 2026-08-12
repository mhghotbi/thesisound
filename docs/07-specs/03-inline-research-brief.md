# 03 — Research Brief: One-Step Confirmation

Date: 2026-08-12 · Status: **implemented** (2026-08-12, same day as this revision) · Effort: S · Source: [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html), "Simplify / Change before MVP" — *brief in the same page, editable, without a separate approval*

Remove the brief's standalone approval screen from the user's path without removing `BRIEF_READY` from the state machine. What shipped differs from this spec's original proposal in one deliberate way: the merge point is the **project-creation form**, not an inline panel on the project page — see §3 for why, and §8 for what changed and why the original design was dropped in favor of it.

## 1. Position

**Adopted, as a UI change only.** The audit's reasoning held: the brief is a form the operator fills in once, and stopping on a second screen just to click "confirm" on what they just typed adds a screen and a click before any value is produced. The original version of this spec already got the expensive part right — don't delete `BRIEF_READY`, don't touch the 12-gate registry's numbering — see §2, which is unchanged from the original proposal and was validated by the implementation exactly as written.

## 2. What the state costs to remove

`ProjectState.BRIEF_READY` has **22 references across 11 files** (one more than at proposal time — the implementation added a second, explicit `transition()` call rather than collapsing the two):

```
domain.py · pipeline.py · product_metrics/catalogue.py · services/eval_harness.py
services/readiness.py · services/research_brief.py · services/source_analysis_service.py
services/workflow_revision.py · web/app.py · web/read_models.py · web/source_routes.py
```

It is load-bearing in four places that have nothing to do with the screen:

| Consumer | Use |
|---|---|
| [`pipeline.py:20`](../../src/thesisound/pipeline.py:20) | `DRAFT → BRIEF_READY → SOURCES_COLLECTING` is the only path out of `DRAFT` |
| [`readiness.py:99`](../../src/thesisound/services/readiness.py:99) | gate `brief-confirmed` reads `state == BRIEF_READY` as "still needs confirmation" |
| [`gates.py:21-31`](../../src/thesisound/services/gates.py:21) | gate 1 of 12 in the registry; `writes` is literally "SOURCES_COLLECTING state" |
| `eval_harness.py`, `workflow_revision.py` | replay and rewind both step through the state — and rewind is why it stayed a *state*, not a boolean; see §3.3 |

Deleting the state would have meant touching all of that, re-numbering the gate registry, and invalidating stored projects — for zero user-visible benefit beyond what §3 delivers. This reasoning held up unmodified through implementation.

## 3. Design, as shipped

### 3.1 One form, not two

The original proposal (see §8) moved the brief onto the project page as a collapsible panel. What shipped instead: `must_include` and `exclusions` — the two fields that used to only exist on the separate `/brief` screen — moved onto the project-creation form itself ([`new.html:60-67`](../../src/thesisound/web/templates/projects/new.html:60)), both optional. The page copy says so plainly: *"با ثبت همین فرم تحلیل منابع آغاز میشود؛ بعداً هم میتوانید این برداشت را ویرایش کنید."* ("Submitting this form starts source analysis; you can still edit this brief afterward.") — [`new.html:41`](../../src/thesisound/web/templates/projects/new.html:41). The submit button reads *"تأیید و شروع تحلیل منابع"* ("Confirm and start source analysis"), not "Create brief" — [`new.html:111`](../../src/thesisound/web/templates/projects/new.html:111).

`create_project` ([`app.py:838-933`](../../src/thesisound/web/app.py:838)) builds the `ResearchBrief` directly from all of this form's fields, including the new scope ones ([`app.py:857-872`](../../src/thesisound/web/app.py:857)), then advances the state machine through both steps in one request:

```python
project = Project(raw_input=topic, brief=brief)
# This form is the whole gate: the operator wrote the question and
# (optionally) the scope, so submitting it is the real confirmation --
# there is no separate approval screen to stop at. BRIEF_READY is
# still visited (not skipped) because workflow rewind targets it
# directly; see workflow_revision.rewind().
transition(project, ProjectState.BRIEF_READY)
transition(project, ProjectState.SOURCES_COLLECTING)
```
— [`app.py:873-880`](../../src/thesisound/web/app.py:873)

Both `PROJECT_CREATED` and `GATE_BRIEF_CONFIRMED` are emitted from this one request ([`app.py:895-911`](../../src/thesisound/web/app.py:895)), and the response redirects straight to `/projects/{project_id}/sources`, not to the brief screen ([`app.py:930-933`](../../src/thesisound/web/app.py:930)).

The existing confirm handler in `save_brief` is unchanged in shape — it is still conditional on `project.state == ProjectState.BRIEF_READY` ([`app.py:1012`](../../src/thesisound/web/app.py:1012)), which is now simply never true for a freshly created project, and remains true only for the rewind path (§3.3). That guard is still what makes this safe: post-creation, the condition is false and later saves edit the brief without attempting a transition.

### 3.2 Why not the inline-panel design

The original proposal's §3.2 put the brief on the *project* page as a collapsible panel, reachable after creation. That was dropped for a simpler reason than aesthetics: the brief's two scope fields (`must_include`, `exclusions`) are exactly the fields a first-time operator is most likely to want *before* committing to a topic, not after. Putting them on the creation form means the one moment of friction removed by this spec is also the one moment those fields are most useful — an inline panel on a page the operator only reaches *after* creating the project would have added a click to reach fields that belong before it.

The brief remains reachable and editable at `/projects/{project_id}/brief` at any later point — nothing about editability was lost, only the *forced stop*.

### 3.3 The gate stays real for rewind

`workflow_revision.rewind(target="brief")` still sets `project.state = ProjectState.BRIEF_READY` ([`workflow_revision.py:92-99`](../../src/thesisound/services/workflow_revision.py:92)), and rewinding to sources while still `BRIEF_READY` is still explicitly rejected ([`workflow_revision.py:82-83`](../../src/thesisound/services/workflow_revision.py:82)). So `BRIEF_READY` is not a state the implementation merely tolerates for legacy reasons — it is a state a project can be in *today*, deliberately, whenever an operator rewinds a project that already has sources or further progress back to the brief. `brief.html` reflects this with state-conditional copy rather than one fixed message:

```jinja
{% if project.state.value == 'brief_ready' %}
<p>این تأیید واقعی است: تا زمانی که برداشت اولیه را تأیید نکنید، افزودن یا تحلیل منابع شروع نمی‌شود.</p>
{% else %}
<p>این برداشت اولیه معیار انتخاب منبع، سنجش کفایت و ساختار گفتار است. هر زمان لازم بود می‌توانید ویرایشش کنید.</p>
{% endif %}
```
— [`brief.html:14-18`](../../src/thesisound/web/templates/projects/brief.html:14)

The blocking promise — *"this confirmation is real"* — is true and shown exactly when it is true (a rewound project sitting in `BRIEF_READY`, genuinely blocked from sources until re-confirmed), and replaced with a non-blocking statement everywhere else. The "saved" notice on lines 22-28 of the same template follows the identical split. This is a refinement the original proposal did not anticipate, because it assumed the panel-on-project-page design where this ambiguity didn't arise.

### 3.4 Gate semantics

`brief-confirmed` stays in the registry as gate 1, keeping its code, label, and order — the original proposal's §3.3 got this right and it shipped unchanged. What differs from the original proposal: **`actor` stays `human`**, not `system`. The operator still explicitly writes and submits the form that becomes the brief; nothing auto-confirms on their behalf. `blocked_means` was reworded to describe the real remaining failure — an empty topic, not a pending approval:

| Field | Before | Now |
|---|---|---|
| `enforced_at` | `web/app.py:787` (already stale at proposal time — pointed at an unrelated route) | [`web/app.py:880`](../../src/thesisound/web/app.py:880) — the second `transition()` call |
| `blocked_means` | "The operator has not confirmed the brief." | "The operator has not submitted the project brief (topic and, optionally, scope)." |
| recovery (SOP doc only) | "Correct or narrow the brief, then confirm it." | "Write a topic (and, optionally, scope) and submit the project-creation form; edit the brief afterward at any time." |

[`docs/06-operations/03-production-sop.md`](../06-operations/03-production-sop.md)'s stated reason for `brief-confirmed` being a human-only gate — *"the operator owns the intended question and scope; a model cannot confirm the operator's intent on their behalf"* — needed no change. It was never about a model confirming anything; no model was ever in this path (§5).

## 4. Non-goals

- Removing `BRIEF_READY` from `ProjectState`, the transition table, or the gate registry. Confirmed unnecessary; see §2 and §3.3.
- Changing what a brief contains.
- Touching the other two approvals (source selection, episode plan). Out of scope then and now.
- Rewind and revision semantics for an edited brief — unchanged, and now load-bearing for why `BRIEF_READY` had to stay a real, re-enterable state (§3.3).
- Retiring `ResearchBriefService` / `research_brief.py`. It has no callers left in the web app (§5) but is still wired into [`cli.py:229`](../../src/thesisound/cli.py:229) (a standalone CLI command that generates a brief via the model for an already-existing project); deciding whether that command should also drop the model call is a separate question this spec does not answer.

## 5. A premise this spec got wrong at proposal time

The original §3.1 said: *"The generation path already transitions `DRAFT → BRIEF_READY` ([`research_brief.py:85`](../../src/thesisound/services/research_brief.py:85))."* That is true of `ResearchBriefService.build()`, but that method is not, and — as far as this revision could determine — was never, called from the web app's project-creation route. `create_project` has always built `ResearchBrief` directly from form fields (a hardcoded `learning_objectives` string included, [`app.py:865`](../../src/thesisound/web/app.py:865)), with no model call on the path a browser user takes. `ResearchBriefService` is real, tested code, but its only remaining caller anywhere in the codebase is [`cli.py:229`](../../src/thesisound/cli.py:229) — a standalone CLI command that generates a brief via the model for an already-existing project (`project_id` is a required argument, not something the command creates), not the web app. `services/eval_harness.py` builds its `Project` from a pre-authored fixture `brief` directly too ([`eval_harness.py:254`](../../src/thesisound/services/eval_harness.py:254)), so it never exercised the model path either. The audit's finding that three recorded projects all got an identical, boilerplate brief is fully explained by this: they went through the same hardcoded literal in `create_project`, not through a model that happened to produce the same output three times.

Net effect on this spec: §3's design needed no rework because of this — auto-advancing past `BRIEF_READY` is correct regardless of whether generation is a model call or a literal — but any future reader relying on the original §3.1 to understand *why* `BRIEF_READY` gets reached would have been reasoning from a path that doesn't execute for a single real user today.

## 6. Acceptance criteria

1. Creating a project lands it in `SOURCES_COLLECTING` with no user action between form submission and the sources step. ✅ [`app.py:879-880`](../../src/thesisound/web/app.py:879), verified by `test_create_project_confirms_the_brief_in_one_step`.
2. `project_readiness` reports `brief-confirmed` as `pass` for such a project. ✅ unchanged `readiness.py:99` logic; `BRIEF_READY` is simply never the resting state for a fresh project.
3. Saving an edited brief on a project already past `BRIEF_READY` succeeds, changes the brief, and does not attempt a transition. ✅ verified by the same test's second half.
4. A blank central question is still rejected with the existing message. ✅ unchanged validation in `save_brief`; covered by `test_brief_validation_preserves_all_submitted_values`.
5. `GATE_BRIEF_CONFIRMED` is emitted exactly once per project. ✅ [`app.py:906-911`](../../src/thesisound/web/app.py:906).
6. A project rewound to `brief` genuinely re-enters `BRIEF_READY` and shows the blocking confirmation copy again, not the non-blocking one. ✅ verified by `test_rewind_to_brief_reblocks_with_the_confirmation_copy`.
7. `ALLOWED_TRANSITIONS` is unchanged. ✅ no edits to `pipeline.py`.

## 7. Test plan

| Test | Asserts |
|---|---|
| `test_create_project_confirms_the_brief_in_one_step` | §6.1, §6.3 — implemented, in [`tests/test_web_project_flow.py:278`](../../tests/test_web_project_flow.py:278) |
| `test_brief_validation_preserves_all_submitted_values` | §6.4 — implemented, in `tests/test_web_brief_validation.py` |
| `test_gate_codes_are_unique_and_kebab_case`, `test_every_enforced_at_reference_resolves`, `test_human_only_gates_match_the_documented_set`, `test_sop_document_lists_every_*` | §3.4's registry edits stay internally consistent and SOP-synced — implemented, in `tests/test_gates.py` |
| `test_rewind_to_brief_reblocks_with_the_confirmation_copy` | §6.6 — implemented, in [`tests/test_web_project_flow.py`](../../tests/test_web_project_flow.py). Creates a project (already past `BRIEF_READY`), POSTs `/workflow/rewind` with `target=brief`, then asserts the `/brief` page shows the blocking confirmation copy and `project.state == BRIEF_READY`. State/artifact side remains covered by `tests/test_workflow_revision.py`. |

## 8. Related

- [`06-conditional-document-map.md`](06-conditional-document-map.md) and [`07-conditional-glossary-and-verification.md`](07-conditional-glossary-and-verification.md) — the other two "simplify before MVP" items; both still proposed, not yet implemented.
- [`08-batched-claim-reconciliation.md`](08-batched-claim-reconciliation.md) — a later, unrelated addition to this same directory; no dependency either way.
- [`03-web-ui/01-operator-user-workflow.md`](../03-web-ui/01-operator-user-workflow.md) — the operator/end-user boundary this change moves.
- [`06-operations/03-production-sop.md`](../06-operations/03-production-sop.md) — the 12 gates and which are human-only; gate 1's `enforced_at` and `blocked_means` changed here, `actor` did not.
