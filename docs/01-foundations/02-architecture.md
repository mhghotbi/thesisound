# 02 — معماری سیستم

مرتبط: قرارداد اجرای هر stage در [`03-agent-workflow.md`](03-agent-workflow.md)، استراتژی parser/منبع در [`04-document-and-source-strategy.md`](04-document-and-source-strategy.md)، gateهای کیفیت در [`05-quality-evaluation.md`](05-quality-evaluation.md).

این سند **شکل سیستم** را می‌گوید: لایه‌ها، portها، artifactها و state machine. رفتار تک‌تک stageها اینجا تکرار نمی‌شود؛ قرارداد هر stage در [`03-agent-workflow.md`](03-agent-workflow.md) و جزئیات پیاده‌سازی در [`../02-pipeline/`](../02-pipeline/) است.

## هدف معماری

1. **قابل‌ممیزی:** بتوان از هر جمله مهم در سناریو به شواهد اصلی برگشت؛
2. **قابل‌تعویض:** parser، search provider، مدل متن و TTS بدون بازنویسی domain عوض شوند؛
3. **ساده برای MVP:** یک developer بتواند vertical slice را محلی اجرا و debug کند.

## اصل طراحی

Thesisound یک multi-agent autonomous system نیست. یک **workflow orchestrator** است که چند transform مدل‌محور محدود را میان مراحل deterministic اجرا می‌کند.

```text
Deterministic code -> Model transform -> Schema validation -> Quality gate
```

اگر schema یا gate شکست بخورد، stage retry یا متوقف می‌شود. مرحله بعد نباید روی خروجی ناقص ادامه دهد.

## نمای کلی pipeline

| # | مرحله | نوع |
|---:|---|---|
| ۱ | Project creation | deterministic |
| ۲ | Research brief | model transform + human correction |
| ۳ | Source intake | uploads، URL، metadata |
| ۴ | Source discovery | query plan + connector |
| ۵ | Human selection | **gate اجباری** |
| ۶ | Corpus build | parse، normalize، locate، section |
| ۷ | Evidence build | document map + evidence records |
| ۸ | Coverage audit | تشخیص gap مادی |
| ۹ | Episode plan | outline معنایی claim-bound |
| ۱۰ | Evidence retrieval | original spans هر segment |
| ۱۱ | Persian script | نگارش مستقیم فارسی + glossary |
| ۱۲ | Script verifier | adversarial روی شواهد اصلی |
| ۱۳ | TTS generation | segment کوتاه idempotent |
| ۱۴ | Audio QA | ASR + diff + retry هدفمند |
| ۱۵ | Final package | audio، transcript، source map |

برای نیت `source_coverage` (برنامه‌ریزی‌شده، سند ۱۰ §6) بین ۶ و ۷ سه مرحله اضافه می‌شود — تشخیص فصل (deterministic)، سلول‌های مفهومی و یال‌ها (model transform + gate)، و پس از ۸ بسته‌بند بخش‌ها (deterministic)؛ مراحل ۹ تا ۱۴ برای هر بخش تکرار می‌شوند؛ ۱۱ می‌تواند به‌جای گفت‌وگو درس متنی بسازد.

## لایه‌ها

### ۱. Domain

هیچ dependency از provider، parser یا database ندارد. شامل `Project`، `ResearchBrief`، `SourceCandidate`، `DocumentBlock`، `EvidenceItem`، `ClaimRecord`، `EpisodePlan`، `Script`، `VerificationReport` و state machine.

### ۲. Application workflow

use caseها: build brief، collect sources، build corpus، plan episode، generate script، verify script، render audio. Application فقط با portها صحبت می‌کند، نه provider concrete.

### ۳. Ports

