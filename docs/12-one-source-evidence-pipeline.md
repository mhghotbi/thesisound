# 12 — One-source evidence pipeline

این subsystem یک منبع parse‌شده را به Claim Ledger قابل‌ممیزی تبدیل می‌کند. هدف آن «خلاصه‌سازی سند» نیست؛ هدف ساختن یک لایه شواهد است که مراحل بعدی مانند episode planning و script writing بتوانند دوباره به متن اصلی برگردند.

## جریان کامل

```text
IngestionResult
  -> Semantic Block Builder
  -> Document Map
  -> Block-scoped Evidence Extraction
  -> Deterministic Evidence Validation
  -> Claim Reconciliation
  -> Claim Ledger
```

این pipeline فقط ingestionهایی را می‌پذیرد که `safe_for_claim_extraction=true` دارند و پروژه باید پیش‌تر Research Brief معتبر داشته باشد.

## اصل اعتماد

Source of truth همیشه متن block و locator آن است.

مدل اجازه ندارد این شناسه‌ها را بسازد:

- `source_id`
- `block_id`
- page locator
- `evidence_id`
- `claim_id`

این مقادیر بعد از پاسخ مدل و به‌صورت deterministic ساخته می‌شوند. در نتیجه یک پاسخ ظاهراً معتبر نمی‌تواند شواهد را به صفحه یا منبع جعلی متصل کند.

---

## ۱. Semantic Block Builder

فایل اصلی:

```text
src/thesisound/services/block_builder.py
```

ورودی:

```text
ParsedDocument
```

خروجی:

```text
list[SourceDocumentBlock]
BlockBuildReport
```

### کارهایی که انجام می‌دهد

1. header و footer صریح را حذف می‌کند.
2. متن کوتاه تکرارشونده را فقط وقتی حذف می‌کند که روی حداقل سه صفحه دیده شده باشد.
3. heading را به‌عنوان context نگه می‌دارد، نه evidence مستقل.
4. جدول، فرمول و code را block مستقل نگه می‌دارد.
5. paragraphهای هم‌مسیر و دارای heading یکسان را تا سقف token budget ادغام می‌کند.
6. blockهای بسیار بزرگ را ابتدا روی مرز paragraph و sentence می‌شکند.
7. برای هر block رابطه قبلی و بعدی، source block keyها و locator را حفظ می‌کند.

### چرا token count تخمینی است؟

Block builder نباید به tokenizer یک provider وابسته شود. `estimate_tokens` فقط برای کنترل اندازه chunk است. مصرف واقعی API از metadata خود provider ثبت می‌شود.

### چیزی که نباید انجام دهد

- تشخیص معنای استدلال با LLM؛
- حذف متن به دلیل «کم‌اهمیت» بودن؛
- تبدیل heading به claim؛
- ادغام table یا formula با prose اطراف؛
- حذف تکرار صرفاً بر اساس شباهت دو block.

---

## ۲. Document Map

فایل‌ها:

```text
src/thesisound/services/document_mapper.py
prompts/document_map/1.0.0/
```

مدل blockها را به sectionهای استدلالی تقسیم می‌کند و function هر section را مشخص می‌کند:

```text
front_matter
 definition
 argument
 example
 objection
 response
 transition
 conclusion
 other
```

### Quality gate قطعی

- section IDها یکتا باشند؛
- هر block فقط در یک section باشد؛
- هیچ block ناشناخته‌ای ارجاع نشود؛
- dependency و cross-section thread فقط به section موجود اشاره کنند؛
- حداقل ۹۰ درصد blockهای غیر-front-matter پوشش داده شوند.

اگر مدل یک block را حذف کند یا ID بسازد، stage با repair محدود دوباره اجرا می‌شود. خروجی ناقص پذیرفته نمی‌شود.

### محدودیت vertical slice

در این نسخه، Document Map برای یک فصل یا سند محدود طراحی شده است. اگر مجموع متن از budget پیکربندی‌شده بزرگ‌تر باشد، stage متوقف می‌شود. راه درست برای کتاب کامل، نقشه سلسله‌مراتبی chapter-level است؛ نه ارسال بی‌قید کل کتاب.

---

## ۳. Evidence Extraction

فایل‌ها:

```text
src/thesisound/services/evidence_extractor.py
prompts/evidence_extraction/1.0.0/
```

هر semantic block در یک model run مستقل تحلیل می‌شود. ورودی محدود است به:

- متن همان block؛
- heading و locator؛
- context کوتاه section؛
- working thesis سند.

مدل خروجی draft می‌دهد:

- claimها؛
- supporting excerpt؛
- definitionها؛
- distinctionها؛
- exampleها؛
- objection و response؛
- qualification؛
- unresolved context؛
- `must_not_be_lost`.

مدل ID یا locator تولید نمی‌کند. application پس از validation آن‌ها را می‌سازد.

### Persistence مرحله‌ای

خروجی هر block بلافاصله نوشته می‌شود:

```text
sources/<source-id>/evidence/extractions/<block-id>.json
```

اگر پردازش block دهم شکست بخورد، خروجی ۹ block قبلی برای debugging باقی می‌ماند. نسخه فعلی هنوز resume خودکار از همان block را انجام نمی‌دهد، اما artifact لازم برای آن را حفظ می‌کند.

---

## ۴. Evidence Validation

فایل:

```text
src/thesisound/services/evidence_validator.py
```

این gate مدل زبانی نیست.

برای هر evidence item بررسی می‌شود:

