# Thesisound

[![CI](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml/badge.svg)](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml)

Thesisound یک ابزار کوچک و شخصی برای تبدیل موضوع یا مجموعه‌ای از منابع به پادکست فارسی منبع‌محور است.

> کاربر موضوع، سؤال، نام نویسنده یا کتاب را وارد می‌کند؛ منابع خودش را اضافه می‌کند؛ سیستم منابع معتبر مکمل را پیشنهاد می‌دهد؛ کاربر corpus نهایی را انتخاب می‌کند؛ سپس اپیزودی فارسی، قابل‌ممیزی و متناسب با مدت خروجی ساخته می‌شود.

هدف پروژه ساختن رقیب عمومی NotebookLM نیست. اولویت با یک vertical slice دقیق، قابل تست و قابل اجرا برای استفاده شخصی است.

## وضعیت فعلی

پنج subsystem اصلی اکنون پیاده‌سازی شده‌اند.

### ۱. Document Ingestion

- inspection واقعی PDF و فایل؛
- SHA-256، MIME، اندازه، encryption و نمونه پوشش متن؛
- Docling adapter و MinerU CLI adapter؛
- parser routing و fallback خودکار؛
- quality gate قطعی؛
- artifact persistence؛
- benchmark یک سند یا corpus محلی.

### ۲. Structured Model Execution

- Gemini adapter با Pydantic Structured Output؛
- model port مستقل از provider؛
- prompt contract نسخه‌دار؛
- retry محدود برای timeout، rate limit و schema repair؛
- ثبت prompt version، hash، token usage، latency و finish reason؛
- عدم ذخیره rendered prompt به‌صورت پیش‌فرض؛
- smoke test زنده اختیاری برای Gemini.

### ۳. One-source Evidence Analysis

- semantic block building؛
- حفظ heading، locator، source block key و reading order؛
- Document Map؛
- `AnalysisProfile` وابسته به duration، سطح مخاطب و mode؛
- output-aware evidence extraction؛
- supporting excerpt عینی از متن اصلی؛
- evidence validation قطعی؛
- deterministic evidence ID و claim ID؛
- Claim Ledger؛
- ثبت blockهای selected و deferred؛
- transition پروژه تا `corpus_ready`.

### ۴. Episode Preparation

- Coverage Audit برای سؤال مرکزی و learning objectiveها؛
- deterministic budget report در کنار برآورد مدل؛
- اولویت‌بندی deterministic claimها؛
- disagreement graph صریح برای stanceهای sourceها؛
- Episode Plan متناسب با duration؛
- حفظ prerequisite claimها در domain نهایی؛
- بازیابی مستقیم EvidenceItem و original block؛
- retrieval مکمل با SQLite FTS5؛
- Evidence Pack دارای token budget، neighbor context و retrieval trace؛
- transition پروژه تا `episode_planned`.

### ۵. Verified Persian Script

- واژه‌نامه دوزبانه و pronunciation contract؛
- سناریونویسی مستقیم فارسی، segment-by-segment؛
- الزام claim ID و evidence ID برای هر turn محتوایی؛
- deterministic checks برای grounding، مدت، تکرار، glossary و prompt leakage؛
- adversarial verifier مستقل از writer؛
- targeted revision فقط برای turnهای مسئله‌دار؛
- حداکثر یک دور revision خودکار؛
- ثبت calibration point از word count، evidence tokens و verifier result؛
- transition پروژه تا `script_verified` فقط پس از عبور همه gateها.

هنوز Source Discovery، cross-source semantic reconciliation کامل، TTS، ASR و Audio QA پیاده نشده‌اند.

## معماری در یک نگاه

```text
User intent
  → Research Brief
  → Source ingestion
  → Semantic blocks and locators
  → Document Map
  → Output-aware AnalysisProfile
  → Evidence extraction and validation
  → Claim Ledger
  → Coverage Audit
  → Claim Priorities + Budget Report + Disagreement Graph
  → Episode Plan with prerequisites
  → Direct evidence mapping + SQLite FTS retrieval
  → Segment Evidence Packs
  → Bilingual Glossary
  → Persian segment scripts
  → Deterministic script checks
  → Adversarial verifier
  → Targeted revision
  → Verified Persian Script
  → TTS and Audio QA
```

