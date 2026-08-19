# 05 — آماده‌سازی اپیزود و Evidence Pack

مرتبط: ورودی‌های این stage همان Claim Ledger از [`03-one-source-evidence-pipeline.md`](03-one-source-evidence-pipeline.md) و Evidence Extraction Plan از [`04-output-aware-analysis-budget.md`](04-output-aware-analysis-budget.md) هستند؛ خروجی آن ورودی [`06-persian-script-pipeline.md`](06-persian-script-pipeline.md) است.

این subsystem بین Claim Ledger و سناریونویسی فارسی قرار می‌گیرد. پیش از نوشتن متن گفتاری مشخص می‌کند corpus برای خروجی درخواستی کافی است یا نه، کدام claimها اولویت دارند، اختلاف sourceها کجاست، ترتیب آموزشی چیست و هر segment دقیقاً به چه evidence و متن اصلی دسترسی دارد.

> **بازنگری ۲۰۲۶-۰۸-۱۹ ([سند ۱۰](../01-foundations/10-personal-learning-companion-development-plan.md) §5.5، §6، §8 C4–C5، P2–P3):** as-built این سند برای `focused_question` می‌ماند. برنامه‌ریزی‌شده: (۱) **بخش‌بند قطعی** (`part_packer`) پیش از planner، سلول‌های مفهومی در دامنه را به `LessonPart`هایی ≤ طول اپیزود و نزدیک به آن می‌چیند؛ planner (`episode_plan/1.3.0`) به‌ازای هر بخش با claimهای همان بخش اجرا می‌شود؛ پنجرهٔ زمان برای این نیت بدون کف و با سقف ۱٫۲۵ × طول اپیزود است؛ (۲) هر claim با `must_not_be_lost` یا در segment است یا با دلیل در `deliberately_omitted_claims` (امروز `must_not_be_lost` اصلاً به planner داده نمی‌شود و `MustNotBeLostReview` در هیچ صفحه‌ای نیست)؛ (۳) گیت «۸۰٪ مدت» برای `source_coverage` مشورتی است و بررسی پوشش هر سلول جایش را می‌گیرد؛ خطوط برش اولویت (امروز `/3, /2, /4` — نه `/10, /6, /8` که در `07-specs/05` آمده بود) برای این نیت با «claim متصل به سلول‌های بخش → must_include» جایگزین می‌شود؛ (۴) **Evidence Pack حامل خودِ `ClaimRecord`ها** می‌شود (متن، `support_status`، قیدها) نه فقط `claim_ids`، تا نویسنده و verifier عدم‌قطعیت را ببینند؛ (۵) glossary از سلول‌های مفهومی seed می‌گیرد.

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
Deterministic Budget Report
    ↓
Explicit Disagreement Graph
    ↓
Output-aware Episode Plan
    ↓
Direct Evidence Mapping + SQLite FTS5 Retrieval
    ↓
Segment Evidence Packs
```

Episode Preparation سناریو تولید نمی‌کند. خروجی آن ورودی subsystem سناریوی فارسی است.

## ۱. Coverage Audit

فایل‌ها:

```text
src/thesisound/services/coverage_auditor.py
prompts/coverage_audit/1.0.0/
```

برای سؤال مرکزی و هر learning objective این موارد را ثبت می‌کند:

- وضعیت `well_covered`، `partially_covered` یا `not_covered`؛
- claim IDهای پشتیبان؛
- material gaps؛
- برآورد مدل از حداکثر مدت قابل پشتیبانی؛
- recommendation برابر `continue`، `narrow_scope` یا `more_evidence`.

مدل فقط claim ID موجود را می‌تواند استفاده کند و همه objectiveها باید دقیقاً یک‌بار برگردند.

## ۲. Claim Prioritization

فایل:

```text
src/thesisound/services/claim_prioritizer.py
```

این مرحله deterministic است. هر claim یکی از levelهای زیر را می‌گیرد:

```text
must_include
supporting
optional
deferred
```

Score از support status، claim type، ارتباط با سؤال مرکزی، objectiveها، evidence count، qualification، mode و duration ساخته می‌شود. reason و estimated explanation seconds نیز در artifact ثبت می‌شوند.

## ۳. Budget Report

فایل:

```text
src/thesisound/services/episode_budget.py
```

Coverage Audit تنها مرجع مدت نیست. Budget estimator مستقل، ظرفیت corpus را از این عوامل محدود می‌کند:

- مجموع زمان توضیح claimهای قابل استفاده؛
- expansion factor برای مثال، transition و dialogue؛
- مقدار original evidence token؛
- برآورد مدل.

`effective_supported_minutes` حداقل برآورد مدل و deterministic estimator است. فرض‌های عددی داخل `budget-report.json` ثبت می‌شوند و پنهان نیستند.

Defaultها خودکار از روی یک run تغییر نمی‌کنند. پس از script verification می‌توان calibration point ثبت کرد:

```bash
uv run thesisound record-budget-calibration <project-id>
```

پس از حداقل سه نمونه pass‌شده، گزارش به `ready_for_review` می‌رسد و medianهای واقعی قابل بررسی می‌شوند.

## ۴. Disagreement Graph

فایل:

```text
src/thesisound/services/disagreement_graph.py
```

Graph موضع sourceها را برای claimهای contested یا چندمنبعی صریح می‌کند:

```text
supports
 disputes
 qualifies
 unclear
