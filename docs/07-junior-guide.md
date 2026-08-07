# 07 — راهنمای توسعه برای Junior Developer

این سند فرض می‌کند توسعه‌دهنده Python را در حد پایه می‌داند، اما تجربه ساخت pipeline مدل‌محور ندارد.

## قبل از کدنویسی: مدل ذهنی درست

Thesisound یک تابع بزرگ نیست که فایل را به مدل بدهد و MP3 تحویل بگیرد. یک pipeline مرحله‌ای است که هر مرحله:

1. ورودی مشخص دارد؛
2. artifact خروجی می‌سازد؛
3. خروجی را validate می‌کند؛
4. فقط بعد از pass شدن، state را جلو می‌برد.

هرگز این شکل را نساز:

```python
async def make_podcast(file):
    text = parse(file)
    script = ask_llm(text)
    return tts(script)
```

چون در صورت خطا نمی‌فهمی:

- parse خراب بوده؛
- prompt غلط بوده؛
- مدل بخشی را حذف کرده؛
- TTS متن را نخوانده؛
- retry کدام قسمت لازم است.

---

# ۱. محیط توسعه

## نصب ابزارها

```bash
git clone https://github.com/mhghotbi/thesisound.git
cd thesisound
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev
cp .env.example .env
```

## تست scaffold

```bash
uv run pytest
uv run ruff check .
uv run thesisound init "آرنت و مفهوم کنش"
```

یک directory در `workspaces/` ساخته می‌شود. آن را inspect کن و بفهم هر artifact کجا ذخیره می‌شود.

---

# ۲. چگونه یک feature اضافه کنی

برای هر feature این ترتیب را رعایت کن:

1. domain contract؛
2. port interface؛
3. fake adapter برای test؛
4. service/use case؛
5. artifact output؛
6. quality gate؛
7. real adapter؛
8. CLI command؛
9. integration test.

مستقیم از CLI به Gemini یا Firecrawl call نزن.

---

# ۳. Milestone 1: Document inspection

## هدف

قبل از parse بفهمیم فایل چیست و احتمالاً به کدام parser نیاز دارد.

## فایل بساز

```text
src/thesisound/document_inspection.py
```

## مدل داده

```python
class DocumentInspection(BaseModel):
    path: Path
    mime_type: str
    extension: str
    file_size_bytes: int
    sha256: str
    page_count: int | None
    encrypted: bool
    sampled_text_characters: int
    image_only_ratio: float | None
    likely_complex_layout: bool
    warnings: list[str]
```

## کد deterministic

- SHA-256 فایل؛
- MIME با `python-magic` یا fallback extension؛
- PDF page count با library سبک؛
- sample چند صفحه؛
- نسبت صفحه بدون text؛
- encrypted flag.

## تست

سه fixture کوچک:

- txt/epub؛
- PDF متنی؛
- PDF image-only.

در تست به model یا internet وابسته نباش.

## اشتباه متداول

از filename مثل `scan.pdf` نتیجه نگیر که سند scan است. باید inspection واقعی داشته باشی.

---

# ۴. Milestone 1: Parser port

## فایل

```text
src/thesisound/ports/parser.py
```

## interface

```python
from pathlib import Path
from typing import Protocol

class DocumentParserPort(Protocol):
    name: str

    def supports(self, inspection: DocumentInspection) -> bool: ...

    def parse(self, path: Path) -> ParsedDocument: ...
```

## ParsedDocument

provider JSON را مستقیم نگه ندار. output داخلی:

```python
class ParsedBlock(BaseModel):
    source_block_key: str
    text: str
    page_start: int | None
    page_end: int | None
    heading_path: list[str]
    kind: str

class ParsedDocument(BaseModel):
    parser_name: str
    parser_version: str
    blocks: list[ParsedBlock]
    warnings: list[str]
```

## fake adapter

اول `FakeParser` بساز که fixture JSON بخواند. service و test را با آن کامل کن. بعد Docling adapter را اضافه کن.

---

# ۵. Docling adapter

## فایل

```text
src/thesisound/adapters/parsers/docling_adapter.py
```

## مسئولیت adapter

- Docling را call کند؛
- exception آن را به `ParserError` تبدیل کند؛
- output را به `ParsedDocument` normalize کند؛
- version را ثبت کند؛
- provider object را به بقیه سیستم leak نکند.

