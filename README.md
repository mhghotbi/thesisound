# Thesisound

[![CI](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml/badge.svg)](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml)

Thesisound یک ابزار کوچک و شخصی برای تبدیل موضوع یا مجموعه‌ای از منابع به پادکست فارسی منبع‌محور است.

> کاربر موضوع، سؤال، نام نویسنده یا کتاب را وارد می‌کند؛ منابع خودش را اضافه می‌کند؛ سیستم منابع معتبر مکمل را پیشنهاد می‌دهد؛ کاربر corpus نهایی را انتخاب می‌کند؛ سپس اپیزودی فارسی، قابل‌ممیزی و متناسب با مدت خروجی ساخته می‌شود.

هدف پروژه ساختن رقیب عمومی NotebookLM نیست. اولویت با یک vertical slice دقیق، قابل تست و قابل اجرا برای استفاده شخصی است.

## وضعیت فعلی

چهار subsystem اصلی اکنون قابل اجرا هستند.

### ۱. Document Ingestion

- inspection واقعی PDF و فایل؛
- SHA-256، MIME، اندازه، encryption و نمونه پوشش متن؛
- Docling adapter؛
- MinerU CLI adapter؛
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
- stage کامل Research Brief.

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
- تخمین حداکثر مدت قابل پشتیبانی بدون padding؛
- اولویت‌بندی deterministic claimها؛
- Episode Plan متناسب با duration؛
- enforce کردن must-include، omission و prerequisite؛
- بازیابی مستقیم EvidenceItem و original block برای هر segment؛
- Evidence Pack دارای token budget و context محدود؛
- transition پروژه تا `episode_planned`.

هنوز Source Discovery، cross-source reconciliation، Persian Script Writer، adversarial verification، TTS و Audio QA پیاده نشده‌اند.

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
  → Deterministic Claim Priorities
  → Episode Plan
  → Original-evidence retrieval
  → Segment Evidence Packs
  → Persian Script
  → Adversarial verification
  → TTS and Audio QA
```

خروجی نهایی از خلاصه‌های چندبار خلاصه‌شده ساخته نمی‌شود. خلاصه‌ها فقط نقش index و planning دارند؛ هر segment دوباره به evidence و block اصلی برمی‌گردد.

## مدت خروجی چگونه روی تحلیل اثر می‌گذارد؟

Parse، block ID و locator مستقل از مدت ساخته می‌شوند تا artifactها پایدار و reusable باشند. اما breadth و depth استخراج evidence به خروجی درخواستی وابسته است.

| مدت | tier | پوشش هدف tokenهای منبع | حداکثر claim در block | context همسایه |
|---|---|---:|---:|---:|
| ۵ تا ۱۰ دقیقه | `brief` | ۳۵٪ | ۲ | ۰ |
| ۱۱ تا ۲۵ دقیقه | `standard` | ۶۰٪ | ۳ | ۰ |
| ۲۶ تا ۴۵ دقیقه | `deep` | ۸۵٪ | ۵ | ۱ |
| ۴۶ تا ۱۲۰ دقیقه | `extended` | ۱۰۰٪ تا سقف budget | ۷ | ۲ |

Episode Preparation نیز output-aware است: نسخه کوتاه claimهای کمتری را must/supporting می‌کند؛ نسخه بلند باید claimها، اعتراض‌ها و qualificationهای واقعاً متفاوت اضافه کند، نه اینکه نسخه کوتاه را کش بدهد.

جزئیات:

- [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md)
- [`docs/14-episode-preparation.md`](docs/14-episode-preparation.md)

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

### ۱. ساخت پروژه

```bash
uv run thesisound init "آرنت و مفهوم کنش"
```

### ۲. ساخت Research Brief

```bash
uv run thesisound build-brief <project-id> \
  --audience "social-science graduate student" \
  --prior-knowledge intermediate \
  --duration 25 \
  --modes explanatory,critical \
  --language fa
```

`--duration` منبع حقیقت برای بودجه evidence و Episode Plan است.

### ۳. Parse منبع

```bash
uv run thesisound parse chapter.pdf \
  --parser auto \
  --output parse-result.json
```

اگر parse از quality gate عبور نکند، فرمان با exit code برابر ۲ متوقف می‌شود.

### ۴. تحلیل منبع

اجرای کامل:

```bash
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

