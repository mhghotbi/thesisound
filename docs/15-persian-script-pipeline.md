# 15 — سناریوی فارسی Grounded و Verified

این subsystem از Episode Plan و Segment Evidence Pack یک سناریوی فارسی قابل شنیدن می‌سازد. هدف آن «تولید متن زیبا» به‌تنهایی نیست؛ هر turn محتوایی باید به claim و evidence معتبر متصل باشد و پیش از ورود به TTS از دو لایه کنترل عبور کند.

## جریان

```text
Episode Plan
+ Evidence Packs
+ Disagreement Graph
    ↓
Bilingual Glossary
    ↓
Persian Script per Segment
    ↓
Deterministic Checks
    ↓
Adversarial Verifier
    ↓
Targeted Revision, at most once
    ↓
Checks + Verification again
    ↓
script_verified
```

سناریو مستقیم به فارسی نوشته می‌شود. سیستم ابتدا یک سناریوی کامل انگلیسی تولید و سپس ترجمه نمی‌کند.

## ۱. Glossary

فایل‌ها:

```text
src/thesisound/services/glossary_builder.py
prompts/glossary/1.0.0/
```

واژه‌نامه فقط اصطلاح‌هایی را نگه می‌دارد که روی معنا، تمایز، attribution یا تلفظ اثر دارند.

هر term شامل:

- source term؛
- preferred Persian؛
- first-use form؛
- subsequent-use form؛
- pronunciation hint اختیاری؛
- translation status؛
- مواردی که نباید با آن‌ها اشتباه شود.

ترجمه‌های contested باید به‌صراحت `contested` باقی بمانند. مدل اجازه ندارد چند اصطلاح متمایز را صرفاً برای روانی به یک واژه فارسی فروبکاهد.

Artifact:

```text
script/glossary.json
```

## ۲. Persian Script Writer

فایل‌ها:

```text
src/thesisound/services/persian_script_writer.py
prompts/persian_script_segment/1.0.0/
```

هر segment در یک model run مستقل نوشته می‌شود. ورودی writer فقط این‌هاست:

- Research Brief؛
- همان Episode Segment؛
- Evidence Pack همان segment؛
- Glossary؛
- Disagreement Graph؛
- target word count.

Writer کل corpus را نمی‌بیند. این محدودیت accidental cross-segment leakage و استفاده از evidence نامرتبط را کم می‌کند.

دو نقش گفت‌وگو:

- Speaker A: توضیح‌دهنده دقیق؛
- Speaker B: مخاطب هوشمند که سؤال مفید، clarification و challenge واقعی مطرح می‌کند.

Speaker B نقش comic relief یا فرد ناآگاه مصنوعی ندارد.

### Grounding contract

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

Turn انتقالی می‌تواند `editorial_only=true` باشد، اما در این حالت claim ID و evidence ID ندارد.

مدل turn ID نمی‌سازد. application شناسه‌های پایدار زیر را materialize می‌کند:

```text
seg-001-turn-001
seg-001-turn-002
```

## ۳. Deterministic Checks

فایل:

```text
src/thesisound/services/script_checks.py
```

این مرحله مدل زبانی ندارد و موارد زیر را بررسی می‌کند:

- segment و Evidence Pack معتبر؛
- claim ID فقط از همان segment؛
- evidence ID فقط از همان pack؛
- وجود evidence مرتبط با claim هر turn؛
- prompt leakage؛
- تکرار کامل turn؛
- speaker pattern غیرطبیعی؛
- consistency واژه‌نامه؛
- مدت تخمینی بر اساس word count.

Verdict:

```text
pass
revise
reject
```

Blocking issue باعث `reject` می‌شود. مشکل مدت، تکرار یا terminology معمولاً `revise` است.

## ۴. Adversarial Verifier

فایل‌ها:

```text
src/thesisound/services/script_verifier.py
prompts/script_verifier/1.0.0/
```

Verifier مستقل از writer اجرا می‌شود و هر turn را در برابر claim، evidence، original block، qualification، glossary و disagreement graph بررسی می‌کند.