## مسئولیت adapter نیست

- chunking معنایی؛
- evidence extraction؛
- انتخاب source؛
- تغییر state؛
- retry بین parserها.

این‌ها در service/orchestrator هستند.

---

# ۶. Parse quality service

## فایل

```text
src/thesisound/services/parse_quality.py
```

## ابتدا heuristic

```python
def evaluate_parse(document: ParsedDocument) -> ParseReport:
    # empty blocks
    # replacement characters
    # repeated lines
    # non-monotonic pages
    # missing locators
    # suspiciously short output
```

## چرا اول LLM نه؟

چون بسیاری از خطاها deterministic و ارزان‌اند. LLM فقط sample مشکل‌دار را بررسی می‌کند.

## خروجی

```python
class ParseReport(BaseModel):
    verdict: Literal["pass", "warning", "retry", "manual_review"]
    issues: list[ParseIssue]
    suggested_parser: str | None
```

---

# ۷. Gemini adapter

## فایل‌ها

```text
src/thesisound/ports/text_model.py
src/thesisound/adapters/gemini/text_model.py
```

## interface

```python
T = TypeVar("T", bound=BaseModel)

class TextModelPort(Protocol):
    def generate_structured(
        self,
        *,
        prompt: str,
        output_type: type[T],
        model: str,
        run_metadata: RunMetadata,
    ) -> T: ...
```

## نکات پیاده‌سازی

- از structured output واقعی provider استفاده کن؛
- JSON را با `model_validate_json` validate کن؛
- timeout داشته باش؛
- error taxonomy بساز؛
- همه exceptionها را catch و ناپدید نکن؛
- full prompt را در production log نکن؛
- prompt version و model را ثبت کن.

## error taxonomy

```python
class ModelError(Exception): ...
class ModelAuthError(ModelError): ...
class ModelRateLimitError(ModelError): ...
class ModelTransientError(ModelError): ...
class ModelSchemaError(ModelError): ...
class ModelSafetyError(ModelError): ...
```

هر error retry policy متفاوت دارد.

---

# ۸. Prompt runner

## چرا prompt فایل جداست؟

برای اینکه:

- بدون تغییر code prompt را review کنیم؛
- version داشته باشد؛
- regression test بزنیم؛
- input/output contract کنار prompt بماند.

## روش اجرا

1. prompt contract را load کن؛
2. template variableها را inject کن؛
3. schema را از domain model بگیر؛
4. model adapter را call کن؛
5. validate؛
6. artifact و run metadata را ذخیره کن؛
7. state را تغییر بده.

## template injection

از `.replace()`های پراکنده استفاده نکن. Jinja2 با strict undefined یا یک renderer کوچک type-safe استفاده کن. اگر variable وجود نداشت، قبل از API call fail کن.

---

# ۹. Evidence extraction

## ورودی درست

یک block تصادفی ۲۰۰۰ توکنی نه. یک section/argument unit با:

- source metadata؛
- heading path؛
- locator؛
- متن؛
- context کوتاه قبل/بعد.

## بعد از output مدل

برای هر evidence:

```python
assert evidence.block_id == input_block.block_id
assert normalized_excerpt in normalized_input_text
assert 0 <= confidence <= 1
```

اگر excerpt match نشد:

1. یک بار از مدل بخواه exact excerpt اصلاح کند؛
2. اگر نشد evidence را reject کن؛
3. هرگز با fuzzy match ضعیف آن را silently قبول نکن.

## parallelization

sectionها مستقل‌اند و بعداً می‌توان parallel کرد. در MVP sequential اجرا کن تا debugging ساده باشد.

---

# ۱۰. Episode plan

## ورودی

فقط claim ledger و brief؛ متن خام کامل لازم نیست.

## چرا؟

Planner باید ساختار و پوشش را تصمیم بگیرد، نه جمله‌پردازی.

## validatorهای لازم

- claim ID وجود دارد؛
- claim در بیش از حد segment تکرار نشده؛
- dependency رعایت شده؛
- مجموع duration نزدیک target است؛
- deliberately omitted ثبت شده.

---

# ۱۱. Evidence pack

## فایل

```text
src/thesisound/services/evidence_pack.py
```

## الگوریتم MVP

