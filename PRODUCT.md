# Thesisound Product Context

## Product

Thesisound turns user-selected sources into evidence-grounded Persian educational podcasts.

The product is not a generic AI audio generator. Its core promise is that the listener can understand where important claims came from and the system refuses to pad an episode when the selected corpus is insufficient.

## Primary audience

The first end-user audience is Persian-speaking humanities and social-science students. They may be comfortable with academic reading but should not need to understand parsers, model providers, claim IDs, run IDs, or artifact stores.

A separate Operator UI serves the owner, developer, and quality reviewer.

## Primary job

> Help me turn a topic and a set of credible sources into a clear Persian audio lesson I can trust, review, and continue later.

## Product modes

### Simple Mode

- plain Persian language;
- one primary action per screen;
- explicit human gates;
- source quality summarized without hiding blocking problems;
- guided recovery;
- source trace available on demand.

### Operator Mode

- project lifecycle, run attempts, warnings, artifacts, parsers, model usage, logs, and recovery;
- no alternate state machine;
- actions are supplied by the server from domain preconditions.

## Non-negotiable product rules

- The Research Brief must be explicitly confirmed.
- The corpus must be explicitly confirmed.
- A blocking source-quality failure cannot be silently accepted.
- Insufficient coverage blocks script generation.
- Progress is based on real stages or known units, not invented percentages.
- Editing upstream inputs marks affected downstream outputs stale.
- Every important claim remains traceable to evidence and source location.
- Test OTP is development-only and must be impossible to enable in production.

## Current implementation slice

The first UI slice covers:

1. phone OTP authentication;
2. project list;
3. project creation;
4. Research Brief confirmation;
5. source upload and source selection;
6. corpus confirmation;
7. processing handoff.

The development account is:

- phone: `0912000000`
- OTP: `999999`

This credential exists only when `THESISOUND_ALLOW_TEST_OTP=true` outside production.
