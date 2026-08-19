# 06 — سناریوی فارسی Grounded و Verified

مرتبط: Episode Plan و Segment Evidence Pack ورودی از [`05-episode-preparation.md`](05-episode-preparation.md) می‌آیند؛ فراخوانی مدل روی قرارداد مشترک [`02-structured-model-execution.md`](02-structured-model-execution.md) اجرا می‌شود.

این subsystem از Episode Plan تأییدشده و Segment Evidence Pack یک سناریوی فارسی قابل شنیدن می‌سازد. هدف صرفاً تولید متن روان نیست؛ هر turn محتوایی باید به claim و evidence معتبر متصل باشد و پیش از ورود به TTS از کنترل قطعی و verifier مستقل عبور کند.

> **بازنگری ۲۰۲۶-۰۸-۱۹ ([سند ۱۰](../01-foundations/10-personal-learning-companion-development-plan.md) §7، §8 F1/F5/F11، C1/C5/C7، ضمیمهٔ A.1/A.5/A.11):**
> - **پیاده‌شده در P0.5:** نسخهٔ فعال نویسنده `persian_script_segment/1.3.0` است (لحن 1.2.0 + قرارداد grounding و dynamics؛ «عدد/تاریخ/نام/مکان/تشبیه خارج از pack ممنوع؛ تشبیه فقط در turn ویرایشی»). pack حامل `ClaimRecord`هاست. چک قطعی `unsupported_specifics` در `script_checks` فعال است. `script_verifier/1.2.0` و `script_reviser/1.1.0` لجر ادعا را می‌بینند.
> - **برنامه‌ریزی‌شده (P3/P4):** script و audio به‌ازای هر بخش (`script/parts/<n>/`, `audio/parts/<n>/`)؛ تحویل متنی با `persian_lesson_prose/1.0.0` روی همان plan/pack/verifier و گذار `SCRIPT_VERIFIED → COMPLETE` برای `delivery == text`.

## جریان

```text
Episode Plan
→ explicit approval of the exact plan hash
→ Bilingual Glossary
→ Persian Script per Segment
→ Deterministic Checks
→ Adversarial Verifier
→ Targeted Revision, at most once
→ Checks + Verification again
→ SCRIPT_VERIFIED
→ توقف پیش از تولید صدا
```

سناریو مستقیماً به فارسی نوشته می‌شود؛ سیستم ابتدا متن کامل انگلیسی تولید و سپس ترجمه نمی‌کند.

## ۱. Human gate و plan hash

شروع script generation بدون approval مجاز نیست. approval شامل موارد زیر است:

```text
project_id
plan_hash
approved_by
approved_at
```

Artifact:

```text
workspaces/<project-id>/episode/plan-approval.json
```

`plan_hash` از JSON canonical همان Episode Plan ساخته می‌شود. تغییر هر بخش طرح، approval قبلی را نامعتبر می‌کند. GET صفحه هیچ approval یا run ایجاد نمی‌کند؛ فقط POST صریح کاربر مجاز است.

CLI:

```bash
uv run thesisound approve-plan <project-id> --approved-by <actor>
uv run thesisound prepare-script <project-id>
```

`prepare-script` بدون approval معتبر fail می‌شود.

## ۲. Glossary

واژه‌نامه فقط اصطلاح‌هایی را نگه می‌دارد که روی معنا، تمایز، attribution یا تلفظ اثر دارند. ترجمه contested باید صریحاً contested باقی بماند.

ساخت واژه‌نامه **ابتدا قطعی است** (`deterministic_glossary`): از `ExtractedDefinition`ها، توکن‌های لاتین در excerptها و متن claimها فهرست اصطلاح می‌سازد و فقط وقتی تصمیم ترجمه‌ای باز مانده (فرم فارسی مطمئن نیست، تعارض بین منابع، یا کاندیدای لاتین بی‌ترجمه) مدل صدا زده می‌شود. نتیجه همیشه یک `Glossary` کامل است (`build_kind` برابر `deterministic` یا `model`) تا `glossary_inconsistency` خاموش نشود. جزئیات: [`07-specs/07-conditional-glossary-and-verification.md`](../07-specs/07-conditional-glossary-and-verification.md).

Artifact:

```text
script/glossary.json
```

## ۳. Persian Script Writer

