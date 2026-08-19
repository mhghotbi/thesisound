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

### OCR محلی — صفحهٔ تصویری

مسیریابی صفحه‌محور و اجرای offline در [`../04-integrations/04-self-hosted-ocr.md`](../04-integrations/04-self-hosted-ocr.md). هیچ parser میزبانی‌شده‌ای فعال نیست؛ parse به‌صورت پیش‌فرض محلی می‌ماند و فایل خام به provider بیرونی نمی‌رود.

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

### connector فعلی

تنها مسیر اجراشونده **Gemini Google Search grounding** است ([`../04-integrations/01-gemini-grounding.md`](../04-integrations/01-gemini-grounding.md)). قاعده‌ای که مستقل از provider می‌ماند: **نتیجهٔ جست‌وجو candidate است، نه evidence.** توضیح یا snippet نتیجه هرگز evidence نیست؛ candidate باید fetch، parse و صریحاً توسط کاربر انتخاب شود.

### connectorهای رزروشده

`openalex`، `semantic_scholar`، `crossref`، `google_books`، `open_library` فقط مقدار مجاز `SearchQuery.provider` در `domain.py` هستند و connector ندارند. اگر روزی اضافه شدند، تقسیم کارشان این است: OpenAlex برای scholarly search و open-access location؛ Crossref برای DOI normalization و dedup؛ Google Books/Open Library برای edition و ISBN؛ Semantic Scholar برای citation graph. در همهٔ این موارد metadata را evidence متن کامل فرض نکن.

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

(سند ۱۰، P1) بالای block، لایهٔ **فصل** قطعی اضافه می‌شود: گروه‌بندی پیوستهٔ بلاک‌ها بر اساس `heading_path` (عمق ۰ سپس ۱) یا TOC سند؛ document map و سلول‌های مفهومی فصل‌به‌فصل ساخته می‌شوند و هیچ متنی بریده نمی‌شود (برخلاف AQT Maker که متن فصل/زیرموضوع را با سقف کاراکتر می‌بُرد).

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
