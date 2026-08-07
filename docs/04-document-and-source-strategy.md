# 04 — استراتژی سند و منبع

## ۱. چرا یک parser کافی نیست؟

فایل‌هایی که کاربر وارد می‌کند از نظر ساختار یکسان نیستند:

- EPUB با heading واقعی؛
- PDF متنی ساده؛
- PDF چندستونه دانشگاهی؛
- PDF اسکن‌شده؛
- کتاب دارای footnote، جدول و تصویر؛
- DOCX یا HTML؛
- URL صفحه وب.

یک parser ممکن است در extraction متن خوب و در reading order ضعیف باشد. دیگری scan را خوب بخواند ولی نصب سنگین‌تری داشته باشد. بنابراین انتخاب باید با inspect و benchmark انجام شود.

## ۲. ابزارهای فعلی

### Docling — انتخاب پیش‌فرض محلی

مزیت‌ها:

- Python-native و مناسب integration؛
- PDF، DOCX، PPTX، XLSX، HTML، EPUB و چند فرمت دیگر؛
- layout، reading order، table، formula و image classification؛
- representation ساختاریافته و exportهای مختلف؛
- مناسب برای شروع بدون ارسال فایل به سرویس خارجی.

ریسک‌ها:

- dependency و زمان نصب؛
- کیفیت باید روی فارسی و کتاب‌های واقعی benchmark شود؛
- ممکن است روی scanهای دشوار نیاز به fallback داشته باشد.

### MinerU — fallback برای سند دشوار

مزیت‌ها:

- OCR و layout پیچیده؛
- multi-column، formula، table و scan؛
- خروجی Markdown/JSON؛
- ابزارهای API/CLI.

ریسک‌ها:

- installation و runtime سنگین‌تر؛
- license سفارشی باید قبل از استفاده گسترده دوباره بررسی شود؛
- برای MVP نباید dependency اجباری همه نصب‌ها باشد.

### Firecrawl Parse — fallback میزبانی‌شده

مزیت‌ها:

- endpoint ساده برای local/non-public file؛
- modeهای `fast`, `auto`, `ocr`؛
- reading order و table preservation؛
- مناسب وقتی local parser شکست خورده است.

ریسک‌ها:

- ارسال فایل به provider؛
- credit cost؛
- محدودیت حجم و timeout؛
- وابستگی شبکه و privacy.

### MarkItDown — ابزار سبک، نه parser اصلی

مناسب برای conversionهای ساده و فرمت‌های متنوع است، اما نباید فرض شود PDFهای دانشگاهی پیچیده را با fidelity لازم پردازش می‌کند.

## ۳. Parser benchmark قبل از تصمیم نهایی

یک corpus ثابت بساز:

| Fixture | ویژگی |
|---|---|
| A | مقاله PDF متنی تک‌ستونه انگلیسی |
| B | مقاله PDF دو‌ستونه با footnote |
| C | کتاب PDF فارسی متنی |
| D | کتاب PDF اسکن‌شده فارسی |
| E | EPUB انگلیسی با فصل و زیرفصل |
| F | PDF دارای جدول و فرمول |

برای هر parser این معیارها ثبت شود:

- character recall روی sample دستی؛
- heading preservation؛
- reading order؛
- page locator accuracy؛
- footnote handling؛
- table/formula preservation؛
- repeated header removal؛
- runtime؛
- RAM/VRAM؛
- install difficulty؛
- privacy/cost.

نتیجه benchmark باید در `docs/benchmarks/document-parsers.md` ثبت شود. قبل از benchmark، هیچ ادعای «بهترین parser» نهایی نیست.

## ۴. Normalized document format

تمام parserها باید به representation داخلی واحد تبدیل شوند:

```json
{
  "source_id": "...",
  "parser": {
    "provider": "docling",
    "version": "...",
    "strategy": "default"
  },
  "pages": [],
  "headings": [],
  "blocks": [],
  "warnings": []
}
```

هر block:

```json
{
  "block_id": "src-1:b-0042",
  "heading_path": ["Chapter 2", "Action"],
  "locator": {
    "page_start": 81,
    "page_end": 83,
    "paragraph_start": 4,
    "paragraph_end": 9
  },
  "text": "...",
  "previous_block_id": "...",
  "next_block_id": "..."
}
```

Parser-specific JSON مستقیم وارد prompt نمی‌شود. ابتدا normalize می‌شود.

## ۵. Source discovery strategy

### جریان‌های جدا

