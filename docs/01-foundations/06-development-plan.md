# 06 — برنامه توسعه

**وضعیت زندهٔ هر milestone در [`STATUS.md`](../../STATUS.md) است، نه اینجا.** این سند ترتیب و دلیل آن ترتیب را نگه می‌دارد؛ آنچه انجام شده در اسناد [`../02-pipeline/`](../02-pipeline/) و [`../03-web-ui/`](../03-web-ui/) به‌صورت as-built ثبت است.

## راهبرد

ترتیب توسعه بر اساس ریسک است، نه جذابیت UI:

```text
input fidelity → evidence fidelity → episode sufficiency → script fidelity
→ audio fidelity → operator control and observability
→ discovery and multi-source breadth → end-user UI → persistence and deployment
```

> **بازنگری ۲۰۲۶-۰۸-۱۹:** پس از M7، ادامهٔ مسیر دیگر M8–M10 نیست؛ [`10-personal-learning-companion-development-plan.md`](10-personal-learning-companion-development-plan.md) جای آن‌ها را می‌گیرد (P0 قرارداد → P1 نقشهٔ مفهومی → P2 کامل‌بودن شواهد → P3 `source_coverage` → P4 متن → P5 UI → P6 ارزیابی). دیگر «End-user UI» جداگانه‌ای وجود ندارد: مالک همان اپراتور است.

## قواعد سراسری

- parse، block ID و locator مستقل از duration هستند؛
- برای `focused_question`، breadth و depth شواهد و اپیزود به duration وابسته‌اند؛ برای `source_coverage` به دامنه و فشردگی وابسته‌اند و duration خروجی است (سند ۱۰ §6)؛
- مدل هیچ ID یا locator معتبری نمی‌سازد؛
- متن اصلی source of truth است؛
- corpus ناکافی با padding جبران نمی‌شود؛
- writer تنها verifier خروجی خودش نیست؛
- هر stage artifact، gate و failure state مستقل دارد؛
- UI منطق orchestration یا state machine دوم نمی‌سازد.

## نقشهٔ milestoneها

| # | Milestone | سند مرجع |
|---|---|---|
| M0 | Scaffold و قراردادها | [`02-architecture.md`](02-architecture.md) |
| M1 | Document ingestion | [`../02-pipeline/01-document-ingestion.md`](../02-pipeline/01-document-ingestion.md) |
| M2 | Structured model execution | [`../02-pipeline/02-structured-model-execution.md`](../02-pipeline/02-structured-model-execution.md) |
| M2.5 | مشاهده‌پذیری واحد فراخوانی مدل | [`../04-integrations/05-model-observability.md`](../04-integrations/05-model-observability.md) |
| M3 | One-source evidence pipeline | [`../02-pipeline/03-one-source-evidence-pipeline.md`](../02-pipeline/03-one-source-evidence-pipeline.md) |
| M4 | Episode preparation | [`../02-pipeline/05-episode-preparation.md`](../02-pipeline/05-episode-preparation.md) |
| M5 | سناریوی فارسی verified | [`../02-pipeline/06-persian-script-pipeline.md`](../02-pipeline/06-persian-script-pipeline.md) |
| M6 | TTS، ASR و Audio QA | [`../03-web-ui/09-audio-vertical-slice.md`](../03-web-ui/09-audio-vertical-slice.md) |
| M6.5 | Operator UI | [`../03-web-ui/`](../03-web-ui/) |
| M7 | Source Discovery | [`../04-integrations/02-source-discovery-large-docs-and-revision.md`](../04-integrations/02-source-discovery-large-docs-and-revision.md) |
| M8–M10 | **بازنشسته** — جایگزین: فازهای P0–P6 سند ۱۰ | [`10-personal-learning-companion-development-plan.md`](10-personal-learning-companion-development-plan.md) |

بخش‌های زیر دربارهٔ M8–M10 فقط به‌عنوان سابقهٔ تصمیم نگه داشته شده‌اند. M8 (reconciliation چندمنبعی کامل) و M9 (UI کاربر نهایی) دیگر هدف نیستند؛ M10 فقط اگر استفادهٔ واقعی نیاز را ثابت کرد.

## Milestone 8 — Multi-source reconciliation (بازنشسته)

reconciliation آگاه به نقش منبع؛ یال‌های اختلاف معنایی؛ synthesis آگاه به انتساب؛ تخصیص بودجه میان منابع؛ جست‌وجوی gap؛ ارتقای تدریجی profile؛ استفادهٔ دوباره از شواهد معتبر قبلی؛ جلوگیری از dominance یک منبع یا اجماع جعلی.

Disagreement Graph فعلی فقط stanceهای صریح را نگه می‌دارد؛ رابطه‌های معنایی میان claimها در این milestone ساخته می‌شوند.

## Milestone 9 — End-user product UI

فقط پس از تثبیت workflow در Operator UI و اجرای موفق چند پروژهٔ واقعی: تجربهٔ ساده‌شدهٔ ساخت پروژه؛ upload و انتخاب منبع کاربرپسند؛ نمایش اثر duration بر هزینه، پوشش و omission **پیش از اجرا**؛ progress بدون جزئیات مهندسی؛ بازبینی طرح و متن متناسب با کاربر غیرمتخصص؛ player و transcript و trace تا منبع؛ کنترل‌های privacy و چرخهٔ عمر داده؛ onboarding و empty state؛ دسترس‌پذیری و responsive؛ telemetry با حفظ privacy.

End-user UI نباید APIهای داخلی Operator UI را بدون boundary عمومی expose کند؛ اول use caseها و permission model مستقل تعریف شوند.

## Milestone 10 — Persistence، jobs و deployment

فقط وقتی usage واقعی نیاز را اثبات کرد: repository و job table روی SQLite؛ stage runner قابل resume؛ cache بلاک/مدل/صوت؛ cleanup و حذف پروژه؛ deployment خصوصی؛ object storage؛ access control؛ PostgreSQL/Redis فقط با نیاز واقعی concurrency.

Operator UI می‌تواند روی artifact store فایل‌سیستمی و process محلی کار کند. مهاجرت به job queue یا database نباید پیش‌شرط ساخت UI شود، اما UI باید command boundary داشته باشد تا این مهاجرت بعداً بدون بازنویسی منطق صفحه‌ها ممکن باشد.
