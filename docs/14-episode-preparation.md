# 14 — آماده‌سازی اپیزود و Evidence Pack

این subsystem بین Claim Ledger و سناریونویسی فارسی قرار می‌گیرد. مسئولیت آن این است که پیش از نوشتن حتی یک جمله از سناریو، مشخص کند آیا corpus برای خروجی درخواستی کافی است، کدام claimها اهمیت بیشتری دارند، ترتیب آموزشی اپیزود چیست و برای هر segment دقیقاً کدام متن‌های اصلی باید در اختیار نویسنده قرار بگیرند.

## جریان کامل

```text
ResearchBrief
+ Claim Ledgers
+ Evidence Extraction Plans
    ↓
Coverage Audit
    ↓
Deterministic Claim Prioritization
    ↓
Output-aware Episode Plan
    ↓
Original-evidence Retrieval
    ↓
Segment Evidence Packs
```

مرحله بعد از این subsystem، Glossary و Persian Script Writer است. Episode Preparation خودش سناریو یا متن گفتاری تولید نمی‌کند.

---

## ۱. Coverage Audit

فایل‌ها:

```text
src/thesisound/services/coverage_auditor.py
prompts/coverage_audit/1.0.0/
```

ورودی:

- Research Brief؛
- تمام claimهای grounded؛
- Evidence Extraction Plan هر source؛
- blockهای deferred و coverage واقعی extraction.

خروجی:

```text
coverage-report.json
```

برای سؤال مرکزی و تک‌تک learning objectiveها این موارد ثبت می‌شود:

- `well_covered`؛
- `partially_covered`؛
- `not_covered`؛
- claim IDهای پشتیبان؛
- rationale؛
- material gaps؛
- حداکثر مدت غیرتکراری که corpus می‌تواند پشتیبانی کند؛
- recommendation.

Recommendation یکی از این سه مقدار است:

```text
continue
narrow_scope
more_evidence
```

### Quality gate

- مدل فقط claim ID موجود را می‌تواند استفاده کند؛
- تمام learning objectiveها باید دقیقاً یک‌بار و به ترتیب ورودی برگردند؛
- `well_covered` بدون claim ID پذیرفته نمی‌شود؛
- recommendation برابر `continue` با صفر دقیقه محتوای پشتیبانی‌شده رد می‌شود؛
- `can_plan_episode` فقط وقتی true است که recommendation ادامه باشد و corpus حداقل ۸۰٪ مدت هدف را پوشش دهد.

اگر کاربر ۶۰ دقیقه درخواست کرده ولی corpus فقط ۲۰ دقیقه محتوای grounded دارد، pipeline متوقف می‌شود. سیستم اجازه ندارد باقی زمان را با padding، تکرار یا دانش آزاد مدل پر کند.

---

## ۲. Claim Prioritization

فایل:

```text
src/thesisound/services/claim_prioritizer.py
```

این مرحله deterministic است. مدل زبانی در تعیین score یا level دخالت ندارد.

هر claim یکی از levelهای زیر را می‌گیرد:

```text
must_include
supporting
optional
deferred
```

Score بر اساس این عوامل ساخته می‌شود:

- support status؛
- نوع claim؛
- ارتباط مستقیم با سؤال مرکزی؛
- تعداد learning objectiveهای پشتیبانی‌شده؛
- تعداد evidenceهای معتبر؛
- qualificationها؛
- تناسب با critical/debate mode؛
- تناسب با مدت خروجی.

تعداد claimهای `must_include` و `supporting` به مدت خروجی وابسته است. بنابراین profile شصت‌دقیقه‌ای claimهای بیشتری از profile پنج‌دقیقه‌ای وارد plan می‌کند.

Artifact:

```text
claim-priorities.json
```

این artifact علاوه بر level و score، تخمین زمان توضیح و reasons را ثبت می‌کند تا تصمیم editorial قابل ممیزی باشد.

---

## ۳. Episode Plan

فایل‌ها:

```text
src/thesisound/services/episode_planner.py
prompts/episode_plan/1.0.0/
```

Episode Plan یک semantic execution plan است، نه خلاصه و نه سناریو.

هر segment شامل این موارد است:

- title؛
- purpose؛
- target minutes؛
- claim IDs؛
- prerequisite claim IDs؛
- key question؛
- speaker dynamic.

مدل segment ID تولید نمی‌کند. application به‌شکل deterministic شناسه‌های زیر را می‌سازد:

```text
seg-001
seg-002
...
```

### Quality gate

- مجموع زمان segmentها باید در محدوده ±۱۰٪ duration هدف باشد؛
- تمام claim IDها باید موجود باشند؛
- claim در چند segment تکرار نمی‌شود؛
- prerequisite باید در segment قبلی معرفی شده باشد؛
- تمام `must_include`ها باید استفاده شوند؛
- claimهای `supporting` و `optional` یا استفاده می‌شوند یا با reason در deliberate omission ثبت می‌شوند؛
- claim نمی‌تواند هم استفاده‌شده و هم omitted باشد؛
- sourceهای contested نباید به consensus تبدیل شوند.

خروجی‌ها:

```text
episode-plan-draft.json
episode-plan.json
```

Draft شامل prerequisiteها و قرارداد کامل planner است. نسخه materialized با domain فعلی پروژه سازگار است و روی `project.json` نیز ثبت می‌شود.

---

## ۴. Evidence Pack Builder

فایل:

