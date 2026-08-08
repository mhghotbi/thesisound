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

## تصمیم سراسری: بودجه تحلیل وابسته به خروجی

Parse، normalization، semantic blockها و locator باید مستقل از مدت خروجی باشند تا artifactها پایدار و قابل استفاده مجدد بمانند. اما evidence extraction نباید همیشه با پوشش و عمق یکسان اجرا شود.

بعد از Document Map، سیستم باید از Research Brief یک `AnalysisProfile` بسازد. این profile حداقل بر اساس این عوامل تعیین می‌شود:

- `target_duration_minutes`؛
- `prior_knowledge`؛
- modeهای explanatory، critical، comparative و debate؛
- اندازه corpus؛
- sectionهای required و میزان ارتباط آن‌ها با سؤال مرکزی.

Profile باید این بودجه‌ها را کنترل کند:

- درصد tokenهای منبع که وارد extraction می‌شوند؛
- سقف token ورودی؛
- حداکثر claim در هر block؛
- context همسایه؛
- استخراج example، objection و response؛
- نیاز احتمالی به second pass.

قاعده اصلی:

```text
full parse + stable blocks + lightweight full map
then output-aware evidence breadth and depth
then late retrieval from original evidence
```

نباید برای یک پادکست ۵ دقیقه‌ای کل کتاب را با همان عمق پادکست ۶۰ دقیقه‌ای استخراج کرد. همچنین نباید block ID و locator با تغییر duration عوض شوند.

طراحی و defaultهای فعلی در [`13-output-aware-analysis-budget.md`](13-output-aware-analysis-budget.md) ثبت شده‌اند.

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

یک فصل واقعی را به evidence و claim ledger تبدیل کن، با عمقی متناسب با خروجی درخواستی.

## کد

```text
src/thesisound/services/block_builder.py
src/thesisound/services/document_mapper.py
src/thesisound/services/analysis_profile.py
src/thesisound/services/evidence_extractor.py
src/thesisound/services/evidence_validator.py
src/thesisound/services/claim_reconciler.py
```

## جریان

```text
Parsed blocks
 -> section grouping
 -> document map
 -> analysis profile
 -> evidence extraction plan
 -> output-aware evidence extraction
 -> excerpt validation
 -> claim reconciliation
```

## نکته

ابتدا فقط یک source. Cross-source synthesis را هنوز نساز.

Block building و Document Map نباید برای durationهای مختلف دوباره با representation متفاوت ساخته شوند. تفاوت هزینه باید در extraction plan اعمال شود.

## Definition of Done

- excerptها با متن match می‌شوند؛
- locator درست است؛
- claim بدون evidence ساخته نمی‌شود؛
- must-cover pointهای fixture پیدا می‌شوند؛
- `evidence-extraction-plan.json` ذخیره می‌شود؛
- blockهای selected و deferred قابل ممیزی‌اند؛
- profile پنج‌دقیقه‌ای token و block کمتری از profile شصت‌دقیقه‌ای مصرف می‌کند؛
- max claims و neighbor context مطابق profile enforce می‌شوند؛
- تغییر duration باعث تغییر block ID یا locator نمی‌شود.

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

## الزام output-aware

Episode planner باید deliberate omissionهای extraction plan را ببیند. برای خروجی کوتاه نباید با padding زمان را پر کند؛ برای خروجی بلند نیز نباید فقط claimهای نسخه کوتاه را تکرار و کش بدهد.

Evidence pack باید از original blockها retrieval کند، نه اینکه صرفاً Claim Ledger را به متن تبدیل کند.

## Definition of Done

- همه turnهای substantive claim ID دارند؛
- unsupported claim ratio صفر؛
- اصطلاح‌های مهم consistency دارند؛
- مجموع duration segmentها با Research Brief سازگار است؛
- deliberate omissionها ثبت می‌شوند؛
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
- source-aware script attribution؛
- تقسیم evidence token budget میان sourceها؛
- جلوگیری از مصرف یکسان روی sourceهای کم‌اهمیت و primary؛
- incremental profile upgrade هنگام افزایش duration.

## Definition of Done

- اختلاف‌ها merge نمی‌شوند؛
- interpretation به primary author نسبت داده نمی‌شود؛
- source diversity به padding تبدیل نمی‌شود؛
- user omissionها را می‌بیند؛
- افزایش duration فقط blockهای deferred و core sectionهای لازم را عمیق‌تر می‌کند؛
- evidence معتبر قبلی بدون نیاز دوباره استفاده می‌شود.

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

## الزام UI

Episode settings باید قبل از evidence extraction نهایی مشخص باشند. UI باید اثر duration و mode بر هزینه و پوشش را نشان دهد و deliberate omissionهای profile کوتاه را قابل مشاهده کند.

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
- object storage در صورت deploy؛
- block-level cache keyed by source hash، block ID، prompt version و analysis depth؛
- reuse افزایشی هنگام ارتقای profile.

Redis/PostgreSQL فقط اگر concurrency یا deployment آن را لازم کرد.

---

# Benchmark اختصاصی بودجه تحلیل

قبل از تثبیت defaultها باید یک benchmark جدا ساخته شود:

```text
same source
  x durations: 5, 15, 30, 60
  x modes: explanatory, critical
  x profile versions
```

Metricها:

- input/output tokens؛
- cost؛
- claim recall روی must-cover fixture؛
- unsupported claim ratio؛
- qualification retention؛
- objection/response retention؛
- human rating برای تناسب عمق با مدت؛
- repetition و padding در سناریو؛
- درصد artifactهای قابل استفاده مجدد پس از تغییر duration.

Coverage targetها فقط بعد از این benchmark باید stable تلقی شوند.

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
- هیچ feature قبل از معیار پذیرش ساخته نشود؛
- duration فقط در script stage مصرف نشود؛ از Research Brief تا extraction plan propagate شود؛
- block representation مستقل از profile بماند؛
- هر تغییر profile باید artifact نسخه‌دار و قابل مقایسه تولید کند.