```python
class TextModelPort(Protocol):
    def generate_structured(self, *, prompt: str, schema: type[BaseModel]) -> BaseModel: ...

class SearchPort(Protocol):
    def search(self, query: SearchQuery) -> list[RawSearchResult]: ...

class DocumentParserPort(Protocol):
    def inspect(self, path: Path) -> DocumentInspection: ...
    def parse(self, path: Path, strategy: ParseStrategy) -> ParsedDocument: ...

class ParserIdentityPort(Protocol):  # هویت پایدار parser برای کلید کش parse
    ...

class TtsPort(Protocol):
    def synthesize(self, segment: TtsSegment) -> AudioArtifact: ...

class AsrPort(Protocol):
    def transcribe(self, audio: Path) -> str: ...

class ArtifactStorePort(Protocol):
    def put_json(self, key: str, value: BaseModel) -> ArtifactRef: ...
    def put_file(self, key: str, path: Path) -> ArtifactRef: ...
```

### ۴. Adapters پیاده‌شده

| نقش | پیاده‌سازی | مسیر |
|---|---|---|
| مدل متن | Gemini، Okian | `adapters/models/` |
| جست‌وجوی وب | Gemini Google Search grounding | `adapters/search/gemini.py` |
| TTS/ASR | Gemini | `adapters/audio/gemini.py` |
| parser | Docling، MinerU، EPUB، OCR محلی، native | `adapters/parsers/` |
| SMS (OTP) | Kavenegar | `adapters/sms/` |
| artifact store | filesystem محلی | `workspaces/` |

مسیریابی مدل بر اساس stage در [`../04-integrations/06-okian-provider-and-model-routing.md`](../04-integrations/06-okian-provider-and-model-routing.md). سیاست ابزار وب و مرز evidence در [`../04-integrations/01-gemini-grounding.md`](../04-integrations/01-gemini-grounding.md).

> **هیچ connector کتاب‌شناختی مستقلی پیاده نشده.** OpenAlex، Crossref، Google Books و Semantic Scholar فقط به‌عنوان مقدار `SearchQuery.provider` در `domain.py` رزرو شده‌اند؛ کلیدهایشان به‌همراه Firecrawl از تنظیمات فعال حذف شده است. تنها مسیر اجراشوندهٔ جست‌وجو امروز Gemini است.

### ۵. Interface

CLI ← اکنون · web UI محلی ← اکنون · hosted private UI ← بعداً.

## Artifact-first workflow

هر stage فایل خروجی versioned تولید می‌کند:

```text
workspaces/<project-id>/
├── project.json
├── inputs/{original,hashes.json}
├── 01-brief/{brief.json,run.json}
├── 02-sources/{queries,candidates,decisions,selected-manifest}.json
├── 03-corpus/<source-id>/{parsed.json,blocks.jsonl} + parse-report.json
├── 04-evidence/{section-cards.jsonl,evidence.jsonl,claims.json,coverage.json}
├── 05-episode/{plan,glossary,script-draft,verification}.json
├── 06-audio/{segments/,asr/,audio-qa.json,final.wav}
└── manifest.json
```

هر `run.json` حداقل این‌ها را نگه می‌دارد — بدون آن‌ها بهبود prompt بر اساس حدس است:

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

## State machine

```text
DRAFT → BRIEF_READY → SOURCES_COLLECTING → SOURCE_SELECTION_REQUIRED
      → CORPUS_BUILDING → CORPUS_READY → EPISODE_PLANNING → EPISODE_PLANNED
      → SCRIPT_DRAFTING → SCRIPT_READY → SCRIPT_VERIFYING → SCRIPT_VERIFIED
      → AUDIO_GENERATING → AUDIO_READY → AUDIO_VERIFYING → COMPLETE
```

هر مرحله می‌تواند به `FAILED_RETRYABLE` یا در خطای غیرقابل‌اصلاح به `FAILED_PERMANENT` برود. **تغییر state فقط پس از ثبت artifact معتبر انجام می‌شود.**

## تغییرات معماری برنامه‌ریزی‌شده (سند ۱۰، بازنگری ۳.۱ — ۲۰۲۶-۰۸-۱۹)

اصل طراحی، لایه‌ها، portها و artifact-first بودن **تغییر نمی‌کنند**. آنچه اضافه می‌شود لایه‌ای بالای خط شواهد است و همهٔ تغییرات افزایشی‌اند؛ هیچ stage حذف یا دور زده نمی‌شود. فهرست دقیق در [`10-personal-learning-companion-development-plan.md`](10-personal-learning-companion-development-plan.md) §5، §6 و §9.