1. **Bibliographic discovery:** شناسایی اثر، نویسنده، edition، DOI، citation و venue؛
2. **Content acquisition:** دستیابی قانونی و فنی به full text؛
3. **Web reference discovery:** منابع مرجع یا سازمانی؛
4. **User-provided source:** فایل یا URL که خود کاربر داده است.

این چهار جریان نباید با هم اشتباه شوند.

### OpenAlex

برای:

- scholarly work search؛
- author/venue metadata؛
- DOI/OpenAlex ID؛
- open-access location؛
- citation metadata؛
- semantic search در صورت نیاز.

OpenAlex metadata را evidence متن کامل فرض نکن.

### Firecrawl Search/Scrape

برای:

- جست‌وجوی وب؛
- صفحات JS-heavy؛
- دریافت Markdown تمیز؛
- صفحات دانشگاه، دانشنامه و publisher؛
- public PDF URL.

Search result description evidence نیست. بعد از انتخاب candidate باید content fetch و parse شود.

### Crossref

برای:

- DOI normalization؛
- publication metadata validation؛
- dedup.

### Google Books/Open Library

برای:

- title/author/edition/ISBN؛
- شناسایی کتاب؛
- preview/access information.

### Semantic Scholar

برای milestone بعد:

- paper recommendation؛
- references/citations؛
- seed-based discovery.

در MVP اضافه نمی‌شود مگر OpenAlex در corpus هدف کمبود مشخصی داشته باشد.

## ۶. Query families

برای مثال «هانا آرنت و مفهوم کنش»:

### Primary

- exact work/title queries؛
- author + concept؛
- edition/translation.

### Canonical reference

- academic encyclopedia؛
- handbook chapter؛
- university course/reference page.

### Scholarly interpretation

- concept + interpretation؛
- work + analysis؛
- author + debate term.

### Criticism

- feminist critique؛
- Marxist critique؛
- postcolonial critique؛
- named scholarly controversy.

### Recent scholarship

فقط اگر سؤال درباره وضعیت پژوهش فعلی است. برای فهم متن اصلی، جدیدبودن خودکار مزیت نیست.

### Persian

- ترجمه اصطلاح؛
- مقاله فارسی دانشگاهی؛
- اطلاعات edition و ترجمه؛
- تلفظ و usage رایج.

## ۷. Source selection UI contract

هر card حداقل:

- title؛
- author/year؛
- source role؛
- authority class؛
- access level؛
- relevance reasons؛
- limitations؛
- duplicate status؛
- source origin؛
- Include/Exclude/Background/Reading-only.

کاربر نباید با یک score مبهم تنها بماند.

## ۸. Evidence eligibility

یک source فقط وقتی می‌تواند evidence بسازد که:

- user decision = Include؛
- access = Full text؛
- parse quality pass یا pass_with_warning غیرمادی؛
- locator قابل‌استفاده؛
- source identity مشخص؛
- copyright/privacy policy اجازه پردازش بدهد.

## ۹. Chunking policy

هدف chunking کم‌کردن token نیست؛ حفظ واحد استدلال است.

ترتیب boundary:

1. chapter/section؛
2. heading؛
3. paragraph group؛
4. discourse marker؛
5. sentence boundary؛
6. token hard limit.

اگر یک argument از boundary عبور کرد:

- blockها linked می‌شوند؛
- dependency ثبت می‌شود؛
- evidence retrieval هر دو را برمی‌گرداند.

## ۱۰. Footnote و citation

- footnote از body حذف نشود؛ جدا و linked ذخیره شود؛
- bibliography برای source discovery مفید است، اما به‌صورت خودکار evidence نیست؛
- citation در متن باید به reference entry resolve شود اگر parser اجازه دهد؛
- quoted text باید تا حد ممکن marker جدا داشته باشد.

## ۱۱. Stop condition جست‌وجو

جست‌وجو تمام است وقتی:

- primary/reference/interpretation roleهای لازم پوشش دارند؛
- criticism مناسب scope وجود دارد یا نبود آن ثبت شده؛
- full-text evidence برای objectiveهای اصلی وجود دارد؛
- round جدید source متمایز و مؤثر نیاورده؛
- user corpus را تأیید کرده است.

تعداد source معیار کیفیت نیست.

## منابع رسمی

- [Docling GitHub](https://github.com/docling-project/docling)
- [MinerU GitHub](https://github.com/opendatalab/MinerU)
- [MarkItDown GitHub](https://github.com/microsoft/markitdown)
- [Firecrawl Parse](https://docs.firecrawl.dev/features/parse)
- [Firecrawl Search](https://docs.firecrawl.dev/api-reference/endpoint/search)
- [OpenAlex API](https://developers.openalex.org/)