```python
for claim_id in segment.claim_ids:
    evidence_items = claim_index[claim_id]
    for item in evidence_items:
        add(original_block[item.block_id])
        if item.needs_context:
            add(previous_block)
            add(next_block)

deduplicate_blocks()
apply_token_budget()
```

اگر budget پر شد، evidence مهم‌تر را براساس direct support و claim priority نگه دار؛ نه براساس طول کوتاه‌تر.

---

# ۱۲. سناریوی فارسی

## نکته معماری

مدل را مجبور نکن ابتدا یک متن انگلیسی کامل بنویسد. ورودی:

- segment plan؛
- evidence pack؛
- glossary؛
- style rules؛
- tail segment قبل.

خروجی:

- speaker؛
- spoken Persian؛
- claim IDs؛
- editorial flag.

## بعد از generation

validator deterministic:

```python
for turn in script.turns:
    if not turn.editorial_only:
        assert turn.claim_ids
    assert all(claim_id in allowed_claim_ids for claim_id in turn.claim_ids)
```

سپس verifier اجرا می‌شود.

---

# ۱۳. Script revision

کل script را برای یک خطا regenerate نکن.

## جریان

1. verifier issue را به turn ID وصل می‌کند؛
2. revision prompt فقط turn معیوب + neighbor turns + evidence مربوط را می‌گیرد؛
3. replacement turn باید claim IDs قبلی را حفظ یا حذف مستدل کند؛
4. دوباره همان turn verify می‌شود.

این کار drift و هزینه را کم می‌کند.

---

# ۱۴. TTS

## TTS adapter

renderer فقط transcript را به audio تبدیل می‌کند. transcript را اصلاح نمی‌کند.

## segment key

```python
segment_hash = sha256(
    transcript
    + voice_a
    + voice_b
    + director_notes
    + model_id
)
```

اگر همان hash قبلاً audio موفق دارد، دوباره API call نزن.

## فایل صوتی

- WAV خام provider؛
- sample rate metadata؛
- duration؛
- retry count؛
- transcript hash.

## FFmpeg

دستورها را با subprocess argument list اجرا کن، نه shell string. return code را چک کن.

---

# ۱۵. Audio QA

## ابتدا technical validation

- فایل وجود دارد؛
- header معتبر؛
- duration > 0؛
- پایان ناگهانی ندارد؛
- clipping شدید نیست.

## سپس ASR

ASR transcript را ذخیره کن. normalization:

- نیم‌فاصله؛
- علائم؛
- اعداد فارسی/لاتین؛
- contractions گفتاری.

بعد missing/repeated content را پیدا کن. semantic model فقط موارد مبهم را بررسی کند.

---

# ۱۶. تست‌نویسی

## unit test

بدون شبکه و مدل:

- validators؛
- state machine؛
- dedup؛
- artifact store؛
- segmentation؛
- source eligibility.

## integration test

با fixture و fake adapter:

```text
input -> brief -> parsed blocks -> evidence -> plan -> script
```

## provider smoke test

با marker جدا:

```bash
pytest -m provider
```

این تست در CI عادی اجرا نشود چون quota و network دارد.

---

# ۱۷. Logging

log خوب:

```text
stage=script_verifier project_id=... attempt=2 verdict=revise issues=1
```

log بد:

```text
Full copyrighted chapter: ...
Full API key: ...
Raw prompt with all source text: ...
```

## هر log باید

- project ID؛
- stage؛
- attempt؛
- duration؛
- artifact ID؛
- error class

داشته باشد.

---

# ۱۸. چه چیزهایی را هنوز نساز

تا vertical slice پاس نشده:

- Next.js؛
- auth؛
- Redis؛
- PostgreSQL؛
- pgvector؛
- Kubernetes؛
- multi-agent framework؛
- LangChain graph پیچیده؛
- scheduler؛
- analytics dashboard.

این‌ها مسئله فعلی را حل نمی‌کنند.

---

# ۱۹. اولین task واقعی

اولین task پیشنهادی:

> یک PDF متنی ۱۰ تا ۲۰ صفحه‌ای را با Docling parse کن، output را به `ParsedDocument` normalize کن، parse report بساز و fixture/test اضافه کن.

نه TTS، نه search، نه UI.

## acceptance criteria

- command مشخص؛
- output JSON؛
- page locator؛
- test؛
- error handling؛
- documentation کوتاه؛
- بدون provider coupling در domain.
