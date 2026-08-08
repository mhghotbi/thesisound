# 22 — ساخت واقعی مجموعه شواهد از رابط وب

## هدف

این slice فاصله میان `corpus confirmation` و `CORPUS_READY` را حذف می‌کند.

```text
selected READY sources
→ persisted corpus run
→ semantic block building
→ document mapping
→ evidence extraction
→ claim ledger
→ all selected sources complete
→ CORPUS_READY
```

## نتیجه review گام‌های قبلی

دو نقص یکپارچگی پیش از این slice وجود داشت:

1. endpoint تغییر انتخاب منبع پس از تأیید corpus همچنان قابل فراخوانی بود و می‌توانست UI manifest را از `Project.sources` جدا کند؛
2. `SourceAnalysisService.build_claims` پس از آماده‌شدن اولین منبع، پروژه را `CORPUS_READY` می‌کرد؛ این رفتار برای corpus چندمنبعی زودهنگام بود.

هر دو مورد در این slice اصلاح شده‌اند.

## قرارداد run

آخرین اجرای corpus در فایل زیر ذخیره می‌شود:

```text
<workspace>/<project_id>/corpus-build-run.json
```

run شامل این داده‌هاست:

- `run_id`؛
- وضعیت `queued | running | succeeded | failed`؛
- فهرست دقیق منابع تأییدشده؛
- ingestion artifact هر منبع؛
- stage واقعی هر منبع؛
- claim count؛
- خطای آخر؛
- زمان شروع، به‌روزرسانی و پایان.

stageهای source:

```text
queued
building_blocks
mapping_document
extracting_evidence
building_claims
complete | failed
```

در UI درصد یا ETA ساختگی نمایش داده نمی‌شود. فقط تعداد منابع تکمیل‌شده و stage ذخیره‌شده نشان داده می‌شود.

## قاعده چندمنبعی

`SourceAnalysisService` همچنان برای CLI تک‌منبعی می‌تواند با `finalize_project=true` پروژه را نهایی کند.

orchestrator چندمنبعی همیشه از این قرارداد استفاده می‌کند:

```python
build_claims(..., finalize_project=False)
```

پس از تکمیل همه sourceها، فقط `CorpusBuildingService` transition زیر را انجام می‌دهد:

```text
CORPUS_BUILDING → CORPUS_READY
```

هیچ source منفردی اجازه ندارد این transition را زودتر انجام دهد.

## failure و retry

اگر یک source شکست بخورد:

- همان source برابر `failed` می‌شود؛
- project برابر `FAILED_RETRYABLE` می‌شود؛
- sourceهای تکمیل‌شده حفظ می‌شوند؛
- error در run و source ثبت می‌شود؛
- retry فقط sourceهای failed را دوباره `queued` می‌کند؛
- sourceهای succeeded دوباره اجرا نمی‌شوند.

نبود `GEMINI_API_KEY` یا dependency مدل نیز failure قابل‌مشاهده و retryable است و به‌صورت silent باقی نمی‌ماند.

## قفل corpus

پس از `corpus confirmation`:

- upload جدید پذیرفته نمی‌شود؛
- toggle انتخاب منبع پذیرفته نمی‌شود؛
- صفحه منابع read-only است؛
- inputهای run از ingestion artifactهای همان source ID ساخته می‌شوند؛
- مسیر artifact باید داخل namespace همان project/source باقی بماند.

این قفل مانع divergence میان UI manifest، `Project.sources` و corpus run می‌شود.

## مرز این slice

این slice corpus را تا `CORPUS_READY` می‌سازد.

Coverage audit و تصمیم درباره کافی‌بودن corpus برای مدت درخواستی، آغاز `EPISODE_PLANNING` است و در application service موجود `EpisodePreparationService` باقی می‌ماند. انتقال آن منطق به corpus builder مجاز نیست.

## Definition of Done

- همه منابع تأییدشده وارد run شوند؛
- هر source از ingestion artifact واقعی خودش خوانده شود؛
- blocks، map، evidence و claims واقعاً ساخته و persist شوند؛
- project پیش از تکمیل همه sourceها `CORPUS_READY` نشود؛
- source selection پس از confirmation تغییر نکند؛
- failure و retry روی دیسک قابل بازیابی باشند؛
- processing page stage واقعی را نمایش دهد؛
- تست چندمنبعی و تست قفل selection وجود داشته باشد؛
- Ruff و کل pytest suite سبز باشند.
