# Thesisound

[![CI](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml/badge.svg)](https://github.com/mhghotbi/thesisound/actions/workflows/ci.yml)

Thesisound یک ابزار محلی برای تبدیل موضوع و منابع کاربر به پادکست فارسی منبع‌محور، قابل‌ردیابی و قابل‌ممیزی است.

## مسیر فعلی محصول

```text
OTP login
→ create project and confirm Research Brief
→ upload and inspect sources
→ parse-quality gate
→ explicitly confirm corpus
→ semantic blocks, evidence, and claims
→ coverage audit and supported-duration gate
→ review and approve Episode Plan
→ grounded Persian script
→ deterministic checks and independent verification
→ explicitly start audio generation
→ TTS-safe chunking
→ Gemini TTS
→ WAV validation
→ Gemini ASR
→ expected-vs-heard QA
→ targeted regeneration
→ FFmpeg normalization and assembly
→ verified final WAV
→ COMPLETE
```

Source Discovery و production deployment هنوز جزو مسیر فعلی نیستند. کاربر منابع را خودش بارگذاری می‌کند.

## نصب برای اجرای کامل محلی

نیازمندی‌های پایه:

- Python 3.12 یا جدیدتر؛
- `uv`؛
- FFmpeg روی `PATH`؛
- کلید Gemini برای مرحله‌های مدل، TTS و ASR.

نصب UI، Gemini و ابزار توسعه:

```bash
uv sync --extra dev --extra web-ui --extra gemini
cp .env.example .env
```

برای PDFهای پیچیده‌تر، Docling را هم نصب کنید:

```bash
uv sync --extra dev --extra web-ui --extra gemini --extra parsers
```

MinerU runtime مستقلی است؛ اگر استفاده می‌شود، فرمان `mineru` باید روی `PATH` باشد.

در `.env` حداقل این مقدار را تنظیم کنید:

```dotenv
GEMINI_API_KEY=...
```

## بررسی محیط پیش از هزینه API

```bash
uv run thesisound doctor
```

این فرمان موارد زیر را بررسی می‌کند:

- تنظیم بودن `GEMINI_API_KEY`؛
- نصب `google-genai`؛
- وجود FFmpeg؛
- writable بودن workspace و ingestion artifact roots؛
- parserهای واقعاً در دسترس.

همین preflight داخل UI نیز روی actionهای هزینه‌دار enforce می‌شود. اگر پیش‌نیازی ناقص باشد، run قبل از queue شدن متوقف و کاربر به `/system-check` هدایت می‌شود.

## اجرای وب

```bash
uv run thesisound-web
```

سپس باز کنید:

```text
http://127.0.0.1:8000
```

ورود توسعه‌ای پیش‌فرض:

```text
phone: 0912000000
otp:   999999
```

OTP تستی فقط در development مجاز است. startup در production با OTP تستی، demo mode، cookie ناامن یا secret پیش‌فرض رد می‌شود.

## تست دستی از ابتدا تا انتها

1. وارد شوید.
2. پروژه جدید بسازید و موضوع، مخاطب، مدت و mode را مشخص کنید.
3. Research Brief را بررسی و صریحاً تأیید کنید.
4. یک PDF، DOCX، TXT یا Markdown اضافه کنید.
5. وضعیت parser و quality gate را ببینید.
6. منبع آماده را انتخاب و corpus را تأیید کنید.
7. منتظر ساخت semantic blocks، evidence و claims بمانید.
8. Coverage Audit و مدت قابل‌پشتیبانی را بررسی کنید.
9. Episode Plan را صریحاً تأیید کنید.
10. سناریو، verifier result و source trace را بررسی کنید.
11. از همان صفحه روی «ادامه به ساخت صوت» بزنید.
12. preflight صوت را بررسی و تولید را شروع کنید.
13. chunkها، ASR diff، regeneration و فایل نهایی را بررسی کنید.
14. WAV نهایی را پخش یا دانلود کنید.

اگر یک منبع `review` یا `blocked` شد، در همان صفحه می‌توان extraction را دوباره اجرا یا منبع را حذف کرد. نصب parser جدید و سپس retry باعث می‌شود مسیر auto با ابزارهای تازه در دسترس دوباره اجرا شود.

## فرمان‌های CLI اصلی

```bash
uv run thesisound doctor
uv run thesisound init "آرنت و مفهوم کنش"
uv run thesisound status <project-id>
uv run thesisound parse source.pdf --parser auto --output parse-result.json
uv run thesisound analyze-source <project-id> parse-result.json
uv run thesisound prepare-episode <project-id>
uv run thesisound prepare-script <project-id>
uv run thesisound prepare-audio <project-id>
uv run thesisound audio-status <project-id>
```

## قواعد اصلی pipeline

- metadata یا abstract به‌تنهایی evidence متن کامل نیست.
- parse، block ID و locator به مدت خروجی وابسته نیستند.
- breadth و depth تحلیل به مدت، مخاطب و mode وابسته‌اند.
- مدل حق ساختن source ID، locator، evidence ID، claim ID، segment ID یا turn ID را ندارد.
- supporting excerpt باید واقعاً در source block موجود باشد.
- corpus ناکافی با padding به مدت هدف نمی‌رسد.
- ادامه با corpus ناکافی مجاز نیست؛ باید مدت، منبع یا تمرکز تغییر کند.
- هر turn محتوایی باید claim و evidence معتبر داشته باشد.
- writer تنها verifier خروجی خودش نیست.
- script و audio به hash نسخه بالادستی متصل‌اند.
- retry artifactهای سالم را دوباره تولید نمی‌کند.
- final audio فقط وقتی serve می‌شود که checksum و binding آن معتبر باشد.

## artifactها

```text
workspaces/<project-id>/
  project.json
  ui-source-manifest.json
  corpus-build-run.json
  episode-planning-run.json
  script-build-run.json
  audio-build-run.json

  sources/<source-id>/
    parsed-document.json
    document-blocks.jsonl
    document-map.json
    evidence-items.jsonl
    claim-ledger.json

  episode/
    coverage-report.json
    budget-report.json
    episode-plan.json
    evidence-packs.jsonl

  script/
    glossary.json
    script-draft.json
    checks.json
    verification.json
    script-revised.json

  audio/
    chunks.json
    segments/*.wav
    transcripts/*.json
    qa/*.json
    final.wav
    manifest.json
```

## وضعیت milestoneها

- M0 Scaffold and contracts: implemented
- M1 Document ingestion: implemented
- M2 Structured model execution: implemented
- M3 Evidence pipeline: implemented
- M4 Episode preparation: implemented
- M5 Verified Persian script: implemented
- M6 TTS, ASR, and Audio QA: implemented in code
- M6.5 Local Operator UI: implemented for the current source-bound flow
- M7 Source Discovery: not implemented
- M8 Full cross-source semantic reconciliation: not implemented
- M9 General end-user product UI: not implemented
- M10 Production persistence, jobs, deployment, and real OTP: not implemented

## چیزی که هنوز اثبات نشده است

کد مسیر کامل وجود دارد، اما کیفیت واقعی هنوز باید با اجرای زنده سنجیده شود:

- کیفیت استخراج PDF فارسی و OCR؛
- رفتار مدل‌های تنظیم‌شده در API واقعی؛
- تلفظ، prosody و تفکیک voiceهای فارسی؛
- دقت ASR و thresholdهای QA؛
- latency، هزینه و regeneration rate؛
- تجربه شنیداری blind review.

## اسناد مهم

- [`STATUS.md`](STATUS.md)
- [`docs/02-architecture.md`](docs/02-architecture.md)
- [`docs/13-output-aware-analysis-budget.md`](docs/13-output-aware-analysis-budget.md)
- [`docs/14-episode-preparation.md`](docs/14-episode-preparation.md)
- [`docs/15-persian-script-pipeline.md`](docs/15-persian-script-pipeline.md)
- [`docs/16-operator-user-workflow.md`](docs/16-operator-user-workflow.md)
- [`docs/17-interface-state-model.md`](docs/17-interface-state-model.md)
- [`docs/19-error-and-recovery-ux.md`](docs/19-error-and-recovery-ux.md)
- [`docs/25-audio-vertical-slice.md`](docs/25-audio-vertical-slice.md)
- [`docs/26-local-live-e2e-runbook.md`](docs/26-local-live-e2e-runbook.md)
