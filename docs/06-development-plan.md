# 06 — برنامه توسعه

## راهبرد

ترتیب توسعه بر اساس ریسک است، نه بر اساس جذابیت UI.

بزرگ‌ترین unknownها:

1. کیفیت parse روی منابع واقعی؛
2. حفظ پوشش و تمایزها؛
3. کیفیت سناریوی فارسی؛
4. کیفیت TTS فارسی؛
5. مقدار کار دستی باقی‌مانده.

بنابراین اول vertical slice، بعد discovery و UI.

---

# Milestone 0 — Scaffold و قراردادها

## هدف

ساخت core قابل تست، بدون API واقعی.

## کارها

- Pydantic domain models؛
- state machine؛
- workspace artifact layout؛
- prompt loader؛
- CLI `init/status/dump`؛
- tests؛
- config providerها.

## خروجی

```bash
thesisound init "آرنت و مفهوم کنش"
thesisound status <project-id>
```

## Definition of Done

- پروژه local ساخته می‌شود؛
- manifest round-trip دارد؛
- transition نامعتبر رد می‌شود؛
- promptها از فایل load می‌شوند؛
- هیچ secret در Git نیست.

---

# Milestone 1 — Document ingestion benchmark

## هدف

انتخاب parser بر اساس داده واقعی.

## کد موردنیاز

```text
src/thesisound/ports/parser.py
src/thesisound/adapters/parsers/docling.py
src/thesisound/adapters/parsers/mineru.py
src/thesisound/services/document_inspector.py
src/thesisound/services/document_normalizer.py
src/thesisound/services/parse_quality.py
```

## Interface

```python
class DocumentParserPort(Protocol):
    def inspect(self, path: Path) -> DocumentInspection: ...
    def parse(self, path: Path, strategy: ParseStrategy) -> ParsedDocument: ...
```

## CLI

```bash
thesisound inspect path/to/file.pdf
thesisound parse path/to/file.pdf --parser docling
thesisound compare-parsers path/to/file.pdf
```

## تست‌ها

- PDF ساده؛
- PDF چندستونه؛
- scan؛
- EPUB؛
- heading preservation؛
- page locator.

## Definition of Done

- benchmark report واقعی؛
- parser default و fallback بر اساس evidence؛
- normalized block output؛
- parse gate.

---

# Milestone 2 — Gemini structured-output adapter

## هدف

یک adapter قابل اعتماد برای promptهای schema-bound.

## کد

```text
src/thesisound/ports/text_model.py
src/thesisound/adapters/gemini/text_model.py
src/thesisound/services/model_runner.py
```

## نیازها

- Pydantic schema -> provider schema؛
- timeout؛
- retry فقط روی خطای transient/schema؛
- usage metadata؛
- prompt/model version؛
- raw response optional؛
- deterministic artifact hash.

## smoke test

- یک brief فارسی؛
- یک structured output؛
- invalid schema retry؛
- missing key error.

## Definition of Done

- `ResearchBrief` معتبر از یک input واقعی؛
- provider error به domain error تبدیل می‌شود؛
- مدل از config خوانده می‌شود.

---

# Milestone 3 — One-source evidence pipeline

## هدف

یک فصل واقعی را به evidence و claim ledger تبدیل کن.

## کد

```text
src/thesisound/services/document_mapper.py
src/thesisound/services/evidence_extractor.py
src/thesisound/services/evidence_validator.py
src/thesisound/services/claim_reconciler.py
```

## جریان

```text
Parsed blocks
 -> section grouping
 -> document map
 -> evidence extraction
 -> excerpt validation
 -> claim reconciliation
```

## نکته

ابتدا فقط یک source. Cross-source synthesis را هنوز نساز.

## Definition of Done

- excerptها با متن match می‌شوند؛
- locator درست است؛
- claim بدون evidence ساخته نمی‌شود؛
- must-cover pointهای fixture پیدا می‌شوند.

---

# Milestone 4 — Episode plan و سناریوی فارسی

## هدف

از یک source، یک سناریوی ۸ تا ۱۲ دقیقه‌ای verified بساز.

## کد

```text
src/thesisound/services/episode_planner.py
src/thesisound/services/evidence_pack.py
src/thesisound/services/glossary.py
src/thesisound/services/script_writer.py
src/thesisound/services/script_verifier.py
```

## جریان

```text
Claims
 -> episode plan
 -> segment evidence pack
 -> glossary
 -> Persian script
 -> deterministic checks
 -> adversarial verifier
 -> targeted revision
```

