# 01 — Document ingestion

این سند قرارداد اجرایی ingestion را توضیح می‌دهد. هدف این subsystem تبدیل فایل ورودی به `ParsedDocument` قابل‌ممیزی است؛ نه خلاصه‌سازی و نه استخراج claim. خروجی `ParsedDocument` مستقیماً ورودی [`03-one-source-evidence-pipeline.md`](03-one-source-evidence-pipeline.md) است.

## جریان اجرایی

```text
local file
  -> deterministic inspection
  -> parser routing
  -> primary parser
  -> normalization
  -> deterministic quality gate
  -> optional fallback parser
  -> selected safe parse
  -> persisted artifacts
```

## Inspection

`document_inspector.py` بدون مدل زبانی این موارد را ثبت می‌کند:

- مسیر canonical؛
- MIME و extension؛
- اندازه و SHA-256؛
- تعداد صفحات PDF؛
- encryption؛
- میزان متن استخراج‌پذیر در صفحات نمونه؛
- نسبت صفحات نمونه بدون متن؛
- signal اولیه layout پیچیده.

`pypdf` فقط برای inspection سبک استفاده می‌شود و parser اصلی محسوب نمی‌شود.

## Routing

قواعد فعلی (cheapest-capable):

1. فایل encrypted متوقف می‌شود.
2. EPUB فقط با parser اختصاصی `epub` پردازش می‌شود.
3. PDF یا تصویر با `image_only_ratio >= 0.67` ابتدا به `local-ocr` (وگرنه MinerU) می‌رود؛ Docling/native فقط fallbackاند.
4. HTML/HTM ابتدا به Docling می‌رود.
5. سند text-bearing معمولی (PDF/DOCX/TXT/MD) ابتدا به `native` می‌رود.
6. سند با signal layout پیچیده ولی لایهٔ متن سالم ابتدا `native` را به‌عنوان probe ارزان اجرا می‌کند؛ فقط اگر quality gate آن را unsafe بداند به Docling سپس MinerU/`local-ocr` می‌رود.
7. اگر `native` در دسترس نباشد، layout پیچیده با Docling شروع می‌شود.
8. parser بعدی فقط وقتی اجرا می‌شود که parser قبلی خطا دهد، timeout بخورد، یا از quality gate عبور نکند.

این routing هزینهٔ اجرای هم‌زمان چند parser را در مسیر عادی حذف می‌کند و از اجرای زودهنگام Docling روی ورودی‌های دیجیتال ساده جلوگیری می‌کند.

## Docling

Docling در یک **worker process جداگانه** اجرا می‌شود و خروجی آن فوراً به قرارداد داخلی normalize می‌شود. هیچ object اختصاصی Docling وارد domain layer نمی‌شود.

Timeout پیش‌فرض `THESISOUND_DOCLING_TIMEOUT_SECONDS=360` است. اگر تبدیل از این سقف بگذرد، worker terminate می‌شود، attempt به‌عنوان خطا ثبت می‌شود، و ingestion به fallback بعدی می‌رود.

## MinerU

MinerU از طریق CLI رسمی اجرا می‌شود:

```bash
mineru -p <input_path> -o <output_path>
```

این انتخاب عمدی است. API داخلی پایتون MinerU سریع‌تر از CLI تغییر می‌کند، درحالی‌که CLI و structured output سطح integration پایدارترند.

Adapter به‌ترتیب این خروجی‌ها را ترجیح می‌دهد:

1. `*_content_list_v2.json`
2. `*_content_list.json`
3. `*_middle.json`

`content_list` در مستندات MinerU به‌عنوان خروجی flat و reading-order-friendly برای downstream processing معرفی شده است.

Adapter خودش نیز خروجی خام CLI را بر اساس `(sha256 فایل, نسخهٔ mineru, backend, model_source)` در `raw/mineru/<sha-prefix>/<fingerprint>/` نگه می‌دارد و دوباره اجرا نمی‌کند، مگر این‌که یکی از این‌ها عوض شود. کامل بودن اجرا با یک فایل نشانگر (`.mineru-complete`) تعیین می‌شود، نه صرفاً وجود یک JSON ساختاریافته؛ یک اجرای نیمه‌کاره که فرآیند در وسط راه از بین رفته دوباره از نو اجرا می‌شود.

## کش مشترک پارس‌شدن

پارس‌شدن گران‌ترین مرحلهٔ غیرمدلیِ کل pipeline است — OCR روی یک کتاب اسکن‌شده می‌تواند دقیقه‌ها طول بکشد، در برابر یک فراخوان مدل برای نقشهٔ سند. `ingest_document` این هزینه را برای بایت‌های یکسان فقط یک‌بار در کل ماشین می‌پردازد، نه یک‌بار به ازای هر پروژه یا هر کاربر.

