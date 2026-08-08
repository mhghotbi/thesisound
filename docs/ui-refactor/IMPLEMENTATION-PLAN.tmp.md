# Temporary implementation plan — Thesisound UI v2

Status: active on `agent/ui-refactor-v2`. This file must be deleted before merge.

## Source of truth

- `docs/ui-refactor/Thesisound UI v2.dc.html`
- `docs/ui-refactor/docs/29-ui-ux-audit.md`
- `docs/ui-refactor/docs/30-ui-redesign-spec.md`
- Current Jinja + HTMX implementation under `src/thesisound/web`

## Non-negotiable constraints

1. Redesign every existing web page and every meaningful state; do not limit work to a shared CSS pass.
2. Add the missing Project Overview page and integrate it into routing and project-list navigation.
3. Preserve the current backend/state machine and server-rendered Jinja + HTMX architecture.
4. Implement three isolated themes: `cobalt`, `wood`, `olive`; `cobalt` is the default when no valid preference exists.
5. Theme tokens must be semantic and complete. Components may not contain palette-specific values that leak between themes.
6. Implement simple and advanced/operator presentations across all relevant pages. Simple remains default; advanced exposes operational details without creating a second product flow.
7. Maintain RTL, Persian copy, Persian prose numerals, `<bdi dir="ltr">` for identifiers/URLs, accessible labels, keyboard focus, reduced-motion behavior, and responsive mobile layouts.
8. Replace duplicated workflow rails with one six-step StepRail.
9. Standardize status, attention, technical disclosure, error recovery, destructive impact confirmation, evidence tracing, and audio/transcript components.
10. Keep `docs/ui-refactor` as the retained design reference; delete only this temporary plan before merge.

## Delivery sequence

### A. Inventory and contracts
- Map every route/template/read model to the destination screen.
- Extract visual tokens, component anatomy, states, and responsive behavior from the artifact.
- Identify missing backend view-model fields and add presentation-safe defaults.

### B. Foundations
- Rebuild `base.html`, `app.css`, and `app.js` around semantic theme tokens.
- Add pre-paint theme initialization, theme switcher, simple/advanced mode persistence, global header, typography, layout, form, status, feedback, disclosure, table/list, and mobile primitives.
- Remove legacy workflow styling and duplicated rails.

### C. Shared components
- Implement reusable Jinja partials/macros for AppHeader, StepRail, StatusLabel, AttentionPanel, TechnicalDetails, ErrorRecoveryPanel, ImpactSummary, SourceRow, TranscriptTurn, EvidenceDrawer, and AudioPlayer.

### D. Pages
- Authentication: login and OTP verification.
- Projects: grouped list, empty state, new-project form, Project Overview.
- Workflow: brief, sources, processing, episode plan, script/evidence, audio/transcript.
- Operator-only system check.
- Design complete simple and advanced states for all pages, including loading, empty, blocked, warning, failure/retry, stale, and completed states supported by the current domain model.

### E. Integration
- Add/adjust routes and read models for overview, preferences, status labels, and safe technical details.
- Preserve form values and current HTMX behavior.
- Ensure project-list links land on Overview and primary actions derive from attention state.

### F. Verification
- Add/update tests for routes, templates, theme default/persistence, token parity, mode behavior, StepRail consistency, accessibility hooks, project overview, and no legacy workflow CSS.
- Run the full test suite through GitHub Actions.
- Review the complete diff and inspect CI failures.
- Perform a second pass against the artifact/spec, fix issues, rerun verification.

### G. Handoff
- Delete this temporary plan.
- Open/review the PR, verify the final branch diff and CI status.
- Merge into `main` only after checks pass and review findings are resolved.
- Delete `agent/ui-refactor-v2` after merge.
