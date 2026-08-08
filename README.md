# Thesisound

[![CI](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml/badge.svg)](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml)

Thesisound یک ابزار شخصی و کوچک برای تبدیل یک موضوع یا مجموعه‌ای از منابع به پادکست فارسیِ منبع‌محور است.

هدف پروژه ساختن «رقیب NotebookLM» یا یک پلتفرم عمومی پادکست نیست. مسئله مشخص‌تر است:

> کاربر یک موضوع، متن کوتاه، نام نویسنده یا کتاب را وارد می‌کند؛ منابع خودش را اضافه می‌کند؛ سیستم منابع معتبر مکمل را پیشنهاد می‌دهد؛ کاربر منابع نهایی را انتخاب می‌کند؛ سپس یک اپیزود فارسی با پوشش شفاف، ارجاع‌پذیر و قابل‌شنیدن ساخته می‌شود.

## وضعیت فعلی

سه subsystem اصلی اکنون قابل اجرا هستند.

### Document ingestion

- inspection واقعی فایل و PDF؛
- SHA-256، MIME، اندازه، encryption و نمونه پوشش متن؛
- Docling adapter؛
- MinerU CLI adapter؛
- normalization چندنسخه‌ای خروجی MinerU؛
- parser routing و fallback خودکار؛
- quality gate قطعی؛
- artifact persistence؛
- benchmark یک سند یا یک corpus محلی.

### Structured model execution

- Gemini adapter با Pydantic structured output؛
- model port مستقل از provider؛
- prompt contract نسخه‌دار؛
- retry محدود برای timeout، rate limit و schema repair؛
- عدم retry خودکار برای safety rejection؛
- ثبت prompt version، hash، token usage، latency و finish reason؛
- عدم ذخیره rendered prompt به‌صورت پیش‌فرض؛
- stage کامل `ResearchBrief` و transition پروژه به `brief_ready`.

### One-source evidence analysis

- semantic block building؛
- حذف محافظه‌کارانه header و footer؛
- حفظ heading، locator، source block key و reading order؛
- Document Map با حداقل ۹۰ درصد block coverage؛
- `AnalysisProfile` وابسته به مدت، سطح مخاطب و mode؛
- انتخاب output-aware برای breadth و depth استخراج؛
- evidence extraction مستقل برای blockهای منتخب؛
- supporting excerpt عینی از متن اصلی؛
- evidence validation قطعی؛
- deterministic evidence ID و claim ID؛
- Claim Ledger و ثبت evidenceهای unresolved؛
- ثبت blockهای deferred برای خروجی‌های کوتاه‌تر؛
- artifactهای block-level برای debugging؛
- CLI مرحله‌ای و فرمان end-to-end `analyze-source`؛
- transition پروژه تا `corpus_ready`.

هنوز source discovery، multi-source reconciliation، retrieval، episode planning، سناریو، verification و TTS پیاده نشده‌اند.

## محدوده MVP

MVP فقط این مسیر را پوشش می‌دهد:

1. دریافت عنوان، سؤال یا متن کوتاه از کاربر
2. دریافت PDF، EPUB یا URLهای اختیاری
3. استخراج ساختار و متن منابع
4. جست‌وجوی منابع مکمل معتبر
5. نمایش منبع‌ها و انتخاب نهایی توسط کاربر
6. ساخت نقشه موضوع، شواهد و پوشش مطالب
7. طراحی یک اپیزود ۲۰ تا ۴۰ دقیقه‌ای
8. نوشتن مستقیم سناریوی فارسی از شواهد اصلی
9. راستی‌آزمایی سناریو
10. تولید صوت فارسی و کنترل کیفیت آن

موارد زیر فعلاً خارج از محدوده‌اند:

- اپ موبایل
- شبکه اجتماعی یا انتشار عمومی
- پرداخت و اشتراک
- recommendation engine پیچیده
- crawler اختصاصی
- fine-tuning مدل
- معماری چندسرویسه و زیرساخت production

## معماری در یک نگاه

```text
User intent
  -> Research brief
  -> User-source ingestion
  -> Semantic document blocks
  -> Document map
  -> Output-aware analysis profile and extraction plan
  -> Block-scoped evidence extraction
  -> Deterministic evidence validation
  -> Claim ledger
  -> Source discovery
  -> Human source selection
  -> Multi-source synthesis and coverage audit
  -> Episode plan
  -> Original-evidence retrieval
  -> Persian script generation
  -> Adversarial script verification
  -> TTS segmentation and synthesis
  -> Audio transcription and QA
  -> Private player/export
```

خروجی نهایی از خلاصه‌های چندبار خلاصه‌شده ساخته نمی‌شود. خلاصه‌ها فقط نقش index و planning دارند. هنگام نوشتن هر بخش، متن اصلی و locator دقیق دوباره بازیابی می‌شود.

## اصل مدت و عمق تحلیل

Parse، block‌بندی و locator مستقل از مدت خروجی ساخته می‌شوند تا پایدار و قابل استفاده مجدد باشند. اما evidence extraction همیشه کامل اجرا نمی‌شود.

پس از Document Map، سیستم از `target_duration_minutes`، `prior_knowledge` و modeهای Research Brief یک `AnalysisProfile` می‌سازد. این profile تعیین می‌کند:

- چه مقدار از tokenهای منبع تحلیل شود؛
- از هر block حداکثر چند claim استخراج شود؛
- چند block همسایه برای context استفاده شود؛
- example، objection و response در budget قرار بگیرند یا نه.

defaultهای فعلی:

