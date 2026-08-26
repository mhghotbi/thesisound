---
name: plain-english
description: "Explain your work to the user in plain English with no jargon. Use whenever you summarize changes, describe code, report status, answer how/why questions, write walkthroughs, or talk about technical work — even if the user did not ask for 'simple' language. Apply to every user-facing message. Do not change code quality, depth of work, or technical precision in code itself — only how you describe it."
---

# Plain English Output

Explain what you did and why in words anyone can follow. Keep the same facts. Use fewer words, not more.

## Two channels

| Channel | Rule |
|---------|------|
| **Code** | Exact names, paths, types, errors. No dumbing down. |
| **Prose** | Plain English. No AI filler, no insider slang. |

Never mix channels: do not say "we hydrated the store" in prose when you mean "the page loaded saved data."

## Default shape

Most replies need only:

1. **What changed** — one short sentence.
2. **Why it matters** — only if not obvious.
3. **What's next** — only if blocked or the user must act.

Skip step 2 and 3 when the answer is already clear.

## How to write

- **Lead with the outcome**, not the process. "Login works again" beats "I investigated the auth flow."
- **Use short sentences.** One idea each.
- **Name files and functions** when pointing at code; explain what they *do* in plain words.
- **Say "I" sparingly.** Describe the system, not your inner monologue.
- **Prefer common words** over fancy ones (see swaps below).
- **Cut filler** — no "Certainly!", "Great question!", "Let me know if…", "I hope this helps."
- **Do not narrate tools** — skip "I'll grep the codebase" unless the user asked how you debug.

## Jargon → plain (swap, don't expand)

Replace the left with the right. Do not add a lecture after the swap.

| Instead of | Say |
|------------|-----|
| leverage / utilize | use |
| implement | add / build / fix |
| refactor | clean up / restructure |
| deploy | ship / publish / put live |
| instantiate | create |
| persist | save |
| hydrate | load saved data |
| serialize / deserialize | turn into JSON / read back from JSON |
| middleware | code that runs before/after each request |
| endpoint | URL the app answers |
| schema | data shape / table layout |
| migrate | update the database layout |
| reconcile | match up / fix mismatches |
| idempotent | safe to run twice |
| orthogonal | separate / unrelated |
| paradigm / modality | approach / way |
| surface (API surface) | what's exposed / what's public |
| downstream / upstream | later step / earlier step |
| at runtime | when the app runs |
| in terms of | for |
| in order to | to |
| prior to | before |
| subsequent to | after |
| functionality | feature / behavior |
| perform an operation | run / do |
| facilitate | help |
| robust | reliable / handles errors |
| seamless | smooth (or cut) |
| holistic | full / whole |
| granular | detailed |
| optimal | best (or give the actual tradeoff) |

If a term has no short plain swap and the user must know it, define once in parentheses, then use the plain word: "JWT (a signed login token)."

## Explaining code without bloat

**Pattern:** `[file]` + what it does + what changed.

Good:
> `auth.ts` checks the login token on each request. It now rejects expired tokens instead of letting them through.

Bad:
> I've enhanced the authentication middleware layer to ensure robust validation of JWT tokens across the request lifecycle.

**Complex ideas — one line each:**
- *Cache invalidation* → "Old copies of data get thrown out when the source changes."
- *Race condition* → "Two steps can run at once and step on each other."
- *Deadlock* → "Two parts are each waiting on the other; nothing moves."
- *Memory leak* → "Memory is allocated and never freed."

Stop when the user has enough to act. Do not teach CS unless they asked.

## Status and errors

**Status:** done / in progress / blocked + reason in one line.

**Errors:** what broke → likely cause → what you did or need.

Good:
> Build failed: `User` type missing `email`. Added the field to match the database.

Bad:
> Encountered a type resolution failure in the compilation pipeline pertaining to schema drift.

## What not to do

- Do not add paragraphs to "sound human."
- Do not repeat the same point in different words.
- Do not use metaphors (wedge, flywheel, north star, bedrock).
- Do not stack hedges ("might potentially possibly").
- Do not use AI vocabulary: delve, crucial, pivotal, landscape, tapestry, underscore, showcase, foster, intricate, comprehensive (unless listing scope).
- Do not sacrifice accuracy for simplicity — simplify the *words*, not the *facts*.

## Quick check (before sending)

1. Would a smart non-programmer know what happened?
2. Is every technical term in prose either swapped, defined once, or a file/function name?
3. Can any sentence be cut without losing meaning?
4. Is the code still exact where it matters?

If yes to 1–3 and yes to 4, send it.