خروجی نهایی از خلاصه‌های چندبار خلاصه‌شده ساخته نمی‌شود. هر segment دوباره به EvidenceItem، supporting excerpt و block اصلی برمی‌گردد.

## مدت خروجی چگونه روی تحلیل اثر می‌گذارد؟

Parse، block ID و locator مستقل از مدت ساخته می‌شوند تا artifactها پایدار و reusable باشند. اما breadth و depth استخراج evidence، تعداد claimهای انتخابی، تعداد segmentها و مقدار context به خروجی درخواستی وابسته‌اند.

| مدت | tier | پوشش هدف tokenهای منبع | حداکثر claim در block | context همسایه |
|---|---|---:|---:|---:|
| ۵ تا ۱۰ دقیقه | `brief` | ۳۵٪ | ۲ | ۰ |
| ۱۱ تا ۲۵ دقیقه | `standard` | ۶۰٪ | ۳ | ۰ |
| ۲۶ تا ۴۵ دقیقه | `deep` | ۸۵٪ | ۵ | ۱ |
| ۴۶ تا ۱۲۰ دقیقه | `extended` | ۱۰۰٪ تا سقف budget | ۷ | ۲ |

نسخه ۶۰ دقیقه‌ای صرفاً نسخه کش‌آمده نسخه ۵ دقیقه‌ای نیست. باید claimها، qualificationها، اعتراض‌ها و evidenceهای واقعاً بیشتری وارد pipeline شوند.

جزئیات:

- [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md)
- [`docs/14-episode-preparation.md`](docs/14-episode-preparation.md)
- [`docs/15-persian-script-pipeline.md`](docs/15-persian-script-pipeline.md)

## نصب

نصب پایه و ابزار توسعه:

```bash
uv sync --extra dev
```

برای Docling:

```bash
uv sync --extra dev --extra parsers
```

برای Gemini API:

```bash
uv sync --extra dev --extra gemini
cp .env.example .env
```

سپس `GEMINI_API_KEY` را در `.env` قرار دهید. MinerU یک runtime مستقل است و فرمان `mineru` باید روی `PATH` باشد.

## اجرای vertical slice فعلی

### ۱. ساخت پروژه و Research Brief

```bash
uv run thesisound init "آرنت و مفهوم کنش"

uv run thesisound build-brief <project-id> \
  --audience "social-science graduate student" \
  --prior-knowledge intermediate \
  --duration 25 \
  --modes explanatory,critical \
  --language fa
```

`--duration` منبع حقیقت برای evidence budget، Episode Plan و target script length است.

### ۲. Parse و تحلیل منبع

```bash
uv run thesisound parse chapter.pdf \
  --parser auto \
  --output parse-result.json

uv run thesisound analyze-source \
  <project-id> \
  parse-result.json
```

اجرای مرحله‌ای:

```bash
uv run thesisound build-blocks <project-id> parse-result.json
uv run thesisound map-document <project-id> <source-id>
uv run thesisound extract-evidence <project-id> <source-id>
uv run thesisound build-claims <project-id> <source-id>
```

### ۳. آماده‌سازی اپیزود

اجرای کامل:

```bash
uv run thesisound prepare-episode <project-id>
```

اجرای مرحله‌ای:

```bash
uv run thesisound audit-coverage <project-id>
uv run thesisound prioritize-claims <project-id>
uv run thesisound estimate-episode-budget <project-id>
uv run thesisound build-disagreement-graph <project-id>
uv run thesisound plan-episode <project-id>
uv run thesisound build-evidence-packs <project-id>
```

`prioritize-claims`، `estimate-episode-budget`، `build-disagreement-graph` و `build-evidence-packs` deterministic هستند.

