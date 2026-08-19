# 07 — راهنمای کار روی این مخزن

برای کسی که Python را در حد پایه می‌داند ولی تجربهٔ pipeline مدل‌محور ندارد. مسیر M0–M5 پیاده شده است؛ این سند **چگونه در کد موجود کار کنیم** را می‌گوید، نه چگونه از صفر بسازیم.

## مدل ذهنی

Thesisound یک تابع بزرگ نیست که فایل بگیرد و MP3 بدهد. pipeline مرحله‌ای است: هر stage ورودی مشخص دارد، artifact می‌سازد، خروجی را validate می‌کند، و فقط بعد از pass شدن state را جلو می‌برد.

هرگز این شکل را نساز:

```python
async def make_podcast(file):
    text = parse(file)
    script = ask_llm(text)
    return tts(script)
```

چون هنگام خطا نمی‌فهمی parse خراب بوده، prompt غلط بوده، مدل بخشی را حذف کرده، یا TTS متن را نخوانده — و نمی‌دانی کدام قسمت را retry کنی.

## راه‌اندازی

```bash
uv sync --extra dev
cp .env.example .env
uv run pytest
uv run ruff check .
```

تست‌های دارای marker `live` به API واقعی می‌زنند و به‌صورت پیش‌فرض skip می‌شوند.

## نقشهٔ کد

```text
src/thesisound/
├── domain.py          موجودیت‌ها و schemaها — بدون dependency به provider
├── ports.py           Protocolها: TextModel, Search, DocumentParser,
│                      ParserIdentity, Tts, Asr, ArtifactStore
├── adapters/          پیاده‌سازی portها: models/ search/ audio/ parsers/ sms/
├── services/          منطق هر stage (block_builder، document_mapper،
│                      script_verifier، audio_qa، …)
├── pipeline.py        orchestration
├── web/               Jinja + HTMX؛ routes، read_models، runtimeها
├── observability.py   ledger فراخوانی مدل
└── *_cli.py           فرمان‌های CLI
prompts/               promptها به‌صورت فایل نسخه‌دار
workspaces/            artifactهای هر پروژه
```

(سند ۱۰، برنامه‌ریزی‌شده) ماژول‌های جدید کنار همین‌ها: `concepts.py` (سلول/یال/نقشهٔ مفهومی)، `services/concept_map_builder.py`، `services/concept_map_cache.py`، `services/concept_map_overlay.py`، `services/part_packer.py`، `services/segment_skeleton.py`، `services/cost_estimate.py`، `services/lesson_report.py`، `web/concept_routes.py`؛ promptهای `concept_cells`، `concept_cells_consolidate`، `concept_edges`، `persian_lesson_prose` و نسخه‌های جدید promptهای موجود (ضمیمهٔ A در [`10b`](10b-personal-learning-companion-design.md)). قبل از دست زدن به استخراج شواهد یا نویسندهٔ سناریو، `10b` B5 را بخوانید.

## کار از روی 10x (برای ایجنت پیاده‌ساز)

اگر مالک به شما گفته «گام N»، مرجع شما [`10x-agent-runbook.md`](10x-agent-runbook.md) است و این قواعد جای هر دستور دیگری را می‌گیرند:

1. **یک گام، یک نشست.** فقط محدودهٔ همان گام را پیاده کن؛ هرچه بیرون گام لازم شد، در گزارش پایانی بنویس، خودت انجام نده.
2. **اول بخوان، بعد بپرس، بعد بساز.** بخش‌های نام‌برده از `10b`/`10c` را بخوان، پیش‌بررسی گام قبل را اجرا کن، به زبان ساده بگو چه می‌سازی، و تا «شروع کن» نشنیدی کد نزن.
3. **افزایشی و بی‌خطر.** چیزی را حذف نکن مگر گام صریحاً بگوید؛ مسیر `focused_question` را دست نزن مگر گام بگوید (گام ۱ و ۱۳ تنها استثناهای مستند).
4. **prompt = نسخهٔ جدید.** پوشهٔ `prompts/<id>/<version>/` جدید بساز؛ نسخهٔ قبلی immutable است؛ متن را از ضمیمهٔ A کپی کن، بازنویسی نکن.
5. **هر خروجی مدل یک validator قطعی دارد** و از `ModelRunner.run(..., validator=...)` رد می‌شود؛ ID/locator را مدل نمی‌سازد.
6. **تست در ابتدا و انتها.** پیش‌بررسی گام قبلی، سپس تست‌های خود گام، سپس `uv run pytest -q` کامل. تستی را برای سبز شدن شل نکن؛ اگر کهنه است، تغییرش را با دلیل بنویس.
7. **گزارش به زبان محصول، دقیق.** قالب ثابت §۰ در 10x: چه ساختم / چه چیزی عوض نشد / چطور مطمئن شدم / خارج از گام چه دیدم / آمادهٔ commit (بدون اجازه commit نکن).
8. **چک‌پوینت‌ها چیزی نمی‌سازند.** اندازه می‌گیرند، گزارش می‌دهند، پیشنهاد می‌کنند؛ تصمیم با مالک است.
9. **هیچ واژهٔ موضوعی در prompt** (coloniality، dependency، …)، هیچ خواندنی از `research/`.
10. **اگر گام با کد فعلی نمی‌خواند** (مثلاً تابعی که 10c نام برده وجود ندارد یا اسمش فرق دارد)، نزدیک‌ترین معادل را پیدا کن، در گزارش بنویس، و اگر تفاوت معنایی است بپرس — حدس نزن.

