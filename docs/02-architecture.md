# 02 — معماری سیستم

## هدف معماری

معماری باید سه ویژگی داشته باشد:

1. **قابل‌ممیزی:** بتوان از هر جمله مهم در سناریو به شواهد اصلی برگشت؛
2. **قابل‌تعویض:** parser، search provider، مدل متن و TTS بدون بازنویسی domain عوض شوند؛
3. **ساده برای MVP:** یک developer بتواند vertical slice را محلی اجرا و debug کند.

## اصل طراحی

Thesisound یک multi-agent autonomous system نیست. یک **workflow orchestrator** است که چند transform مدل‌محور محدود را میان مراحل deterministic اجرا می‌کند.

```text
Deterministic code -> Model transform -> Schema validation -> Quality gate
```

اگر schema یا gate شکست بخورد، stage retry یا متوقف می‌شود. مرحله بعد نباید روی خروجی ناقص ادامه دهد.

---

## نمای سطح بالا

```text
┌──────────────────────┐
│ 1. Project creation  │
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 2. Research brief    │  model transform + human correction
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 3. Source intake     │  uploads, URLs, metadata
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 4. Source discovery  │  deterministic connectors + query plan
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 5. Human selection   │  mandatory gate
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 6. Corpus build      │  parse, normalize, locate, section
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 7. Evidence build    │  document map + evidence records
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 8. Coverage audit    │  detect material gaps
└──────────┬───────────┘
           v
┌──────────────────────┐
│ 9. Episode plan      │  claim-bound semantic outline
└──────────┬───────────┘
           v
┌──────────────────────┐
│10. Evidence retrieval│  original spans for each segment
└──────────┬───────────┘
           v
┌──────────────────────┐
│11. Persian script    │  direct Persian writing + glossary
└──────────┬───────────┘
           v
┌──────────────────────┐
│12. Script verifier   │  adversarial, original evidence
└──────────┬───────────┘
           v
┌──────────────────────┐
│13. TTS generation    │  short idempotent segments
└──────────┬───────────┘
           v
┌──────────────────────┐
│14. Audio QA          │  ASR + diff + targeted retry
└──────────┬───────────┘
           v
┌──────────────────────┐
│15. Final package     │  audio, transcript, source map
└──────────────────────┘
```

---

## لایه‌ها

### ۱. Domain

هیچ dependency از Gemini، Firecrawl، Docling یا database ندارد.

شامل:

- `Project`
- `ResearchBrief`
- `SourceCandidate`
- `DocumentBlock`
- `EvidenceItem`
- `ClaimRecord`
- `EpisodePlan`
- `Script`
- `VerificationReport`
- state machine

### ۲. Application workflow

Use caseها را اجرا می‌کند:

- build brief؛
- collect sources؛
- build corpus؛
- plan episode؛
- generate script؛
- verify script؛
- render audio.

Application فقط با portها صحبت می‌کند، نه provider concrete.

### ۳. Ports

interfaceهای موردنیاز:

```python
class TextModelPort(Protocol):
    def generate_structured(self, *, prompt: str, schema: type[BaseModel]) -> BaseModel: ...

class SearchPort(Protocol):
    def search(self, query: SearchQuery) -> list[RawSearchResult]: ...

class DocumentParserPort(Protocol):
    def inspect(self, path: Path) -> DocumentInspection: ...
    def parse(self, path: Path, strategy: ParseStrategy) -> ParsedDocument: ...

class TtsPort(Protocol):
    def synthesize(self, segment: TtsSegment) -> AudioArtifact: ...

class AsrPort(Protocol):
    def transcribe(self, audio: Path) -> str: ...

class ArtifactStorePort(Protocol):
    def put_json(self, key: str, value: BaseModel) -> ArtifactRef: ...
    def put_file(self, key: str, path: Path) -> ArtifactRef: ...
```

### ۴. Adapters

- Gemini text adapter؛
- Gemini TTS adapter؛
- OpenAlex adapter؛
- Firecrawl Search/Scrape adapter؛
- Docling parser adapter؛
- MinerU parser adapter؛
- local filesystem artifact store؛
- بعداً SQLite/PostgreSQL repository.

### ۵. Interface

ترتیب پیشنهادی:

1. CLI؛
2. local web UI؛
3. hosted private UI.

---

## Artifact-first workflow

هر stage فایل خروجی versioned تولید می‌کند. مثال:

```text
workspaces/<project-id>/
├── project.json
├── inputs/
│   ├── original/
│   └── hashes.json
├── 01-brief/
│   ├── brief.json
│   └── run.json
├── 02-sources/
│   ├── queries.json
│   ├── candidates.json
│   ├── decisions.json
│   └── selected-manifest.json
├── 03-corpus/
│   ├── <source-id>/parsed.json
│   ├── <source-id>/blocks.jsonl
│   └── parse-report.json
├── 04-evidence/
│   ├── section-cards.jsonl
│   ├── evidence.jsonl
│   ├── claims.json
│   └── coverage.json
├── 05-episode/
│   ├── plan.json
│   ├── glossary.json
│   ├── script-draft.json
│   └── verification.json
├── 06-audio/
│   ├── segments/
│   ├── asr/
│   ├── audio-qa.json
│   └── final.wav
└── manifest.json
```

