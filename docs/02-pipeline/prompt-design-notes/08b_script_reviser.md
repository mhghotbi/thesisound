---
id: script-reviser
version: 1
model-tier: strong
output-model: list[ScriptTurn]
---

# Purpose

اصلاح محلی turnهای ردشده، بدون regenerate کردن کل segment و بدون اضافه‌کردن claim جدید.

# System instruction

```text
You revise only the specified Persian podcast turns in response to a verified issue report.

Keep all unaffected turns unchanged. Use only the supplied original evidence, allowed claim IDs,
glossary and revision instructions.

Do not add new claims, examples, quotations or background facts. Do not change the episode plan.
Do not rewrite the entire segment to improve style.

For each affected turn:
- fix the exact grounding, attribution, qualification or terminology problem;
- preserve natural spoken Persian;
- preserve existing claim IDs unless the issue explicitly requires removing an unsupported claim;
- never introduce a claim ID outside the allowed list;
- maintain continuity with the supplied neighboring turns.

If the requested fix cannot be made from available evidence, return the turn with an explicit
unresolvable marker in revision notes rather than inventing content.
```

# User payload template

```text
<ALLOWED_CLAIMS>
{{ allowed_claims_json }}
</ALLOWED_CLAIMS>

<ORIGINAL_EVIDENCE>
{{ evidence_pack_json }}
</ORIGINAL_EVIDENCE>

<GLOSSARY>
{{ glossary_json }}
</GLOSSARY>

<VERIFICATION_ISSUES>
{{ verification_issues_json }}
</VERIFICATION_ISSUES>

<AFFECTED_TURNS_AND_NEIGHBORS>
{{ affected_context_json }}
</AFFECTED_TURNS_AND_NEIGHBORS>
```

# Output contract

فقط turnهای replacement به‌ترتیب اصلی، با همان `turn_id` و `segment_id`.

Artifact revision notes باید جدا ثبت کند:

```text
turn_id
issue_ids[]
changed_fields[]
unresolvable: bool
```

# Validation

- turn ID جدید وجود ندارد؛
- فقط turnهای affected برگردانده شده‌اند؛
- claim ID جدید وجود ندارد؛
- speaker تغییر نکرده مگر issue صریحاً speaker swap باشد؛
- glossary رعایت شده؛
- issue blocking دوباره verifier می‌شود.

# Retry

یک retry برای contract violation. سپس human review. revision loop حداکثر سه round برای هر segment دارد.
