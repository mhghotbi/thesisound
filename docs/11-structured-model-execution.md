# 11 — Structured model execution

این subsystem تمام stageهای مدل‌محور Thesisound را پشت یک contract مشترک قرار می‌دهد. هیچ service نباید مستقیماً SDK گوگل یا provider دیگری را فراخوانی کند.

## هدف

```text
versioned prompt contract
  -> rendered system/user prompts
  -> provider-neutral ModelRunner
  -> Gemini structured output adapter
  -> Pydantic schema validation
  -> deterministic stage validation
  -> bounded retry or explicit failure
  -> auditable model-run artifacts
```

## مرزبندی مسئولیت‌ها

### `TextModelPort`

تنها قرارداد business layer با مدل است. ورودی آن system prompt، user prompt، output type، model id و run metadata است. خروجی آن `StructuredModelResponse[T]` است.

### Gemini adapter

مسئولیت‌ها:

- ساخت درخواست `generate_content`؛
- استفاده از `application/json` و Pydantic response schema؛
- تبدیل پاسخ SDK به مدل داخلی؛
- استخراج token usage، latency و finish reason؛
- تبدیل خطاهای provider به exceptionهای داخلی؛
- تشخیص safety block.

این adapter `temperature`، `top_p` و `top_k` ارسال نمی‌کند. این پارامترها در مدل‌های فعلی Gemini 3.5/3.6 deprecated هستند.

### `ModelRunner`

مسئولیت‌ها:

- بارگذاری prompt contract نسخه‌دار؛
- render متغیرها؛
- محاسبه input hash؛
- اجرای provider؛
- اجرای validator قطعی stage؛
- retry محدود؛
- ثبت artifactها؛
- بازگرداندن خروجی typed.

Runner درباره محتوای Research Brief یا Evidence تصمیم نمی‌گیرد. منطق semantic هر stage در service همان stage قرار دارد.

## Prompt contract

ساختار:

```text
prompts/<prompt-id>/<version>/
  contract.json
  system.md
  user.md
```

نمونه contract:

```json
{
  "id": "research_brief",
  "version": "1.0.0",
  "model_tier": "fast",
  "output_model": "ResearchBrief",
  "max_attempts": 2,
  "retry_schema_errors": true,
  "system_file": "system.md",
  "user_file": "user.md"
}
```

نسخه منتشرشده نباید درجا تغییر معنایی کند. برای تغییر prompt یک directory نسخه جدید بسازید.

`PromptLoader` این موارد را enforce می‌کند:

- contract id با directory برابر باشد؛
- نسخه contract با نام directory برابر باشد؛
- تمام placeholderها مقدار داشته باشند؛
- placeholder حل‌نشده باقی نماند؛
- hash template و contract ثبت شود.

## Retry policy

Retry فقط در شرایط محدود مجاز است:

| خطا | رفتار |
|---|---|
| timeout یا خطای transient provider | backoff محدود |
| rate limit | backoff محدود |
| schema یا deterministic validation | یک repair instruction مشخص |
| safety rejection | بدون retry |
| authentication یا request نامعتبر | بدون retry |
| hallucination تشخیص‌داده‌نشده | retry کور ممنوع |

تعداد attempt از prompt contract می‌آید و حداکثر پنج است.

Repair attempt همان task را نگه می‌دارد و فقط failure دقیق را اضافه می‌کند:

```text
<REPAIR_INSTRUCTION>
The previous response failed the required output contract...
</REPAIR_INSTRUCTION>
```

## Artifactها

```text
workspaces/<project-id>/model-runs/<run-id>/
  request.json
  record.json
  validated-output.json
  error.json                 only on failure
  rendered-prompts.json      opt-in only
```

`request.json` فقط metadata و نام متغیرها را ذخیره می‌کند. مقدار raw ورودی یا متن منبع به‌صورت پیش‌فرض ثبت نمی‌شود.

`record.json` شامل این موارد است:

- prompt id و version؛
- prompt hash و input hash؛
- provider و model؛
- attemptها؛
- token usage؛
- latency؛
- finish reason؛
- خطای نهایی در صورت failure.

## Research Brief stage

فرمان:

```bash
uv run thesisound build-brief <project-id> \
  --audience "social-science graduate student" \
  --prior-knowledge intermediate \
  --duration 25 \
  --modes explanatory,critical \
  --language fa
```

Validation قطعی این stage:

- topic و central question خالی نباشند؛
- ۲ تا ۵ learning objective وجود داشته باشد؛
- objective تکراری نباشد؛
- duration و output language کاربر حفظ شوند؛
- تمام modeهای درخواستی حفظ شوند.

Project state فقط بعد از نوشتن `validated-output.json` به `brief_ready` تغییر می‌کند.

## اضافه‌کردن stage جدید

برای مثال `DocumentMap`:

1. Pydantic output model را در `domain.py` تعریف یا مرور کن.
2. prompt directory نسخه‌دار بساز.
3. service مخصوص stage را ایجاد کن.
4. متغیرهای مجاز prompt را صریح بساز.
5. validator deterministic بنویس.
6. `ModelRunner.run` را فراخوانی کن.
7. artifact stage را پیش از transition پروژه ذخیره کن.
8. fake-provider unit test بنویس.
9. live test را اختیاری و خارج از CI عادی نگه دار.

## تست

Unit testها provider واقعی را صدا نمی‌زنند. Fake provider این موارد را پوشش می‌دهد:

- پاسخ structured معتبر؛
- timeout و backoff؛
- schema/deterministic repair؛
- safety rejection بدون retry؛
- ثبت prompt version؛
- مخفی‌ماندن rendered prompt به‌صورت پیش‌فرض؛
- transition صحیح Research Brief.

برای اجرای کد:

```bash
uv sync --extra dev --extra gemini
uv run ruff check .
uv run pytest
```