آنچه کش می‌شود دقیقاً `ParsedDocument` هر parser است، نه کل `IngestionResult`. `inspect_document`، routing، quality gate، رتبه‌بندی attemptها و نوشتن artifactهای پروژه هر بار محلی و کامل اجرا می‌شوند؛ فقط فراخوانی `parser.parse(...)` است که روی hit رد می‌شود.

### کلید

کلید سه فیلد از `DocumentInspection` را با نام و identity parser ترکیب می‌کند:

- `sha256` فایل؛
- `extension` — چون `native` روی آن dispatch می‌کند و بایت‌های یکسان با نام `.pdf` و `.txt` دو سند متفاوت‌اند؛
- `encrypted`؛
- `likely_complex_layout` — تنها فیلدی که worker مربوط به OCR می‌خواند.

عمداً `mime_type`، `page_count`، `image_only_ratio`، `file_size_bytes` و `sampled_text_characters` در کلید نیستند: هیچ parseری آن‌ها را نمی‌خواند، با نسخهٔ `pypdf` نصب‌شده drift می‌کنند، و `mime_type` از رجیستری سیستم‌عامل خوانده می‌شود — گنجاندنشان یعنی یک ارتقای بی‌ربط entryهای parserهایی را هم دور بریزد که اصلاً pypdf لمس نمی‌کنند.

نسخهٔ provider و الگوریتم داخل `identity()` هر parser است، نه در هش کلی inspection. هر adapter این متد اختیاری را پیاده می‌کند و در سه حالت `None` برمی‌گرداند — یعنی هرگز خوانده یا نوشته نمی‌شود:

1. یک collaborator تزریق‌شده دارد (runner یا version resolver تست)؛
2. نسخهٔ provider قابل‌تشخیص نیست (`"unknown"`)؛
3. فینگرپرینت کد سازنده قابل‌محاسبه نیست.

فینگرپرینت کد یعنی sha256 بایت‌های خودِ فایل‌های پایتونی که خروجی را می‌سازند (adapter + normalizer مربوطه)، نه یک رشتهٔ نسخهٔ دستی. تغییر نحوهٔ تبدیل blockهای MinerU به heading بدون این، کش را ساکت با نتیجهٔ کهنه پر می‌کرد.

`local-ocr` در interpreter جدایی اجرا می‌شود (`THESISOUND_OCR_PYTHON`)، پس محاسبهٔ `identity()` نمی‌تواند نسخهٔ `paddleocr`/`PyMuPDF`/`Pillow` را از process فراخوان ببیند. به‌جایش همان interpreter با `python -m thesisound.ocr_runtime_probe` صدا زده می‌شود — ماژولی سبک که فقط metadata نصب را می‌خواند، نه خودِ کتابخانه‌ها را import می‌کند — و نتیجه در کلید می‌نشیند. اگر probe fail شود (timeout، خروجی نامعتبر، نبود دسترسی)، `identity()` بدون ابهام `None` برمی‌گرداند.

### محل ذخیره

```text
artifacts/ingestion/_shared/parsed-documents/<cache_key>.json
```

مثل `workspaces/_shared/document-maps/`، این مسیر با `_shared` از هر `<project_id>` (که همیشه UUID است) قابل‌تشخیص است. نوشتن atomic است (فایل موقت با نام یکتا به ازای هر نویسنده، سپس `replace`؛ برخلاف کش نقشهٔ سند، نام موقت ثابت نیست چون دو درخواست وب می‌توانند هم‌زمان یک فایل را parse کنند)، و یک entry پس از نوشتن هرگز بازنویسی نمی‌شود.

آنچه ذخیره **نمی‌شود**: `ParseReport` (کیفیت همیشه محلی و تازه محاسبه می‌شود، پس حتی روی hit نتیجهٔ quality gate را کدِ همین لحظه تعیین می‌کند، نه اجرای اول)، `raw_artifact_ref` (مسیر مطلقی به artifact tree پروژهٔ اولی که parse کرده — همان‌جا هم پس از rekey شدن منبع دیگر معتبر نیست)، و هیچ locator یا شناسهٔ پروژه‌ای.

با `THESISOUND_PARSED_DOCUMENT_CACHE_ENABLED=false` می‌توان کش را کامل خاموش کرد — اولین قدم برای فهمیدن این‌که یک parse مشکوک از کش می‌آید یا خودِ parser.

### مرز صادقانه

وزن مدل‌های Docling و MinerU در این ریپو pin نشده؛ تغییر وزن مدل بدون تغییر نسخهٔ پکیج یا `model_source`، کش را invalidate نمی‌کند.