هر `run.json` حداقل این اطلاعات را نگه می‌دارد:

```json
{
  "stage": "persian_script",
  "prompt_version": "05-persian-script@1",
  "model": "configured-model-id",
  "input_artifact_hashes": [],
  "started_at": "",
  "finished_at": "",
  "attempt": 1,
  "status": "passed",
  "usage": {},
  "warnings": []
}
```

این کار debugging و مقایسه promptها را ممکن می‌کند.

---

## State machine

```text
DRAFT
 -> BRIEF_READY
 -> SOURCES_COLLECTING
 -> SOURCE_SELECTION_REQUIRED
 -> CORPUS_BUILDING
 -> CORPUS_READY
 -> EPISODE_PLANNING
 -> EPISODE_PLANNED
 -> SCRIPT_DRAFTING
 -> SCRIPT_READY
 -> SCRIPT_VERIFYING
 -> SCRIPT_VERIFIED
 -> AUDIO_GENERATING
 -> AUDIO_READY
 -> AUDIO_VERIFYING
 -> COMPLETE
```

هر مرحله می‌تواند به `FAILED_RETRYABLE` یا در خطاهای غیرقابل‌اصلاح به `FAILED_PERMANENT` برود.

تغییر state فقط پس از ثبت artifact معتبر انجام می‌شود.

---

## مرحله ۱: Research brief

### ورودی

- متن خام کاربر؛
- سطح آشنایی؛
- مدت؛
- mode؛
- زبان خروجی.

### خروجی

- normalized topic؛
- central question؛
- objectives؛
- scope؛
- ambiguities؛
- source roles موردنیاز.

### gate

- central question خالی نیست؛
- scope با زمان خروجی سازگار است؛
- ambiguity بحرانی یا با کاربر حل شده یا به‌عنوان فرض ثبت شده است.

---

## مرحله ۲: Source intake و discovery

دو جریان مستقل:

### User sources

فایل یا URL کاربر بدون تغییر نقش و provenance ثبت می‌شود.

### Discovered sources

1. query planner query family می‌سازد؛
2. connectorها metadata/result می‌آورند؛
3. dedup deterministic اجرا می‌شود؛
4. source triage role و limitation را مشخص می‌کند؛
5. کاربر انتخاب می‌کند.

### providerهای MVP

- OpenAlex برای scholarly works؛
- Firecrawl برای web search و scrape؛
- Google Books/Open Library در صورت نیاز به کتاب؛
- Crossref برای DOI validation؛
- Semantic Scholar فقط در milestone بعد برای recommendation/citation graph.

چند provider دانشگاهی مشابه از ابتدا اضافه نمی‌شوند؛ overlap زیاد و debugging سخت می‌شود.

---

## مرحله ۳: Parser routing

### inspect deterministic

قبل از parse:

- MIME و extension؛
- page count؛
- text coverage sample؛
- image-only ratio؛
- احتمال multi-column؛
- file size؛
- encryption؛
- language sample.

### routing

```text
EPUB/DOCX/HTML/simple PDF -> Docling
scanned/complex PDF       -> MinerU
hosted fallback           -> Firecrawl Parse, only with user/provider-upload permission
```

Firecrawl Parse فایل‌های محلی را تا سقف اعلام‌شده provider می‌پذیرد و modeهای `fast`, `auto`, `ocr` دارد. این سرویس fallback است، نه مسیر پیش‌فرض خصوصی.

### parse QA

ابتدا heuristic:

- empty page ratio؛
- replacement characters؛
- repeated headers؛
- reading-order anomalies؛
- heading continuity؛
- page-locator coverage.

فقط اگر heuristic مشکوک بود، sample pageها برای LLM/VLM audit فرستاده می‌شوند.

---

## مرحله ۴: ساخت block و locator

Document parser output به representation داخلی تبدیل می‌شود:

```text
Document -> Chapter -> Section -> Argument unit -> Block
```

block بر اساس تعداد ثابت token ساخته نمی‌شود. ابتدا heading boundary و paragraph relation رعایت می‌شود؛ سپس اگر block بزرگ بود با sentence/paragraph boundary تقسیم می‌شود.

هر block باید:

- source ID؛
- heading path؛
- page/section locator؛
- متن؛
- نوع تقریبی؛
- block قبلی و بعدی

داشته باشد.

---

## مرحله ۵: Evidence model

دو artifact متفاوت تولید می‌شود:

### Section card

برای planning سریع:

- function بخش؛
- key concepts؛
- thesis relation؛
- dependencies؛
- importance؛
- unresolved context.

### Evidence item

برای grounding:

- claim؛
- claim type؛
- exact excerpt؛
- locator؛
- support kind؛
- qualifications؛
- confidence.