| چه چیزی | نوع تغییر | کجا |
|---|---|---|
| **Domain:** `ConceptCell`، `ConceptEdge`، `SourceConceptMap`، `ConceptMapOverlay`، `SourceChapter`، `LessonPart`؛ `Project` با میدان‌های اختیاری `lesson_intent`، `delivery`، `compression`، `episode_target_minutes`، `scope`، `known_concepts`؛ `ResearchBrief.cell_keys`؛ `EpisodePlan.parts` و `EpisodeSegment.part_index` | افزایشی | `src/thesisound/concepts.py` (ماژول جدید)، `domain.py` |
| **Domain:** استخراج ۲.۰ — همهٔ اقلام شواهد (تعریف، تمایز، مثال، اعتراض، پاسخ) claim با excerpt هستند؛ `ClaimType` گسترش می‌یابد؛ `must_not_be_lost` روی claim؛ `ClaimRecord` در evidence pack | **تغییر schema با migration در مسیر خواندن** — تنها تغییر غیرافزایشیِ واقعی | `source_analysis.py`, `domain.py`, `episode.py`, `evidence_artifact_migration.py` |
| **Stageهای جدید (مدل‌محور، bounded):** سلول‌های مفهومی هر فصل، consolidate، یال‌ها، درس متنی (prose) | همان الگوی `Deterministic code → Model transform → Schema validation → Quality gate` | `services/concept_map_builder.py`، prompts جدید |
| **Stageهای جدید (قطعی):** تشخیص فصل، اعتبارسنجی ریزدانگی/دور/یتیم، بسته‌بند بخش‌ها، گزارش پایانی | بدون فراخوانی مدل | `services/part_packer.py`، `services/lesson_report.py` |
| **Document map:** partition = فصل به‌جای بودجهٔ ۲۵۰k کاراکتر | تغییر رفتار سرویس، بدون تغییر قرارداد | `services/document_mapper.py` |
| **State machine:** بدون state جدید؛ مراحل plan/script/audio درون خود **روی بخش‌ها حلقه می‌زنند**؛ یک گذار افزایشی `SCRIPT_VERIFIED → COMPLETE` برای `delivery == text` | افزایشی | `pipeline.py`، سرویس‌های build |
| **Artifactها:** `_shared/concept-maps/<sha>.json` (کش)، `sources/<sid>/concept-map-overlay.json`، `script/parts/<n>/`، `audio/parts/<n>/`، `episode/report.json`؛ checkpoint فصلی هنگام ساخت نقشه | افزایشی | `workspaces/` |
| **Observability:** stageهای جدید با همان `ModelCallSpec` (`concept_cells`, `concept_edges`, `lesson_prose`)، stage فراخوانی اسکریپت با `part_index` | افزایشی | `observability.py` |
| **Web:** صفحات نقشهٔ مفهومی، فهرست بخش‌ها، گزارش؛ گزینه‌های ساخت پروژه؛ بعداً نمای گراف 2D (کتابخانهٔ vendored، بدون CDN) | افزایشی، همان Jinja + HTMX | `web/concept_routes.py` |

**چیزهایی که عمداً عوض نمی‌شوند:** یک process و فایل‌سیستم (صف کار و DB خارجی همچنان رد است)؛ بدون embedding؛ بدون لایهٔ بین‌پروژه‌ای؛ auth و project isolation؛ مسیر `focused_question` به‌جز re-baseline یک‌بارهٔ استخراج ۲.۰.

**ریسک معماری واقعی فقط یکی است:** migration استخراج ۲.۰ — artifactهای قدیمی باید در مسیر خواندن بالا بیایند و پروژه‌های قدیمی با نسخهٔ prompt خودشان reproducible بمانند (الگوی `evidence_artifact_migration.py` و `07-specs/01`). بقیه افزودن ماژول کنار ماژول‌های موجود است.