هر segment یک model run مستقل دارد. writer فقط Research Brief، همان Episode Segment، Evidence Pack همان segment، Glossary و Disagreement Graph را می‌بیند.

هر turn محتوایی باید داشته باشد:

```text
turn_id
segment_id
speaker
spoken_text_fa
claim_ids
evidence_ids
editorial_only = false
```

Turn انتقالی می‌تواند `editorial_only=true` باشد و در این حالت claim/evidence ندارد.

Draft هر segment مستقل ذخیره می‌شود:

```text
script/segments/<segment-id>.json
```

در retry، segment draft موجود دوباره به مدل فرستاده نمی‌شود؛ application همان draft را با turn IDهای پایدار materialize می‌کند.

## ۴. Deterministic Checks

بدون مدل زبانی بررسی می‌شوند:

- segment و Evidence Pack معتبر؛
- claim فقط از همان segment؛
- evidence فقط از همان pack؛
- evidence مرتبط با claim هر turn؛
- prompt leakage؛
- تکرار؛
- speaker pattern؛
- consistency واژه‌نامه؛
- مدت بر اساس word count.

Claim ledger فقط از corpus تأییدشده `Project.sources` خوانده می‌شود. fallback به تمام claim-ready artifactها فقط برای project legacy بدون source registry وجود دارد.

Verdict:

```text
pass | revise | reject
```

## ۵. Adversarial Verifier

Verifier مستقل، turnها را در برابر claim، evidence، original block، qualification، glossary و disagreement graph بررسی می‌کند.

`pass` فقط وقتی معتبر است که:

```text
issues = []
unsupported_claim_ratio = 0
```

## ۶. Targeted Revision

فقط turnهای علامت‌خورده revise می‌شوند. Reviser اجازه ندارد speaker، turn ID، claim ID یا evidence ID جدید بسازد یا turn سالم را تغییر دهد.

فقط یک دور revision خودکار مجاز است. شکست دوباره، pipeline را متوقف و retryable می‌کند.

## ۷. Persisted run و resume

آخرین run:

```text
workspaces/<project-id>/script-build-run.json
```

تاریخچه:

```text
workspaces/<project-id>/runs/script/<run-id>.json
```

Stageها:

```text
queued
building_glossary
writing_segments
checking_draft
verifying_draft
revising
checking_revision
verifying_revision
complete
failed
```

هر retry run ID جدید با `previous_run_id` می‌سازد. Artifactهای سالم reuse می‌شوند. restart در state فعال به failure قابل retry تبدیل می‌شود؛ اگر project قبلاً `SCRIPT_VERIFIED` و artifactهای نهایی معتبر باشند، run pointer stale به success reconcile می‌شود.

## ۸. Artifactها

```text
workspaces/<project-id>/script/
  manifest.json
  glossary.json
  segments/<segment-id>.json
  script-draft.json
  checks.json
  verification.json
  script-revised.json           only when needed
  checks-revised.json           only when needed
  verification-revised.json     only when needed
```

## ۹. رابط وب

```text
/projects/<project-id>/episode
  → explicit plan approval
/projects/<project-id>/script
  → persisted progress
  → deterministic report
  → verifier report
  → script grouped by segment
  → source and locator trace per turn
```

UI درصد یا ETA ساختگی نشان نمی‌دهد. پایان این slice `SCRIPT_VERIFIED` است و audio generation هنوز آغاز نمی‌شود.

## ۱۰. تست زنده

تست‌های CI از fake structured model استفاده می‌کنند. Smoke test واقعی opt-in است:

```bash
THESISOUND_RUN_LIVE_MODEL_TESTS=true \
GEMINI_API_KEY=<key> \
uv run pytest -m live tests/test_live_gemini.py
```

## Definition of Done

- approval صریح و hash-bound لازم باشد؛
- GET side effect نداشته باشد؛
- transition به `SCRIPT_DRAFTING` پیش از model call persist شود؛
- هر segment draft مستقل و قابل resume باشد؛
- deterministic checks فقط corpus تأییدشده را مصرف کنند؛
- verifier مستقل اجرا شود؛
- حداکثر یک revision هدفمند انجام شود؛
- run history و restart recovery وجود داشته باشد؛
- UI trace منبع و locator هر turn را نمایش دهد؛
- project فقط بعد از pass نهایی به `SCRIPT_VERIFIED` برسد؛
- تولید صدا شروع نشود؛
- Ruff و pytest سبز باشند.