## ترتیب افزودن یک feature

domain contract ← port interface ← fake adapter برای تست ← service ← artifact خروجی ← quality gate ← adapter واقعی ← فرمان CLI ← تست integration.

مستقیم از CLI یا route به provider call نزن؛ از port رد شو.

## قواعدی که زیاد نقض می‌شوند

- **از filename نتیجه نگیر.** اینکه فایل `scan.pdf` نام دارد یعنی هیچ؛ inspection واقعی لازم است.
- **adapter فقط تبدیل فرمت است.** chunking معنایی، استخراج شواهد، انتخاب منبع، تغییر state و retry بین parserها کار service است، نه adapter.
- **اول heuristic، بعد مدل.** بیشتر خطاهای parse ارزان و deterministic پیدا می‌شوند؛ مدل فقط sample مشکوک را می‌بیند.
- **prompt فایل جداست و نسخه دارد.** `prompt_version` در هر run ثبت می‌شود تا مقایسه ممکن باشد.
- **کل script را برای یک خطا بازتولید نکن.** verifier هر issue را به turn ID وصل می‌کند؛ revision فقط turn معیوب + همسایه‌ها + شواهد مربوط را می‌گیرد و همان turn دوباره verify می‌شود.
- **TTS renderer حق تغییر transcript ندارد.**
- **FFmpeg را با argument list اجرا کن، نه shell string؛** و return code را چک کن.

## idempotency صوت

```python
segment_hash = sha256(transcript + voice_a + voice_b + director_notes + model_id)
```

اگر همان hash قبلاً audio موفق دارد، دوباره API call نزن.

## خطاهای مدل

هر کلاس retry policy متفاوتی دارد — auth و schema بی‌فایده‌اند، rate limit و transient قابل backoff:

```python
class ModelError(Exception): ...
class ModelAuthError(ModelError): ...
class ModelRateLimitError(ModelError): ...
class ModelTransientError(ModelError): ...
class ModelSchemaError(ModelError): ...
class ModelSafetyError(ModelError): ...
```

## validator بعد از هر خروجی مدل

خروجی schema-bound کافی نیست؛ ارجاع‌ها هم باید بررسی شوند:

```python
for turn in script.turns:
    if not turn.editorial_only:
        assert turn.claim_ids
    assert all(claim_id in allowed_claim_ids for claim_id in turn.claim_ids)
```

همین الگو برای evidence (تطابق excerpt با متن اصلی و locator) و episode plan (وجود claim ID، رعایت dependency، مجموع duration) برقرار است.

## تست

| لایه | بدون شبکه؟ | چه چیزی |
|---|---|---|
| unit | بله | validatorها، state machine، dedup، segmentation، artifact store |
| integration | بله، با fake adapter | مسیر `input → brief → blocks → evidence → plan → script` |
| live | خیر | رفتار provider واقعی؛ با marker `live` جدا و خارج از CI عادی |

## logging

```text
stage=script_verifier project_id=... attempt=2 verdict=revise issues=1
```

هر log باید project ID، stage، attempt، duration، artifact ID و error class داشته باشد. متن کامل منبع، prompt کامل و API key هرگز log نمی‌شوند ([`08-security-privacy-copyright.md`](08-security-privacy-copyright.md)).

## چیزهایی که هنوز لازم نیست

Redis، PostgreSQL، pgvector، Kubernetes، scheduler، framework چندایجنتی، graph پیچیدهٔ orchestration، analytics dashboard. دلیل هر کدام در جدول «تصمیم‌های رد شده» در [`02-architecture.md`](02-architecture.md) است. ترتیب مجاز ارتقا هم همان‌جاست.