`build-blocks` API key نمی‌خواهد. stageهای مدل‌محور بعدی Structured Output را فراخوانی می‌کنند.

### ۵. آماده‌سازی اپیزود

اجرای کامل:

```bash
uv run thesisound prepare-episode <project-id>
```

اجرای مرحله‌ای:

```bash
uv run thesisound audit-coverage <project-id>
uv run thesisound prioritize-claims <project-id>
uv run thesisound plan-episode <project-id>
uv run thesisound build-evidence-packs <project-id>
```

دو مرحله deterministic هستند و API call ندارند:

```text
prioritize-claims
build-evidence-packs
```

مدل‌ها را می‌توان جدا override کرد:

```bash
uv run thesisound prepare-episode <project-id> \
  --coverage-model <model-id> \
  --planning-model <model-id>
```

اگر Coverage Audit نشان دهد corpus برای duration درخواستی کافی نیست، planning متوقف و پروژه `failed_retryable` می‌شود.

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
    ingestion-result.json
    parsed-document.json
    block-build-report.json
    document-blocks.jsonl
    document-map.json
    evidence-extraction-plan.json
    evidence/
      extractions/<block-id>.json
    evidence-extractions.jsonl
    evidence-items.jsonl
    claim-ledger.json

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

به‌صورت پیش‌فرض rendered prompt ذخیره نمی‌شود. برای debugging محلی:

```text
THESISOUND_KEEP_RENDERED_PROMPTS=true
```

این تنظیم برای منابع خصوصی یا copyrighted مناسب نیست.

## Benchmark parserها

```bash
uv run thesisound compare-parsers path/to/file.pdf --output benchmark.json
uv run thesisound benchmark-parsers ./benchmark-corpus --recursive
```

## مدل‌های پیش‌فرض

```text
THESISOUND_MODEL_FAST=gemini-3.5-flash-lite
THESISOUND_MODEL_STRONG=gemini-3.6-flash
THESISOUND_MODEL_TTS=gemini-3.1-flash-tts-preview
```

نام مدل‌ها config است و در business logic hard-code نشده است.

## کنترل کیفیت کد

```bash
uv run ruff check .
uv run pytest
```

تست‌های عادی API خارجی را صدا نمی‌زنند و API key لازم ندارند.

## ترتیب مطالعه برای توسعه‌دهنده

1. [`docs/00-product-scope.md`](docs/00-product-scope.md)
2. [`docs/01-critical-review.md`](docs/01-critical-review.md)
3. [`docs/02-architecture.md`](docs/02-architecture.md)
4. [`docs/03-agent-workflow.md`](docs/03-agent-workflow.md)
5. [`docs/10-document-ingestion.md`](docs/10-document-ingestion.md)
6. [`docs/11-structured-model-execution.md`](docs/11-structured-model-execution.md)
7. [`docs/12-one-source-evidence-pipeline.md`](docs/12-one-source-evidence-pipeline.md)
8. [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md)
9. [`docs/14-episode-preparation.md`](docs/14-episode-preparation.md)
10. [`prompts/README.md`](prompts/README.md)
11. [`docs/06-development-plan.md`](docs/06-development-plan.md)
12. [`docs/07-junior-guide.md`](docs/07-junior-guide.md)

## قواعد غیرقابل‌مذاکره

- metadata یا abstract به‌تنهایی evidence متن کامل نیست.
- parse، block ID و locator به duration وابسته نیستند.
- breadth و depth evidence extraction به خروجی درخواستی وابسته‌اند.
- مدل source ID، block ID، locator، evidence ID، claim ID یا segment ID نمی‌سازد.
- supporting excerpt باید واقعاً در همان source block وجود داشته باشد.
- neighbor context حق تأمین evidence برای target block را ندارد.
- corpus ناکافی با padding به مدت هدف نمی‌رسد.
- must-include claim بدون دلیل حذف نمی‌شود.
- هر segment باید Evidence Pack مستقل و grounded داشته باشد.
- اختلاف تفسیرها نباید به اجماع جعلی تبدیل شود.
- سناریوی فارسی از Evidence Pack و outline معنایی ساخته می‌شود، نه ترجمه لفظ‌به‌لفظ یا knowledge آزاد مدل.
- مدل نویسنده تنها verifier خروجی خودش نیست.
- اگر parse، evidence، coverage، script یا audio از gate عبور نکند، pipeline متوقف می‌شود.