```text
src/thesisound/services/evidence_pack_builder.py
```

این مرحله کاملاً deterministic است و هیچ مدل زبانی را صدا نمی‌زند.

برای هر segment:

```text
claim IDs
  → ClaimRecord
  → evidence IDs
  → EvidenceItem
  → original source blocks
  → allowed neighbor context
  → token-bounded Evidence Pack
```

Evidence Pack شامل:

- claim IDها؛
- EvidenceItemها؛
- original blockهایی که واقعاً evidence را تأمین می‌کنند؛
- context blockهای اختیاری؛
- token budget؛
- actual tokens؛
- warnings.

### قواعد grounding

- هر claim باید evidence موجود داشته باشد؛
- هر evidence باید block اصلی موجود داشته باشد؛
- original block هیچ‌وقت برای رعایت budget حذف نمی‌شود؛
- اگر original evidence از budget بیشتر باشد، grounding حفظ و context حذف می‌شود؛
- context فقط بر اساس `neighbor_context_blocks` در AnalysisProfile اضافه می‌شود؛
- context نمی‌تواند evidence ID جدید ایجاد کند؛
- blockها و evidenceهای تکراری deduplicate می‌شوند.

بودجه اولیه هر segment:

```text
max(1,800, min(18,000, segment_minutes * 1,400))
```

این عدد یک default مهندسی است و باید بعد از benchmark کیفیت سناریو تنظیم شود.

خروجی:

```text
evidence-packs.jsonl
evidence-packs/seg-001.json
evidence-packs/seg-002.json
```

Script Writer آینده فقط Evidence Pack همان segment را دریافت می‌کند، نه کل corpus و نه صرفاً Claim Ledger را.

---

## ۵. Orchestration و State Machine

فایل:

```text
src/thesisound/services/episode_preparation_service.py
```

شروع معتبر:

```text
corpus_ready
```

مسیر:

```text
corpus_ready
  → episode_planning
  → coverage_ready
  → priorities_ready
  → plan_ready
  → evidence_packs_ready
  → episode_planned
```

State فقط پس از ذخیره plan و تمام Evidence Packها به `episode_planned` تغییر می‌کند.

در failure:

- پروژه به `failed_retryable` می‌رود؛
- خطا در project و episode manifest ثبت می‌شود؛
- artifactهای موفق قبلی باقی می‌مانند؛
- اجرای مجدد از `failed_retryable` یا `episode_planned` مجاز است.

Artifact manifest:

```text
workspaces/<project-id>/episode/manifest.json
```

---

## ۶. CLI

اجرای مرحله‌ای:

```bash
uv run thesisound audit-coverage <project-id>
uv run thesisound prioritize-claims <project-id>
uv run thesisound plan-episode <project-id>
uv run thesisound build-evidence-packs <project-id>
```

اجرای کامل:

```bash
uv run thesisound prepare-episode <project-id>
```

مدل coverage و planner را می‌توان جدا override کرد:

```bash
uv run thesisound prepare-episode <project-id> \
  --coverage-model <model-id> \
  --planning-model <model-id>
```

`prioritize-claims` و `build-evidence-packs` API call ندارند.

---

## ساختار Artifact

```text
workspaces/<project-id>/
  project.json
  episode/
    manifest.json
    coverage-report.json
    claim-priorities.json
    episode-plan-draft.json
    episode-plan.json
    evidence-packs.jsonl
    evidence-packs/
      seg-001.json
      seg-002.json
```

مدل runهای Coverage Audit و Episode Plan همچنان در مسیر عمومی زیر ثبت می‌شوند:

```text
model-runs/<run-id>/
```

---

## تست‌ها

فایل:

```text
tests/test_episode_preparation.py
```

تست‌های عادی بدون API خارجی اجرا می‌شوند و این موارد را پوشش می‌دهند:

- vertical slice کامل از `corpus_ready` تا `episode_planned`؛
- ذخیره تمام artifactها؛
- وجود evidence و original block در هر pack؛
- انتخاب claimهای بیشتر برای duration بلندتر؛
- رد claim دارای evidence مفقود؛
- state transition نهایی.

## محدودیت‌های فعلی

1. Coverage Audit و Episode Plan با fake structured model در CI تست می‌شوند؛ کیفیت واقعی Gemini نیازمند live run است.
2. prerequisiteها در draft artifact حفظ می‌شوند، اما domain `EpisodeSegment` فعلی آن‌ها را در project manifest نگه نمی‌دارد؛ پیش از Script Writer باید این field به domain نهایی منتقل شود.
3. Retrieval فعلی مبتنی بر mapping مستقیم claim/evidence/block است. SQLite FTS برای بازیابی context مکمل هنوز اضافه نشده است.
4. Evidence Pack از claimهای موجود استفاده می‌کند؛ cross-source disagreement graph هنوز در milestone چندمنبعی ساخته نشده است.
5. benchmark واقعی token budget و max-supported-minutes هنوز لازم است.

## Definition of Done این milestone

- corpus ناکافی اجازه planning نمی‌گیرد؛
- duration اپیزود معتبر است؛
- must-includeها حذف نمی‌شوند؛
- omissionها قابل ممیزی‌اند؛
- هر segment دقیقاً یک Evidence Pack دارد؛
- هر claim در pack به evidence و original block برمی‌گردد؛
- project فقط پس از ذخیره تمام packها `episode_planned` می‌شود؛
- Ruff و pytest سبز هستند.
