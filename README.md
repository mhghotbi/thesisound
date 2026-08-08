# Thesisound

[![CI](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml/badge.svg)](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml)

Thesisound یک ابزار شخصی و کوچک برای تبدیل یک موضوع یا مجموعه‌ای از منابع به پادکست فارسیِ منبع‌محور است.

هدف پروژه ساختن «رقیب NotebookLM» یا یک پلتفرم عمومی پادکست نیست. مسئله مشخص‌تر است:

> کاربر یک موضوع، متن کوتاه، نام نویسنده یا کتاب را وارد می‌کند؛ منابع خودش را اضافه می‌کند؛ سیستم منابع معتبر مکمل را پیشنهاد می‌دهد؛ کاربر منابع نهایی را انتخاب می‌کند؛ سپس یک اپیزود فارسی با پوشش شفاف، ارجاع‌پذیر و قابل‌شنیدن ساخته می‌شود.

## وضعیت فعلی

دو subsystem اصلی اکنون قابل اجرا هستند.

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

هنوز source discovery، document mapping، evidence extraction، سناریو، verification و TTS پیاده نشده‌اند.

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
  -> Source discovery
  -> Human source selection
  -> Document structure + evidence records
  -> Coverage audit
  -> Episode plan
  -> Original-evidence retrieval
  -> Persian script generation
  -> Adversarial script verification
  -> TTS segmentation and synthesis
  -> Audio transcription and QA
  -> Private player/export
```

خروجی نهایی از خلاصه‌های چندبار خلاصه‌شده ساخته نمی‌شود. خلاصه‌ها فقط نقش index و planning دارند. هنگام نوشتن هر بخش، متن اصلی و locator دقیق دوباره بازیابی می‌شود.

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

## اجرای Research Brief

ابتدا پروژه را بسازید:

```bash
uv run thesisound init "آرنت و مفهوم کنش"
```

UUID خروجی را در فرمان بعدی استفاده کنید:

```bash
uv run thesisound build-brief <project-id> \
  --audience "social-science graduate student" \
  --prior-knowledge intermediate \
  --duration 25 \
  --modes explanatory,critical \
  --language fa
```

فرمان:

1. prompt contract نسخه‌دار را بارگذاری می‌کند؛
2. Gemini را با schema مدل `ResearchBrief` فراخوانی می‌کند؛
3. validation قطعی را اجرا می‌کند؛
4. در صورت schema failure فقط یک repair محدود انجام می‌دهد؛
5. model run و خروجی معتبر را ذخیره می‌کند؛
6. سپس project state را به `brief_ready` تغییر می‌دهد.

Artifactها در این مسیر قرار می‌گیرند:

```text
workspaces/<project-id>/
  project.json
  model-runs/<run-id>/
    request.json
    record.json
    validated-output.json
    error.json                 only on failure
    rendered-prompts.json      only when explicitly enabled
```

به‌صورت پیش‌فرض متن prompt ذخیره نمی‌شود. برای debugging محلی می‌توان موقتاً این تنظیم را فعال کرد:

```text
THESISOUND_KEEP_RENDERED_PROMPTS=true
```

این تنظیم برای اسناد خصوصی مناسب نیست.

## اجرای ingestion

بازرسی بدون parser:

```bash
uv run thesisound inspect path/to/file.pdf
```

انتخاب خودکار parser، fallback و quality gate:

```bash
uv run thesisound parse path/to/file.pdf --parser auto
```

مقایسه parserها:

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

مدل‌های فعلی Gemini پارامترهای `temperature`، `top_p` و `top_k` را deprecated کرده‌اند؛ Thesisound این پارامترها را ارسال نمی‌کند. کنترل خروجی از schema، prompt contract و deterministic validation انجام می‌شود.

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
7. [`prompts/README.md`](prompts/README.md)
8. [`docs/06-development-plan.md`](docs/06-development-plan.md)
9. [`docs/07-junior-guide.md`](docs/07-junior-guide.md)

## قواعد غیرقابل‌مذاکره

- metadata یا abstract به‌تنهایی evidence متن کامل محسوب نمی‌شود.
- هر ادعای محتوایی سناریو باید به evidence ID و locator متصل باشد.
- اختلاف تفسیرها نباید به اجماع جعلی تبدیل شود.
- کاربر منبع نهایی را انتخاب می‌کند؛ سیستم بدون اطلاع او corpus را تغییر نمی‌دهد.
- سناریوی فارسی از outline معنایی و شواهد اصلی ساخته می‌شود، نه از ترجمه لفظ‌به‌لفظ یک پادکست انگلیسی.
- مدل نویسنده تنها verifier خروجی خودش نیست.
- اگر کیفیت parse، evidence یا audio از gate عبور نکند، pipeline متوقف می‌شود.