Issueهای اصلی:

- unsupported claim؛
- overstated certainty؛
- lost qualification؛
- wrong attribution؛
- collapsed disagreement؛
- invented example؛
- terminology error؛
- translation shift؛
- duration or pacing؛
- prompt leakage.

`pass` فقط وقتی معتبر است که:

```text
issues = []
unsupported_claim_ratio = 0
```

این مقدار به معنای «حقیقت مطلقاً اثبات‌شده» نیست؛ یعنی verifier و gateهای فعلی claim پشتیبانی‌نشده‌ای پیدا نکرده‌اند.

## ۵. Targeted Revision

فایل‌ها:

```text
src/thesisound/services/script_reviser.py
prompts/script_reviser/1.0.0/
```

Revision کل سناریو را بازنویسی نمی‌کند. فقط turnهایی که deterministic checks یا verifier علامت زده‌اند وارد prompt می‌شوند.

Reviser حق ندارد:

- speaker را تغییر دهد؛
- turn ID جدید بسازد؛
- claim ID یا evidence ID جدید اضافه کند؛
- turn سالم را تغییر دهد؛
- از knowledge بیرونی برای جبران evidence ناکافی استفاده کند.

یک دور revision خودکار مجاز است. اگر خروجی اصلاح‌شده دوباره از checks یا verification عبور نکند، pipeline متوقف می‌شود.

## ۶. State Machine

```text
episode_planned
  → script_drafting
  → glossary_ready
  → draft_ready
  → checks_ready
  → script_ready
  → script_verifying
  → verification_ready
  → revision_ready        optional
  → checks_ready          revised
  → script_verifying      revised
  → script_verified
```

Project فقط پس از pass نهایی به `script_verified` می‌رود.

## ۷. CLI

اجرای کامل:

```bash
uv run thesisound prepare-script <project-id>
```

اجرای مرحله‌ای:

```bash
uv run thesisound build-glossary <project-id>
uv run thesisound write-script <project-id>
uv run thesisound check-script <project-id>
uv run thesisound verify-script <project-id>
uv run thesisound revise-script <project-id>
uv run thesisound check-script <project-id> --revised
uv run thesisound verify-script <project-id> --revised
```

مدل هر stage جدا قابل override است:

```bash
uv run thesisound prepare-script <project-id> \
  --glossary-model <model-id> \
  --writer-model <model-id> \
  --verifier-model <model-id> \
  --reviser-model <model-id>
```

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

## ۹. Calibration

پس از pass نهایی:

```bash
uv run thesisound record-budget-calibration <project-id>
```

رکورد شامل این موارد است:

- target و planned duration؛
- word count و estimated script minutes؛
- evidence token count؛
- claim count؛
- deterministic verdict؛
- verifier verdict؛
- unsupported claim ratio.

فایل تجمیعی:

```text
workspaces/evaluations/budget-calibration.jsonl
```

حداقل سه نمونه pass‌شده برای `ready_for_review` لازم است. سیستم defaultهای budget را خودکار تغییر نمی‌دهد.

## ۱۰. تست زنده Gemini

تست‌های CI از fake structured model استفاده می‌کنند. Smoke test واقعی opt-in است:

```bash
THESISOUND_RUN_LIVE_MODEL_TESTS=true \
GEMINI_API_KEY=<key> \
uv run pytest -m live tests/test_live_gemini.py
```

تا زمانی که API key در محیط وجود ندارد، این تست skip می‌شود.

## Definition of Done

- هر segment یک draft مستقل دارد؛
- هر turn محتوایی claim ID و evidence ID معتبر دارد؛
- glossary consistency کنترل می‌شود؛
- deterministic checks اجرا می‌شوند؛
- verifier مستقل اجرا می‌شود؛
- فقط turnهای معیوب revise می‌شوند؛
- revision claim/evidence جدید وارد نمی‌کند؛
- پس از یک دور اصلاح، تمام gateها pass می‌شوند؛
- project به `script_verified` می‌رسد؛
- Ruff و pytest سبز هستند.