## Definition of Done

- همه turnهای substantive claim ID دارند؛
- unsupported claim ratio صفر؛
- اصطلاح‌های مهم consistency دارند؛
- human reviewer سناریو را قابل شنیدن می‌داند.

---

# Milestone 5 — TTS vertical slice

## هدف

سناریوی verified را به صوت فارسی verified تبدیل کن.

## کد

```text
src/thesisound/ports/tts.py
src/thesisound/ports/asr.py
src/thesisound/adapters/gemini/tts.py
src/thesisound/services/tts_segmenter.py
src/thesisound/services/audio_qa.py
src/thesisound/services/audio_assembler.py
```

## CLI

```bash
thesisound render-audio <project-id>
thesisound verify-audio <project-id>
```

## کارها

- speaker config؛
- short segment generation؛
- retry؛
- WAV validation؛
- ASR؛
- expected-vs-ASR comparison؛
- FFmpeg concat/normalize.

## Definition of Done

- خروجی ۸ تا ۱۲ دقیقه‌ای؛
- هیچ جمله مهمی نیفتاده؛
- prompt leakage ندارد؛
- تلفظ glossary قابل‌قبول؛
- blind listen قابل‌قبول.

---

# Milestone 6 — Source discovery

## هدف

منابع مکمل معتبر را پیشنهاد بده؛ هنوز UI کامل نساز.

## کد

```text
src/thesisound/ports/search.py
src/thesisound/adapters/openalex.py
src/thesisound/adapters/firecrawl.py
src/thesisound/adapters/crossref.py
src/thesisound/services/query_planner.py
src/thesisound/services/source_normalizer.py
src/thesisound/services/source_triage.py
```

## CLI

```bash
thesisound discover <project-id>
thesisound sources <project-id>
thesisound select-source <project-id> <source-id> --include
```

## Definition of Done

- query family ثبت می‌شود؛
- duplicateها حذف می‌شوند؛
- metadata و full text تفکیک می‌شوند؛
- کاربر corpus را صریح انتخاب می‌کند؛
- max rounds و budget enforce می‌شوند.

---

# Milestone 7 — Multi-source synthesis

## هدف

یک موضوع را با primary، reference و criticism ترکیب کن.

## کارها

- source role-aware claim reconciliation؛
- disagreement representation؛
- coverage audit؛
- gap search؛
- source-aware script attribution.

## Definition of Done

- اختلاف‌ها merge نمی‌شوند؛
- interpretation به primary author نسبت داده نمی‌شود؛
- source diversity به padding تبدیل نمی‌شود؛
- user omissionها را می‌بیند.

---

# Milestone 8 — Local web UI

## هدف

workflow اثبات‌شده را قابل استفاده کن.

## صفحه‌ها

1. Create project؛
2. Upload sources؛
3. Source discovery and selection؛
4. Episode settings؛
5. Progress/artifacts؛
6. Player + transcript + sources.

## پیشنهاد

برای کم‌کردن stack:

- FastAPI؛
- Jinja2/HTMX؛
- Tailwind یا CSS ساده.

Next.js فقط اگر نیاز UI واقعی ایجاد شد. دو stack از ابتدا برای یک ابزار شخصی هزینه اضافی است.

---

# Milestone 9 — Persistence و background jobs

فقط بعد از UI و usage واقعی:

- SQLite repository؛
- job table و worker محلی؛
- resumable stages؛
- cleanup policy؛
- object storage در صورت deploy.

Redis/PostgreSQL فقط اگر concurrency یا deployment آن را لازم کرد.

---

# Task slicing برای pull requestها

هر PR باید یک واحد کوچک باشد:

1. domain model + tests؛
2. parser interface؛
3. one parser adapter؛
4. normalization؛
5. one prompt runner؛
6. one stage service؛
7. one golden fixture؛
8. one quality gate.

PR با عنوان «Implement AI pipeline» قابل review نیست.

# قواعد توسعه

- prompt در code string قرار نگیرد؛
- provider response مستقیم به domain object تبدیل نشود؛ normalize شود؛
- هر stage idempotent باشد؛
- فایل خروجی قبل از state transition نوشته شود؛
- retry دلیل مشخص داشته باشد؛
- log شامل متن کامل copyrighted source نباشد؛
- model name در config؛
- test fixture کوچک و قانونی باشد؛
- هیچ feature قبل از معیار پذیرش ساخته نشود.