کش content-addressed است: خواندن یک entry فقط با داشتن دقیقاً همان بایت‌هایی که کلیدش را ساخته‌اند ممکن است. این تنها مرزی است که بین دو کاربر وجود دارد — در کل این سیستم امروز هیچ مفهوم tenant یا مالکیت دیگری تعریف نشده.

## Artifact layout

```text
artifacts/ingestion/
  <stem>-<sha-prefix>/
    inspection.json
    ingestion-result.json
    parser-benchmark.json              optional
    attempts/
      docling/
        attempt.json
        parsed-document.json
        parse-quality.json
      mineru/
        attempt.json
        parsed-document.json
        parse-quality.json
  raw/
    mineru/
      <sha-prefix>/
        ... native MinerU outputs ...
```

همه JSONها با temp file و atomic replace نوشته می‌شوند.

## Quality gate

Quality gate deterministic است و موارد زیر را می‌سنجد:

- نبود متن؛
- حجم متن بسیار کم؛
- blockهای تکراری؛
- الگوهای OCR خراب؛
- نبود locator صفحه؛
- پوشش کم صفحات؛
- image-only بودن؛
- از بین رفتن heading hierarchy.

Verdictها:

```text
pass          safe
warning       safe, with recorded issues
retry         unsafe; try fallback
manual_review unsafe; human intervention required
```

## Benchmark

`compare-parsers` هر parser configured را روی یک سند اجرا می‌کند. `benchmark-parsers` همین کار را روی یک directory انجام می‌دهد.

Metrics فعلی:

- duration؛
- quality verdict؛
- safe/unsafe؛
- block count؛
- text characters؛
- locator coverage؛
- page coverage؛
- heading coverage؛
- duplicate ratio؛
- issue count؛
- composite score.

Composite score فقط ابزار ranking اولیه است. برای انتخاب parser نهایی باید خطاهای reading order، جدول و فرمول روی corpus واقعی نیز به‌صورت انسانی بررسی شوند.

## نصب

پایه و تست‌ها:

```bash
uv sync --extra dev
```

Docling:

```bash
uv sync --extra dev --extra parsers
```

`--extra parsers` هر دو adapter را نصب می‌کند: Docling به‌عنوان پکیج پایتون و MinerU به‌عنوان CLI داخل `.venv` (`mineru` روی PATH محیط پروژه). این extras اختیاری‌اند؛ محیط اصلی بدون آن‌ها برای text PDF / TXT / Markdown / DOCX کافی است.

## CLI

```bash
thesisound inspect file.pdf

thesisound parse file.pdf --parser auto
thesisound parse file.pdf --parser docling
thesisound parse file.pdf --parser mineru

thesisound compare-parsers file.pdf --output benchmark.json

thesisound benchmark-parsers ./benchmark-corpus \
  --recursive \
  --output benchmark-suite.json
```

Exit codeها:

- `0`: خروجی safe یا benchmark دارای نتیجه؛
- `1`: خطای input/configuration؛
- `2`: parse unsafe یا corpus خالی.

## ساخت corpus واقعی

فایل‌های دارای copyright نباید در Git commit شوند. یک directory محلی بسازید:

```text
benchmark-corpus/
  01-simple-text.pdf
  02-two-column-paper.pdf
  03-book-chapter.pdf
  04-scanned-persian.pdf
  05-footnotes.pdf
  06-table-formula.pdf
  07-sample.epub
```

برای هر فایل یک rubric انسانی جدا نگه دارید:

```json
{
  "expected_pages": 20,
  "must_preserve_headings": ["Introduction", "Conclusion"],
  "known_reading_order_traps": ["page 4 two-column body"],
  "must_preserve_tables": ["table 2"],
  "notes": "Do not commit the source document."
}
```

## Definition of Done

کد Milestone 1 اکنون این موارد را دارد:

- inspection واقعی PDF؛
- Docling adapter؛
- MinerU CLI adapter؛
- normalization چندنسخه‌ای MinerU؛
- automatic routing؛
- fallback؛
- deterministic quality gate؛
- atomic artifacts؛
- single-document benchmark؛
- directory benchmark؛
- generated-PDF tests در CI.

تنها خروجی‌ای که باید خارج از ریپو و با منابع واقعی تولید شود، گزارش benchmark اختصاصی corpus کاربر است. نتیجه آن باید بعداً در ADR انتخاب parser ثبت شود.

## منابع رسمی

- Docling: <https://github.com/docling-project/docling>
- MinerU quick usage: <https://github.com/opendatalab/MinerU/blob/master/docs/en/usage/quick_usage.md>
- MinerU output files: <https://github.com/opendatalab/MinerU/blob/master/docs/en/reference/output_files.md>