Section card هرگز جای evidence item را نمی‌گیرد.

---

## مرحله ۶: Claim ledger و coverage

Claim ledger claimهای هم‌معنا را خوشه‌بندی می‌کند، اما اختلاف‌ها را merge نمی‌کند.

هر claim:

- evidence IDs؛
- claim type؛
- support status؛
- qualifications؛
- agreeing/disagreeing sources

دارد.

Coverage audit central question و subquestionها را به claimها وصل می‌کند و فقط material gapها را اعلام می‌کند.

اگر gap مهم باشد، user انتخاب می‌کند:

- با همین corpus ادامه بده؛
- search round جدید اجرا کن؛
- scope را محدود کن.

---

## مرحله ۷: Episode plan

Episode plan یک prose summary نیست. یک semantic execution plan است:

- listener outcome؛
- segment order؛
- claim IDs؛
- key question؛
- speaker dynamic؛
- duration budget؛
- deliberate omissions.

مجموع زمان segmentها باید با target duration هم‌خوان باشد.

---

## مرحله ۸: Evidence retrieval

برای هر segment:

1. claim IDs دریافت می‌شوند؛
2. evidence items مرتبط پیدا می‌شوند؛
3. block اصلی و همسایه‌های لازم بازیابی می‌شوند؛
4. duplicate excerpt حذف می‌شود؛
5. evidence pack با سقف token ساخته می‌شود.

MVP از mapping و SQLite FTS5 استفاده می‌کند. embedding فقط اگر benchmark نشان دهد recall پایین است اضافه می‌شود.

---

## مرحله ۹: Persian script

مسیر اصلی:

```text
Episode plan + evidence pack + glossary -> Persian script
```

نه:

```text
English polished script -> Persian translation
```

Script writer:

- فقط claimهای segment را استفاده می‌کند؛
- برای هر turn claim ID ثبت می‌کند؛
- اختلاف‌ها و uncertainty را حفظ می‌کند؛
- editorial analogy را علامت می‌زند؛
- filler و fake banter تولید نمی‌کند.

---

## مرحله ۱۰: Verification

دو نوع check:

### deterministic

- تمام turnهای substantive claim ID دارند؛
- claim ID در ledger موجود است؛
- segment از claim خارج از plan استفاده نکرده؛
- duration/word budget رعایت شده؛
- glossary term consistency.

### model-assisted adversarial

- unsupported meaning؛
- attribution اشتباه؛
- certainty shift؛
- حذف qualification؛
- ادغام غلط اختلاف‌ها؛
- invented example.

هر issue blocking باعث برگشت فقط segment معیوب به writer می‌شود.

---

## مرحله ۱۱: TTS

Transcript به segmentهای چنددقیقه‌ای تقسیم می‌شود. مستندات رسمی Gemini TTS درباره drift در خروجی طولانی، voice inconsistency و خطاهای occasional هشدار می‌دهند؛ بنابراین یک اپیزود بلند در یک درخواست ارسال نمی‌شود.

هر TTS segment:

- hash از transcript و voice settings؛
- attempt count؛
- output path؛
- duration؛
- provider metadata

دارد.

Retry فقط برای خطای transient یا QA failure اجرا می‌شود.

---

## مرحله ۱۲: Audio QA

1. audio segment transcribe می‌شود؛
2. expected و ASR text normalize می‌شوند؛
3. missing/repeated/truncated content deterministic پیدا می‌شود؛
4. semantic mismatchهای مبهم با مدل بررسی می‌شوند؛
5. فقط segment معیوب regenerate می‌شود؛
6. FFmpeg loudness normalization و concatenation را انجام می‌دهد.

---

## Provider configuration

نام مدل‌ها در `.env` است. startup باید capability smoke test اجرا کند:

- structured output برای مدل متن؛
- audio output برای TTS؛
- یک درخواست کوتاه فارسی؛
- provider quota/error visibility.

مدل فعلی فقط default است، نه dependency دامنه.

---

## مسیر ارتقا بعد از MVP

فقط اگر محدودیت واقعی دیده شد:

1. SQLite repository؛
2. local web UI؛
3. background worker؛
4. object storage؛
5. PostgreSQL؛
6. embedding/vector retrieval؛
7. multi-user auth.

ترتیب معکوس، پروژه را قبل از اثبات کیفیت به زیرساخت تبدیل می‌کند.

---

## منابع رسمی تصمیم‌ها

- [Docling](https://github.com/docling-project/docling)
- [MinerU](https://github.com/opendatalab/MinerU)
- [Microsoft MarkItDown](https://github.com/microsoft/markitdown)
- [Firecrawl Parse](https://docs.firecrawl.dev/features/parse)
- [Firecrawl Search](https://docs.firecrawl.dev/api-reference/endpoint/search)
- [OpenAlex Search](https://developers.openalex.org/guides/searching)
- [Semantic Scholar APIs](https://api.semanticscholar.org/api-docs/)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini TTS](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Gemini models](https://ai.google.dev/api/models)
