# 10 — Document ingestion

این سند قرارداد اجرایی ingestion را توضیح می‌دهد. هدف این subsystem تبدیل فایل ورودی به `ParsedDocument` قابل‌ممیزی است؛ نه خلاصه‌سازی و نه استخراج claim.

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

قواعد فعلی:

1. فایل encrypted متوقف می‌شود.
2. PDF یا تصویر با `image_only_ratio >= 0.67` ابتدا به MinerU می‌رود.
3. سند دارای signal layout پیچیده ابتدا به MinerU می‌رود.
4. سند text-bearing معمولی ابتدا به Docling می‌رود.
5. parser دوم fallback است و فقط وقتی اجرا می‌شود که parser اول خطا دهد یا از quality gate عبور نکند.

این routing هزینه اجرای هم‌زمان دو parser را در مسیر عادی حذف می‌کند.

## Docling

Docling داخل process اجرا می‌شود و خروجی آن فوراً به قرارداد داخلی normalize می‌شود. هیچ object اختصاصی Docling وارد domain layer نمی‌شود.

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

MinerU یک runtime مستقل و سنگین است. آن را طبق مستندات رسمی MinerU نصب کنید و مطمئن شوید فرمان `mineru` روی `PATH` قرار دارد. Thesisound عمداً MinerU را dependency اجباری محیط اصلی نکرده است.

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
