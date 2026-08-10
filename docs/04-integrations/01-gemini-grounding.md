# 01 — Gemini Google Search و URL Context

مرتبط: مکانیزم کشف منبع مبتنی بر همین گراندینگ در [`02-source-discovery-large-docs-and-revision.md`](02-source-discovery-large-docs-and-revision.md)؛ key rotation و failover در ledger مشترک [`05-model-observability.md`](05-model-observability.md) ثبت می‌شود.

## وضعیت

Thesisound برای قابلیت‌های وب فعلاً فقط از ابزارهای داخلی Gemini استفاده می‌کند:

- Google Search Grounding برای کشف اطلاعات و منابع جدید؛
- URL Context برای خواندن URL عمومی مشخص؛
- Gemini key pool برای failover روی خطاهای quota/rate limit.

کلیدهای Firecrawl، OpenAlex و Semantic Scholar از تنظیمات فعال حذف شده‌اند.

## سیاست stageها

ابزار وب به‌صورت سراسری و کور روی همه درخواست‌ها روشن نیست. policy فعلی:

| Stage | Google Search | URL Context |
|---|---:|---:|
| `research_brief` | بله | فقط با URL صریح |
| `query_planner` | بله | خیر |
| `source_discovery` | بله | فقط با URL صریح |
| `source_triage` | خیر | فقط با URL صریح |
| `glossary` | بله | خیر |
| document map | خیر | خیر |
| evidence extraction | خیر | خیر |
| claim reconciliation | خیر | خیر |
| episode plan | خیر | خیر |
| script writer/verifier | خیر | خیر |

این محدودیت عمدی است. Search نباید evidence boundary را دور بزند.

## مرز evidence

خروجی Google Search یک **candidate source** است، نه evidence.

```text
Google Search candidate
→ full-text acquisition
→ parser
→ parse-quality gate
→ explicit user inclusion
→ evidence extraction
→ Claim Ledger
```

metadata، snippet یا پاسخ grounded مدل به‌تنهایی وارد Claim Ledger نمی‌شود.

## artifactهای audit

هر model run دارای policy grounding در `request.json` است. اگر ابزار وب استفاده شود،
فایل زیر نیز ذخیره می‌شود:

```text
workspaces/<project-id>/model-runs/<run-id>/grounding.json
```

این فایل شامل موارد زیر است:

- mode ابزار؛
- queryهای واقعی Google Search؛
- URL، عنوان و domain منابع grounding؛
- وضعیت retrieval در URL Context.

## تنظیمات

```dotenv
THESISOUND_GEMINI_GOOGLE_SEARCH_ENABLED=true
THESISOUND_GEMINI_URL_CONTEXT_ENABLED=true
```

اگر URL Context فعال باشد ولی URL عمومی صریح در ورودی نباشد، ابزار URL Context به
درخواست اضافه نمی‌شود.

## جست‌وجوی دستی

```bash
uv run thesisound search-web "موضوع یا پرسش"
```

نتایج این فرمان candidate هستند و در جدول با برچسب `not evidence` نمایش داده می‌شوند.
برای استفاده در podcast باید متن کاملشان جداگانه وارد ingestion شود.

## محدودیت‌ها

- URLهای private، نیازمند login یا paywall برای URL Context مناسب نیستند.
- در هر درخواست حداکثر ۲۰ URL به URL Context داده می‌شود.
- Search می‌تواند هزینه و latency درخواست را افزایش دهد.
- ابزارهای built-in در TTS و ASR استفاده نمی‌شوند.
- grounding metadata باید برای audit باقی بماند؛ متن خام provider به‌صورت پیش‌فرض
  ذخیره نمی‌شود.