## Provider configuration

نام مدل‌ها در `.env` است، نه در کد. startup باید capability smoke test اجرا کند: structured output برای مدل متن، audio output برای TTS، یک درخواست کوتاه فارسی، و visibility خطا/quota. مدل فعلی فقط default است، نه dependency دامنه.

## تصمیم‌های رد شده و دلیل

این جدول جای‌گزین سند «نقد نسخه اولیه معماری» است. هدفش جلوگیری از پیشنهاد دوبارهٔ همین مسیرهاست.

| رد شد | انتخاب شد | چرا |
|---|---|---|
| PostgreSQL + pgvector + Redis + worker جدا از روز اول | فایل و JSON روی دیسک، SQLite، یک process | ریسک اصلی پروژه مقیاس نیست؛ کیفیت استخراج، وفاداری به متن و طبیعی‌بودن فارسی است |
| pgvector برای MVP | claim-to-block mapping + SQLite FTS5 + neighbor expansion | corpus یک کاربر آن‌قدر بزرگ نیست؛ embedding فقط اگر benchmark recall ناکافی نشان دهد |
| یک parser میزبانی‌شده به‌عنوان مسیر اصلی | Docling پیش‌فرض، MinerU برای scan و layout پیچیده | انتخاب parser باید با benchmark روی corpus خود پروژه باشد، نه شهرت مخزن |
| زنجیرهٔ «خلاصهٔ محلی → خلاصهٔ سراسری» | section card + evidence record؛ writer و verifier به متن اصلی برمی‌گردند | خلاصهٔ میانی index است نه source of truth؛ حذف یک قید در مرحلهٔ اول دیگر جبران نمی‌شود |
| agentهای آزاد با مرز مسئولیت مبهم | سه نوع stage: deterministic / bounded model transform / human gate | هر جا مدل آزادانه تصمیم بگیرد فضای خطا بزرگ‌تر می‌شود |
| `authority_score` عددی برای منبع | role + access level + authority class + limitations | نمرهٔ عددی دقت جعلی می‌سازد؛ اعتبار منبع تابع claim است نه صفت ثابت آن |
| metadata و abstract به‌عنوان شواهد | `SourceAccess`؛ فقط full-text انتخاب‌شده evidence می‌سازد | metadata برای کشف منبع خوب است، برای نسبت‌دادن جزئیات به متن کامل نه |
| جست‌وجوی «دقیق و مفصل» بدون حد توقف | حداکثر ۳ round با stop condition صریح | بدون حد توقف، نتیجه منبع بیشتر و کیفیت کمتر است |
| سناریوی انگلیسی صیقل‌خورده → ترجمهٔ فارسی | plan معنایی + glossary → نگارش مستقیم فارسی | ترجمهٔ دومرحله‌ای attribution، certainty و اصطلاح را جابه‌جا می‌کند |
| TTS به‌عنوان آخرین مرحلهٔ ساده | segment کوتاه + idempotency key + ASR verify + بازتولید فقط segment معیوب | خروجی طولانی drift، voice inconsistency و خطای موقت دارد |
| model name داخل کد | فقط در config + capability check هنگام startup + fallback | مدل‌ها و aliasها سریع عوض می‌شوند و preview shut down می‌شود |

سیاست privacy، حق نشر و data handling در [`08-security-privacy-copyright.md`](08-security-privacy-copyright.md).

## مسیر ارتقا بعد از MVP

فقط اگر محدودیت واقعی دیده شد، به همین ترتیب: SQLite repository ← web UI محلی ← background worker ← object storage ← PostgreSQL ← embedding/vector retrieval ← multi-user auth.

ترتیب معکوس، پروژه را قبل از اثبات کیفیت به زیرساخت تبدیل می‌کند.

## منابع رسمی تصمیم‌ها

- [Docling](https://github.com/docling-project/docling) · [MinerU](https://github.com/opendatalab/MinerU)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output) · [Gemini TTS](https://ai.google.dev/gemini-api/docs/speech-generation) · [Gemini models](https://ai.google.dev/api/models)
