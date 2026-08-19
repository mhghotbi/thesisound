# 09 — پرسش‌های باز

سند زنده. این موارد هنوز تصمیم نهایی نیستند و developer نباید با تکیه بر حدس، آن‌ها را در معماری تثبیت کند. هر OQ به سند مربوطه‌اش وابسته است — عمدتاً [`04-document-and-source-strategy.md`](04-document-and-source-strategy.md) (انتخاب parser)، [`02-architecture.md`](02-architecture.md) و [`03-agent-workflow.md`](03-agent-workflow.md).

## OQ-001 — Docling یا MinerU برای corpus اصلی؟

### وضعیت

باز است.

### تصمیم لازم

پس از benchmark روی PDF فارسی، PDF دو‌ستونه، scan و EPUB.

### معیار

- text recall؛
- reading order؛
- heading؛
- locator؛
- runtime؛
- install complexity.

### تا آن زمان

Docling default provisional و MinerU fallback provisional است.

---

## OQ-002 — دو گوینده یا تک‌گوینده؟

### وضعیت

باز است.

### ریسک

دو گوینده ممکن است شبیه NotebookLM و جذاب‌تر باشد، اما:

- voice drift بیشتر؛
- filler بیشتر؛
- attribution پیچیده‌تر؛
- TTS فارسی ناپایدارتر.

### آزمایش

یک script واحد با:

1. تک‌راوی؛
2. دوگوینده restrained؛
3. دوگوینده conversational.

مقایسه blind روی clarity، طبیعی‌بودن و fatigue.

---

## OQ-003 — آیا سناریوی مستقیم فارسی از English semantic plan بهتر است؟

### فرض فعلی

بله؛ چون translation chain حذف می‌شود.

### آزمایش

- direct Persian from evidence؛
- English script + Persian adaptation؛
- Persian plan + Persian script.

معیار: meaning preservation، fluency و term consistency.

---

## OQ-004 — آیا SQLite FTS5 برای retrieval کافی است؟

### فرض فعلی

برای one-user MVP و claim-to-block mapping کافی است.

### trigger افزودن embedding

- must-cover recall پایین؛
- claim context در sectionهای دور پیدا نمی‌شود؛
- multi-source corpus از retrieval lexical عبور می‌کند.

### گزینه‌های بعدی

- Gemini Embedding؛
- Gemini File Search؛
- local embedding + sqlite-vec/pgvector.

---

## OQ-005 — Search provider اصلی چیست؟ **(بسته)**

Gemini Google Search grounding؛ کلیدهای Firecrawl، OpenAlex و Semantic Scholar از تنظیمات فعال حذف شده‌اند. جزئیات در [`../04-integrations/01-gemini-grounding.md`](../04-integrations/01-gemini-grounding.md).

بازگشایی فقط با یکی از این triggerها: نیاز به citation graph، recommendation از seed paper، یا ناکافی‌بودن پوشش grounding در رشتهٔ هدف.

---

## OQ-006 — اندازه مطلوب TTS segment

### وضعیت

باید empirical تعیین شود.

### آزمایش

segmentهای ۶۰، ۱۲۰، ۱۸۰ و ۲۴۰ ثانیه‌ای.

### معیار

- voice consistency؛
- truncation؛
- retry rate؛
- transition quality؛
- cost/latency.

---

## OQ-007 — کیفیت Free Tier برای فایل‌های واقعی

### ریسک

- quota؛
- terms/data usage؛
- preview availability؛
- rate limits.

### تصمیم

MVP ابتدا Free Tier را تست می‌کند، ولی config و provider abstraction باید migration به Paid Tier یا provider دیگر را ممکن کند.

---

## OQ-008 — منبع فارسی در glossary چقدر لازم است؟

برای متفکران ترجمه‌شده، ترجمه فارسی اصطلاحات خود یک مسئله پژوهشی است.

### آزمایش

- glossary فقط از مدل؛
- glossary با یک ترجمه فارسی منتخب؛
- user override.

### معیار

term consistency و رضایت کاربر آشنا با متن.

---

## OQ-009 — چه مقدار منبع برای یک اپیزود کافی است؟

تعداد ثابت غلط است. با role coverage سنجیده شود.

### فرض MVP

- یک primary؛
- یک reference/secondary؛
- یک criticism فقط اگر mode لازم دارد.

اما در source-bound mode ممکن است فقط یک کتاب کافی باشد.

---

## OQ-010 — حد quote و نمایش متن

قبل از public sharing باید policy مشخص شود:

- حداکثر excerpt قابل نمایش؛
- private versus public export؛
- copyrighted source handling؛
- attribution format.

در MVP خروجی private است.

---

## OQ-011 — تشخیص فصل بدون تأیید انسانی (سند ۱۰، P1)

### وضعیت

باز است؛ تصمیم فعلی مالک: بدون تأیید.

### تصمیم لازم

آیا تشخیص قطعی فصل از `heading_path`/TOC روی PDFهای واقعی با heading تخت به‌اندازهٔ کافی قابل اعتماد است؟ اگر نه، یک گام تأیید/اصلاح فصل‌ها (مثل `confirmedChapters` در AQT Maker) اضافه می‌شود.

### معیار

نسبت منابع P6 که `detected_from` آن‌ها `heading` یا `toc` است و مالک فصل‌بندی را درست می‌داند.

### تا آن زمان

Pass 0 فقط `detected_from` را گزارش می‌کند و صفحهٔ نقشهٔ مفهومی فصل‌ها را نشان می‌دهد.

---

## OQ-012 — آستانه‌های tier و قاعدهٔ پرکردن بخش (سند ۱۰، §5.4 و §5.5)

### وضعیت

باز است؛ مقادیر اولیه حدس مهندسی‌اند.

### تصمیم لازم

توزیع tier در هر فصل (فعلاً tier 1 در [۰٫۱۵، ۰٫۴۵]، tier 3 ≥ ۰٫۱۰ برای فصل‌های ≥ ۶ سلول) و کف پرکردن بخش (فعلاً ۰٫۸ × طول اپیزود) باید با یک منبع واقعی علوم انسانی تنظیم شوند.

### معیار

بازبینی انسانی P6: آیا `concise` واقعاً «جهت‌گیری» می‌دهد و `standard` «یادگیری درست»؟ آیا بخش‌ها منسجم‌اند یا برای پرشدن، سلول بی‌ربط گرفته‌اند؟

### تا آن زمان

ثابت‌ها در یک فایل (`part_packer.py`، `concepts.py`) با یادداشت تنظیم‌نشده.