| مدت | tier | هدف پوشش token | claim در block | context همسایه |
|---|---|---:|---:|---:|
| ۵ تا ۱۰ دقیقه | `brief` | ۳۵٪ | ۲ | ۰ |
| ۱۱ تا ۲۵ دقیقه | `standard` | ۶۰٪ | ۳ | ۰ |
| ۲۶ تا ۴۵ دقیقه | `deep` | ۸۵٪ | ۵ | ۱ |
| ۴۶ تا ۱۲۰ دقیقه | `extended` | ۱۰۰٪ تا سقف budget | ۷ | ۲ |

بنابراین پادکست ۶۰ دقیقه‌ای صرفاً نسخه کش‌آمده پادکست ۵ دقیقه‌ای نیست. substrate مشترک است، ولی breadth و depth شواهد متفاوت است. طراحی کامل در [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md) آمده است.

## نصب

نصب پایه و ابزارهای توسعه:

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

سپس `GEMINI_API_KEY` را در `.env` قرار دهید.

MinerU یک runtime مستقل است و باید جداگانه نصب شود؛ فرمان `mineru` باید روی `PATH` قرار داشته باشد.

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

`--duration` فقط مدت سناریو را تعیین نمی‌کند؛ ورودی اصلی بودجه تحلیل evidence نیز هست. تنظیم جداگانه‌ای در `analyze-source` وجود ندارد تا دو مقدار متناقض ایجاد نشود.

### ۳. Parse منبع

```bash
uv run thesisound parse chapter.pdf \
  --parser auto \
  --output parse-result.json
```

اگر parse از quality gate عبور نکند، فرمان با exit code برابر ۲ متوقف می‌شود و نباید source analysis اجرا شود.

### ۴. تحلیل یک منبع

اجرای کل pipeline:

```bash
uv run thesisound analyze-source \
  <project-id> \
  parse-result.json
```

یا اجرای مرحله‌ای:

```bash
uv run thesisound build-blocks <project-id> parse-result.json
uv run thesisound map-document <project-id> <source-id>
uv run thesisound extract-evidence <project-id> <source-id>
uv run thesisound build-claims <project-id> <source-id>
```

`build-blocks` به API key نیاز ندارد. سه فرمان بعدی structured model را فراخوانی می‌کنند. `extract-evidence` profile را خودکار از Research Brief پروژه می‌سازد.

## Artifactها

```text
workspaces/<project-id>/
  project.json
  model-runs/<run-id>/
    request.json
    record.json
    validated-output.json
    error.json                 only on failure
    rendered-prompts.json      only when explicitly enabled
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
```

`evidence-extraction-plan.json` شامل profile، token budget، blockهای منتخب، blockهای deferred و coverage واقعی است.

به‌صورت پیش‌فرض متن prompt ذخیره نمی‌شود. برای debugging محلی می‌توان موقتاً این تنظیم را فعال کرد:

```text
THESISOUND_KEEP_RENDERED_PROMPTS=true
```

این تنظیم برای اسناد خصوصی مناسب نیست.

## Benchmark parserها

```bash
uv run thesisound compare-parsers path/to/file.pdf --output benchmark.json
uv run thesisound benchmark-parsers ./benchmark-corpus --recursive
```

## مدل‌های پیش‌فرض

مدل‌ها از environment خوانده می‌شوند:

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

تست‌های عادی هیچ API خارجی را صدا نمی‌زنند و به API key نیاز ندارند.

## ترتیب مطالعه برای توسعه‌دهنده

1. [`docs/00-product-scope.md`](docs/00-product-scope.md)
2. [`docs/01-critical-review.md`](docs/01-critical-review.md)
3. [`docs/02-architecture.md`](docs/02-architecture.md)
4. [`docs/03-agent-workflow.md`](docs/03-agent-workflow.md)
5. [`docs/10-document-ingestion.md`](docs/10-document-ingestion.md)
6. [`docs/11-structured-model-execution.md`](docs/11-structured-model-execution.md)
7. [`docs/12-one-source-evidence-pipeline.md`](docs/12-one-source-evidence-pipeline.md)
8. [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md)
9. [`prompts/README.md`](prompts/README.md)
10. [`docs/06-development-plan.md`](docs/06-development-plan.md)
11. [`docs/07-junior-guide.md`](docs/07-junior-guide.md)

## قواعد غیرقابل‌مذاکره

- metadata یا abstract به‌تنهایی evidence متن کامل محسوب نمی‌شود.
- parse، block ID و locator نباید به مدت خروجی وابسته باشند.
- breadth و depth evidence extraction باید به خروجی درخواستی وابسته باشند.
- مدل source ID، block ID، locator، evidence ID یا claim ID نمی‌سازد.
- supporting excerpt باید واقعاً در همان source block وجود داشته باشد.
- neighbor context حق تأمین evidence برای target block را ندارد.
- هر evidence باید در یک claim مصرف شود یا صریحاً unresolved ثبت شود.
- هر ادعای محتوایی سناریو باید به evidence ID و locator متصل باشد.
- اختلاف تفسیرها نباید به اجماع جعلی تبدیل شود.
- کاربر منبع نهایی را انتخاب می‌کند؛ سیستم بدون اطلاع او corpus را تغییر نمی‌دهد.
- سناریوی فارسی از outline معنایی و شواهد اصلی ساخته می‌شود، نه از ترجمه لفظ‌به‌لفظ یک پادکست انگلیسی.
- مدل نویسنده تنها verifier خروجی خودش نیست.
- اگر کیفیت parse، evidence یا audio از gate عبور نکند، pipeline متوقف می‌شود.