- `source_id` با block برابر است؛
- `block_id` با block برابر است؛
- supporting excerpt پس از normalize کردن whitespace عیناً در block وجود دارد؛
- excerpt برای audit بیش از حد کوتاه نیست؛
- locator خارج از محدوده block نیست؛
- evidence ID در کل source یکتا است؛
- برای هر block حداکثر یک extraction record وجود دارد؛
- extractionهای بدون claim نیز block origin خود را حفظ می‌کنند.

این طراحی عمداً paraphrase را به‌عنوان excerpt نمی‌پذیرد. claim می‌تواند paraphrase دقیق باشد، اما supporting excerpt باید قطعه‌ای از متن اصلی باشد.

---

## ۵. Claim Reconciliation

فایل‌ها:

```text
src/thesisound/services/claim_reconciler.py
prompts/claim_reconciliation/1.0.0/
```

Evidence itemهای یک source ممکن است تکراری یا مکمل باشند. این stage آن‌ها را به claimهای canonical تبدیل می‌کند.

### قواعد

- claimهای هم‌معنا فقط با attribution، scope و certainty سازگار ادغام می‌شوند؛
- objection با response ادغام نمی‌شود؛
- criticism به author position تبدیل نمی‌شود؛
- qualificationهای material حفظ می‌شوند؛
- evidence ID ناشناخته رد می‌شود؛
- هر evidence ID باید یا در یک claim استفاده شود یا در `unresolved_evidence_ids` قرار گیرد؛
- evidence نمی‌تواند هم مصرف‌شده و هم unresolved باشد؛
- claim ID از متن claim و evidence IDها به‌صورت deterministic ساخته می‌شود.

خروجی نهایی:

```text
ClaimLedger
```

این نسخه one-source است. disagreement واقعی میان چند source در مرحله cross-source reconciliation بعدی اضافه می‌شود.

---

## ۶. Artifact و orchestration

فایل‌ها:

```text
src/thesisound/services/source_artifact_store.py
src/thesisound/services/source_analysis_service.py
src/thesisound/source_cli.py
```

### ساختار workspace

```text
workspaces/<project-id>/
  project.json
  model-runs/<run-id>/
    request.json
    record.json
    validated-output.json
  sources/<source-id>/
    manifest.json
    ingestion-result.json
    parsed-document.json
    block-build-report.json
    document-blocks.jsonl
    document-map.json
    evidence/
      extractions/<block-id>.json
    evidence-extractions.jsonl
    evidence-items.jsonl
    claim-ledger.json
```

### State transition

شروع معتبر:

```text
brief_ready
```

ورود source به‌صورت صریح این مسیر را طی می‌کند:

```text
brief_ready
  -> sources_collecting
  -> source_selection_required
  -> corpus_building
  -> corpus_ready
```

برای منبع آپلودشده توسط کاربر، source به‌صورت `full_text` و `include` ثبت می‌شود، چون خود کاربر آن را صریحاً وارد کرده است. منابع کشف‌شده از وب بعداً به human selection gate واقعی می‌روند.

در failure:

- project به `failed_retryable` می‌رود؛
- `last_error` ثبت می‌شود؛
- source manifest در صورت وجود `failed` می‌شود؛
- artifactهای موفق قبلی حذف نمی‌شوند.

---

## CLI

### فقط block building، بدون API key

```bash
uv run thesisound build-blocks \
  <project-id> \
  parse-result.json
```

خروجی source ID می‌دهد. سه stage بعدی را می‌توان جدا اجرا کرد:

```bash
uv run thesisound map-document <project-id> <source-id>
uv run thesisound extract-evidence <project-id> <source-id>
uv run thesisound build-claims <project-id> <source-id>
```

یا کل مسیر مدل‌محور:

```bash
uv run thesisound analyze-source \
  <project-id> \
  parse-result.json
```

`map-document` و `extract-evidence` از fast model استفاده می‌کنند. `build-claims` از strong model استفاده می‌کند. هر مدل را می‌توان از CLI override کرد.

---

## اجرای کامل بعد از قراردادن API key

```bash
uv sync --extra dev --extra gemini --extra parsers
cp .env.example .env
```

سپس:

```bash
uv run thesisound init "آرنت و مفهوم کنش"

uv run thesisound build-brief <project-id> \
  --audience "social-science graduate student" \
  --prior-knowledge intermediate \
  --duration 25 \
  --modes explanatory,critical

uv run thesisound parse chapter.pdf \
  --parser auto \
  --output parse-result.json

uv run thesisound analyze-source \
  <project-id> \
  parse-result.json
```

در پایان project باید `corpus_ready` و source manifest باید `claims_ready` باشد.

---

## تست و Definition of Done

```bash
uv run ruff check .
uv run pytest
```

تست‌ها بدون API خارجی این موارد را پوشش می‌دهند:

- حذف margin صریح؛
- حفظ heading، locator و source block keys؛
- ساخت Document Map با block coverage؛
- رد supporting excerpt ساختگی؛
- ساخت deterministic evidence و claim IDs؛
- اجرای end-to-end با fake structured model؛
- نوشتن تمام artifactهای اصلی؛
- transition نهایی پروژه به `corpus_ready`.

## محدودیت صادقانه فعلی

این کد با fake structured model در CI اجرا می‌شود؛ چون API key در CI قرار ندارد. بنابراین correctness قراردادها، persistence، validation و orchestration اثبات شده، اما کیفیت semantic خروجی Gemini باید بعداً روی یک فصل خوانده‌شده و یک corpus واقعی ارزیابی شود.