### ۴. ساخت و راستی‌آزمایی سناریوی فارسی

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
uv run thesisound revise-script <project-id>       # فقط در صورت نیاز
uv run thesisound check-script <project-id> --revised
uv run thesisound verify-script <project-id> --revised
```

پس از یک اجرای verified، یک calibration point ثبت کن:

```bash
uv run thesisound record-budget-calibration <project-id>
```

پس از حداقل سه نمونه pass‌شده، گزارش calibration به وضعیت `ready_for_review` می‌رسد. defaultها خودکار تغییر نمی‌کنند؛ تغییر آن‌ها باید بر اساس corpus واقعی و بازبینی انسانی باشد.

## Artifactها

```text
workspaces/<project-id>/
  project.json
  model-runs/<run-id>/
    request.json
    record.json
    validated-output.json
    error.json

  sources/<source-id>/
    manifest.json
    parsed-document.json
    document-blocks.jsonl
    document-map.json
    evidence-extraction-plan.json
    evidence-items.jsonl
    claim-ledger.json

  episode/
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

  script/
    manifest.json
    glossary.json
    segments/<segment-id>.json
    script-draft.json
    checks.json
    verification.json
    script-revised.json
    checks-revised.json
    verification-revised.json

workspaces/evaluations/
  budget-calibration.jsonl
```

به‌صورت پیش‌فرض rendered prompt ذخیره نمی‌شود. برای debugging محلی:

```text
THESISOUND_KEEP_RENDERED_PROMPTS=true
```

این تنظیم برای منابع خصوصی یا copyrighted مناسب نیست.

## تست‌ها

تست‌های عادی هیچ API خارجی را صدا نمی‌زنند:

```bash
uv run ruff check .
uv run pytest
```

Smoke test واقعی Gemini فقط با opt-in اجرا می‌شود:

```bash
THESISOUND_RUN_LIVE_MODEL_TESTS=true \
GEMINI_API_KEY=<key> \
uv run pytest -m live tests/test_live_gemini.py
```

این تست تا زمانی که API key اضافه نشود، skip می‌شود.

## Benchmark parserها

```bash
uv run thesisound compare-parsers path/to/file.pdf --output benchmark.json
uv run thesisound benchmark-parsers ./benchmark-corpus --recursive
```

## ترتیب مطالعه برای توسعه‌دهنده

1. [`docs/00-product-scope.md`](docs/00-product-scope.md)
2. [`docs/02-architecture.md`](docs/02-architecture.md)
3. [`docs/03-agent-workflow.md`](docs/03-agent-workflow.md)
4. [`docs/10-document-ingestion.md`](docs/10-document-ingestion.md)
5. [`docs/11-structured-model-execution.md`](docs/11-structured-model-execution.md)
6. [`docs/12-one-source-evidence-pipeline.md`](docs/12-one-source-evidence-pipeline.md)
7. [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md)
8. [`docs/14-episode-preparation.md`](docs/14-episode-preparation.md)
9. [`docs/15-persian-script-pipeline.md`](docs/15-persian-script-pipeline.md)
10. [`prompts/README.md`](prompts/README.md)
11. [`docs/06-development-plan.md`](docs/06-development-plan.md)
12. [`docs/07-junior-guide.md`](docs/07-junior-guide.md)

## قواعد غیرقابل‌مذاکره

- metadata یا abstract به‌تنهایی evidence متن کامل نیست.
- parse، block ID و locator به duration وابسته نیستند.
- breadth و depth evidence extraction به خروجی درخواستی وابسته‌اند.
- مدل source ID، block ID، locator، evidence ID، claim ID، segment ID یا turn ID نمی‌سازد.
- supporting excerpt باید واقعاً در همان source block وجود داشته باشد.
- FTS context حق ایجاد evidence جدید ندارد.
- corpus ناکافی با padding به مدت هدف نمی‌رسد.
- prerequisiteها باید پیش از claim وابسته مطرح شوند و در artifact نهایی باقی بمانند.
- اختلاف sourceها نباید به اجماع جعلی تبدیل شود.
- هر turn محتوایی باید claim ID و evidence ID معتبر داشته باشد.
- سناریوی فارسی مستقیم از Evidence Pack نوشته می‌شود، نه از ترجمه لفظ‌به‌لفظ یا knowledge آزاد مدل.
- writer تنها verifier خروجی خودش نیست.
- targeted revision حق افزودن claim یا evidence جدید ندارد.
- اگر parse، evidence، coverage، script یا audio از gate عبور نکند، pipeline متوقف می‌شود.
