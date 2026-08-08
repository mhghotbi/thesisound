# Thesisound

[![CI](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml/badge.svg)](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml)

Thesisound یک ابزار شخصی و کوچک برای تبدیل یک موضوع یا مجموعه‌ای از منابع به پادکست فارسیِ منبع‌محور است.

هدف پروژه ساختن «رقیب NotebookLM» یا یک پلتفرم عمومی پادکست نیست. مسئله مشخص‌تر است:

> کاربر یک موضوع، متن کوتاه، نام نویسنده یا کتاب را وارد می‌کند؛ منابع خودش را اضافه می‌کند؛ سیستم منابع معتبر مکمل را پیشنهاد می‌دهد؛ کاربر منابع نهایی را انتخاب می‌کند؛ سپس یک اپیزود فارسی با پوشش شفاف، ارجاع‌پذیر و قابل‌شنیدن ساخته می‌شود.

## وضعیت فعلی

ریپو در مرحله vertical-slice است. Milestone صفر کامل شده و مسیر اولیه document ingestion اکنون قابل اجراست:

- inspection مستقل از parser؛
- تشخیص hash، MIME، اندازه، encryption و نمونه پوشش متن PDF؛
- adapter اختیاری Docling؛
- normalization به blockهای داخلی با heading path و page provenance؛
- quality gate قطعی برای متن گم‌شده، تکرار، OCR خراب، locator و پوشش صفحات؛
- فرمان‌های CLI برای `inspect` و `parse`؛
- تست‌های مستقل از نصب سنگین Docling.

هنوز MinerU adapter، corpus benchmark واقعی، Gemini، source discovery، سناریو و TTS پیاده نشده‌اند.

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
- ساخت خودکار چند فصل یا چند اپیزود بلند
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

اصل مهم این معماری این است که خروجی نهایی از خلاصه‌های خلاصه‌شده ساخته نمی‌شود. خلاصه‌ها فقط نقش index و planning دارند. هنگام نوشتن هر بخش، متن اصلی و locator دقیق دوباره بازیابی می‌شود.

## چرا CLI-first؟

این پروژه برای یک مصرف شخصی ساخته می‌شود و بزرگ‌ترین ریسک آن کیفیت محتوا و صوت فارسی است، نه مقیاس. بنابراین ترتیب توسعه این است:

1. یک فصل واقعی را از فایل تا صوت پردازش کن.
2. کیفیت را در برابر NotebookLM و متن اصلی بسنج.
3. فقط بعد از اثبات کیفیت، source discovery و UI را اضافه کن.
4. queue، PostgreSQL و vector search فقط وقتی اضافه شوند که محدودیت واقعی ایجاد شود.

## Stack پیشنهادی MVP

- Python 3.12+
- `uv` برای dependency management
- Pydantic برای قراردادهای داده
- Typer برای CLI
- SQLite + JSON artifacts برای وضعیت محلی
- SQLite FTS5 برای retrieval اولیه
- Docling به‌عنوان parser محلی پیش‌فرض
- MinerU به‌عنوان fallback برای PDF اسکن‌شده یا layout دشوار
- Firecrawl برای web search/scrape و hosted parse اختیاری
- OpenAlex برای metadata و جست‌وجوی دانشگاهی
- Gemini text models برای planning، extraction، writing و verification
- Gemini 3.1 Flash TTS Preview برای صوت فارسی
- FFmpeg برای مونتاژ صوت

مدل‌ها از environment تنظیم می‌شوند و نباید در منطق دامنه hard-code شوند. مدل‌های preview و aliasهای API تغییر می‌کنند.

## ساختار ریپو

```text
.
├── docs/                   تصمیم‌ها، معماری، workflow و برنامه توسعه
├── prompts/                قراردادهای prompt مرحله‌به‌مرحله
├── src/thesisound/
│   ├── adapters/parsers/   adapterهای parser با import اختیاری
│   └── services/           inspection، normalization و quality gates
├── tests/                  unit tests و fixtureهای قانونی
├── .env.example            تنظیمات providerها و مدل‌ها
└── pyproject.toml          پکیج و ابزارهای توسعه
```

## نصب و اجرای ingestion

نصب پایه و ابزارهای توسعه:

```bash
uv sync --extra dev
```

نصب parserها برای اجرای واقعی Docling و بررسی PDF با pypdf:

```bash
uv sync --extra dev --extra parsers
```

بازرسی بدون اجرای parser:

```bash
uv run thesisound inspect path/to/file.pdf
```

Parse، normalization و quality gate:

```bash
uv run thesisound parse path/to/file.pdf --parser docling --output parse-result.json
```

اگر parse برای claim extraction امن نباشد، فرمان `parse` پس از نوشتن report با exit code برابر ۲ متوقف می‌شود.

فرمان‌های scaffold پروژه:

```bash
uv run thesisound init "آرنت و مفهوم کنش"
uv run thesisound status <project-id>
uv run thesisound dump <project-id>
```

کنترل کیفیت کد:

```bash
uv run pytest
uv run ruff check .
```

## ترتیب مطالعه برای توسعه‌دهنده

1. [`docs/00-product-scope.md`](docs/00-product-scope.md)
2. [`docs/01-critical-review.md`](docs/01-critical-review.md)
3. [`docs/02-architecture.md`](docs/02-architecture.md)
4. [`docs/03-agent-workflow.md`](docs/03-agent-workflow.md)
5. [`prompts/README.md`](prompts/README.md)
6. [`docs/06-development-plan.md`](docs/06-development-plan.md)
7. [`docs/07-junior-guide.md`](docs/07-junior-guide.md)
8. [`docs/09-open-questions.md`](docs/09-open-questions.md)

## قواعد غیرقابل‌مذاکره

- metadata یا abstract به‌تنهایی evidence متن کامل محسوب نمی‌شود.
- هر ادعای محتوایی سناریو باید به evidence ID و locator متصل باشد.
- اختلاف تفسیرها نباید به اجماع جعلی تبدیل شود.
- کاربر منبع نهایی را انتخاب می‌کند؛ سیستم بدون اطلاع او corpus را تغییر نمی‌دهد.
- سناریوی فارسی از outline معنایی و شواهد اصلی ساخته می‌شود، نه از ترجمه لفظ‌به‌لفظ یک پادکست انگلیسی.
- مدل نویسنده تنها verifier خروجی خودش نیست.
- اگر کیفیت parse، evidence یا audio از gate عبور نکند، pipeline متوقف می‌شود؛ خروجی ناقص silently منتشر نمی‌شود.

## مستندات مرجع

لینک مستندات رسمی ابزارهای فعلی در فایل‌های `docs/` ثبت شده است. انتخاب providerها provisional است و باید با یک corpus واقعی شامل مقاله، EPUB، PDF متنی و PDF اسکن‌شده benchmark شود.
