# 03 — EPUB ingestion

مرتبط: مسیر مشترک routing/quality-gate در [`../02-pipeline/01-document-ingestion.md`](../02-pipeline/01-document-ingestion.md).

## وضعیت

EPUB 2 و EPUB 3 اکنون در مسیر محلی Thesisound پشتیبانی می‌شوند:

```text
EPUB upload
→ archive safety validation
→ META-INF/container.xml
→ OPF package document
→ manifest + linear spine
→ XHTML blocks in reading order
→ parse-quality gate
→ explicit source selection
→ evidence pipeline
```

این parser وابستگی خارجی جدیدی ندارد و از ZIP/XML استاندارد Python استفاده می‌کند.

## ترتیب خواندن

ترتیب فایل‌های داخل ZIP یا ترتیب حروف الفبا مبنا نیست. parser فقط `itemref`های خطی
`spine` را، به همان ترتیب اعلام‌شده در package document، پردازش می‌کند. آیتم‌های
`linear="no"` و فایل‌های غیرمتنی وارد corpus نمی‌شوند.

## ساختار و locator

- headingهای `h1` تا `h6` به `heading_path` تبدیل می‌شوند؛
- paragraph، list item، blockquote، preformatted text، definition item و table به
  blockهای مستقل تبدیل می‌شوند؛
- `script`، `style`، `head`، `nav` و `noscript` حذف می‌شوند؛
- `source_block_key` شامل resource path و یک locator پایدار مبتنی بر package/spine
  با قالب `epubcfi(...)` است؛
- blockهای semantic بعدی chapter و section را از heading hierarchy می‌گیرند.

CFI ذخیره‌شده برای trace پایدار داخلی است؛ در این نسخه resolver تعاملی CFI در UI
وجود ندارد.

## محدودیت‌های امنیتی

قبل از parse، archive بررسی می‌شود:

- path مطلق، backslash و traversal segment رد می‌شوند؛
- entry رمزگذاری‌شده رد می‌شود؛
- مجموع حجم uncompressed سقف دارد؛
- content item بسیار بزرگ رد می‌شود؛
- compression ratio مشکوک رد می‌شود؛
- `mimetype` نامعتبر رد می‌شود؛
- archive روی filesystem extract نمی‌شود و entryها مستقیم خوانده می‌شوند.

## فرمت‌های پشتیبانی‌شده در UI

```text
PDF, EPUB, DOCX, TXT, Markdown
```

فرمان CLI عمومی نیز EPUB را با auto-routing می‌پذیرد:

```bash
uv run thesisound inspect book.epub
uv run thesisound parse book.epub --parser auto --output parse-result.json
uv run thesisound parse book.epub --parser epub --output parse-result.json
```

## پوشش خودکار

تست‌های regression شامل این حالت‌ها هستند:

- حفظ ترتیب دو فصل مطابق spine؛
- حفظ heading hierarchy فارسی؛
- حذف محتوای `script` و navigation؛
- عبور EPUB معتبر از ingestion و parse-quality gate؛
- ردکردن resource path مطلق و ناامن؛
- بارگذاری EPUB از UI و ثبت آن با parser نوع `epub`.

## خارج از scope فعلی

- EPUB دارای DRM یا entry رمزگذاری‌شده؛
- fixed-layout EPUB و محتوایی که معنا را فقط از layout تصویری می‌گیرد؛
- اجرای JavaScript؛
- استخراج متن از تصویرهای داخل EPUB؛
- media overlays و audiobook synchronization؛
- نمایش تعاملی CFI در مرورگر.

چنین منابعی باید blocked/manual-review شوند یا با نسخه متنی دیگری جایگزین شوند.