```

نسخه فعلی فقط stanceهایی را materialize می‌کند که از evidence source، `agreeing_source_ids` یا `disagreeing_source_ids` قابل اثبات باشند. relationهای معنایی میان claimها حدس زده نمی‌شوند؛ این بخش در cross-source reconciliation تکمیل خواهد شد.

Artifact:

```text
disagreement-graph.json
```

## ۵. Episode Plan

فایل‌ها:

```text
src/thesisound/services/episode_planner.py
prompts/episode_plan/1.1.0/
```

نسخه `1.1.0` علاوه بر coverage و priorities، Budget Report و Disagreement Graph را دریافت می‌کند. نسخه `1.0.0` برای reproducibility بدون تغییر باقی مانده است.

هر segment شامل این موارد است:

- title و purpose؛
- estimated minutes؛
- claim IDs؛
- prerequisite claim IDs؛
- key question؛
- speaker dynamic.

Prerequisiteها هم در draft و هم در domain نهایی `EpisodeSegment` و `project.json` حفظ می‌شوند.

Quality gateها:

- مدت کل در محدوده ±۱۰٪؛
- claim ID ناشناخته ممنوع؛
- prerequisite باید قبلاً معرفی شده باشد؛
- claim در چند segment تکرار نمی‌شود؛
- تمام `must_include`ها استفاده می‌شوند؛
- supporting/optional یا استفاده می‌شوند یا دلیل omission دارند؛
- claim استفاده‌شده نمی‌تواند omitted باشد.

## ۶. Evidence Pack و Retrieval

فایل‌ها:

```text
src/thesisound/services/evidence_pack_builder.py
src/thesisound/services/sqlite_block_retriever.py
```

برای هر segment:

```text
claim IDs
  → ClaimRecord
  → evidence IDs
  → EvidenceItem
  → original source blocks
  → neighbor context
  → SQLite FTS5 context retrieval
  → token-bounded Evidence Pack
```

قواعد:

- original evidence برای رعایت budget حذف نمی‌شود؛
- context نمی‌تواند evidence جدید بسازد؛
- FTS فقط context مکمل می‌آورد؛
- retrieval hit شامل block ID، source ID، query و score است؛
- block و evidence تکراری deduplicate می‌شوند؛
- اگر original evidence از budget بیشتر باشد، context حذف و grounding حفظ می‌شود.

SQLite index در مسیر زیر ساخته می‌شود:

```text
episode/retrieval.sqlite3
```

## ۷. State Machine

```text
corpus_ready
  → episode_planning
  → coverage_ready
  → priorities_ready
  → budget_ready
  → disagreement_ready
  → plan_ready
  → evidence_packs_ready
  → episode_planned
```

State فقط بعد از ذخیره موفق artifact مربوط جلو می‌رود. Failure پروژه را به `failed_retryable` می‌برد و artifactهای موفق قبلی را حفظ می‌کند.

## CLI

```bash
uv run thesisound audit-coverage <project-id>
uv run thesisound prioritize-claims <project-id>
uv run thesisound estimate-episode-budget <project-id>
uv run thesisound build-disagreement-graph <project-id>
uv run thesisound plan-episode <project-id>
uv run thesisound build-evidence-packs <project-id>
```

اجرای کامل:

```bash
uv run thesisound prepare-episode <project-id>
```

## Artifactها

```text
workspaces/<project-id>/episode/
  manifest.json
  coverage-report.json
  claim-priorities.json
  budget-report.json
  disagreement-graph.json
  retrieval.sqlite3
  episode-plan-draft.json
  episode-plan.json
  evidence-packs.jsonl
  evidence-packs/<segment-id>.json
```

## تست‌ها

- vertical slice از `corpus_ready` تا `episode_planned`؛
- prerequisite persistence؛
- budget gate؛
- disagreement artifact؛
- FTS5 retrieval فارسی؛
- evidence و original block در هر pack؛
- claim selection متفاوت برای durationهای مختلف؛
- رد evidence مفقود؛
- Ruff و pytest.

## محدودیت تجربی باقی‌مانده

کد محدودیت‌های قبلی را رفع کرده، اما کیفیت عددهای budget و کیفیت واقعی مدل فقط با corpus و API key واقعی قابل سنجش است. برای این منظور:

- smoke test زنده Gemini opt-in است؛
- calibration recorder داده واقعی را جمع می‌کند؛
- defaultها تا رسیدن به حداقل نمونه و بازبینی انسانی خودکار تغییر نمی‌کنند.

این یک محدودیت داده است، نه یک مسیر کدنویسی ناتمام.
