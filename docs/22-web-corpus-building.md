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
complete | skipped | failed
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

## کنار گذاشتن یک منبع متوقف‌شده

اجرا fail-fast است: با شکست یک source، بقیه در `queued` می‌مانند. اگر خود منبع مشکل داشته باشد، retry بی‌فایده است. بنابراین از صفحه processing این action وجود دارد:

```text
POST /projects/{project_id}/corpus/sources/{source_id}/skip
```

قرارداد این action:

- فقط روی run با وضعیت `failed` کار می‌کند؛
- فقط source با وضعیت `queued` یا `failed` قابل کنار گذاشتن است؛ source `succeeded` نه؛
- دست‌کم یک source باید در corpus بماند؛
- attempt تازه‌ای ساخته می‌شود: `succeeded`ها حفظ، source انتخاب‌شده `skipped`، بقیه دوباره `queued`؛
- source کنار گذاشته‌شده از `Project.sources` هم حذف می‌شود، چون هر stage بعدی برای هر عضو `Project.sources` یک claim ledger لازم دارد؛
- انتخاب همان منبع در UI manifest نیز برداشته می‌شود؛
- run جدید بلافاصله اجرا می‌شود و نیازی به تأیید دوبارهٔ منابع نیست.

`retry` نیز sourceهای `skipped` را دوباره `queued` نمی‌کند.

تکمیل corpus یعنی: هر source یا `succeeded` است یا `skipped`، و دست‌کم یک `succeeded` وجود دارد. corpus خالی به `CORPUS_READY` نمی‌رسد.

## شناسهٔ محتوامحور منبع

شناسهٔ منبع در آپلود وب دیگر تصادفی نیست. فایل ابتدا زیر یک staging ID ذخیره و parse می‌شود، سپس شناسهٔ نهایی از متن به دست می‌آید:

```text
source_id = uuid5(project_id, parsed_document_key(parsed))
```

- اگر منبعی با همین شناسه در همان گفتار باشد، فایل دوم افزوده نمی‌شود و کاربر پیام روشن می‌گیرد؛ منبع موجود و تحلیلش دست‌نخورده می‌ماند.
- وگرنه پوشهٔ آپلود و artifactهای ingestion از staging ID به شناسهٔ نهایی منتقل می‌شوند. `artifact_ref` نسبت به ریشهٔ artifact ذخیره می‌شود و با این جابه‌جایی معتبر می‌ماند.
- فایل با نوع پشتیبانی‌نشده یا سندی که parse نشده، کلید محتوا ندارد و با همان staging ID می‌ماند.

چون شناسه پایدار است، آپلود دوبارهٔ همان کتاب پس از rewind دقیقاً به همان `sources/<source_id>/` می‌رسد و کل زنجیرهٔ بازاستفاده — نقشهٔ منبع، شاهدهای هر پاره‌متن، و carry-forward دفتر مدعاها — بدون کار اضافه فعال می‌شود.

## carry-forward هنگام تأیید دوبارهٔ منابع

`confirm` مثل `retry` باید کار تمام‌شده را دوباره نسازد. در `queue` هر source تأییدشده پیش از رفتن به صف با `corpus_reuse.reusable_claim_ledger` سنجیده می‌شود:

- `manifest.status == "claims_ready"`؛
- `manifest.source_sha256` برابر sha256 همان ingestion artifact فعلی؛
- claim ledger خوانده شود و `source_id` آن درست باشد؛
- `plan_evidence_extraction` با brief فعلی دقیقاً همان `profile` و همان `selected_block_ids` ذخیره‌شده را بدهد.

اگر هر شرط برقرار نباشد، source از صفر ساخته می‌شود. اگر همه برقرار باشند، source با `status=succeeded`، `stage=complete`، `claim_count` واقعی و `carried_forward=true` وارد run می‌شود و هیچ فراخوانی مدلی برای آن انجام نمی‌شود. UI همین را نشان می‌دهد و وانمود نمی‌کند که دوباره ساخته شده است.

شرط brief عمداً سخت‌گیرانه است: تغییر مدت هدف، mode، سطح دانش پیشین یا پرسش اصلی، انتخاب و عمق استخراج شاهد را عوض می‌کند، پس شاهدهای قبلی دیگر همان چیزی نیستند که این گفتار می‌خواهد.

به همین دلیل rewind به مرحله منابع دیگر `sources/` را بایگانی نمی‌کند؛ اعتبارسنجی بالا جای بایگانی‌کردن را می‌گیرد. rewind به مرحله موضوع و هدف همچنان `sources/` را بایگانی می‌کند. حذف یک منبع از صفحه منابع هم artifactهای تحلیل همان منبع را پاک می‌کند تا claim ledger یتیم باقی نماند.

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
- کنار گذاشتن یک منبع متوقف‌شده، بقیه منابع را بدون تأیید دوباره ادامه دهد؛
- تأیید دوبارهٔ زیرمجموعه‌ای از منابع، sourceهای معتبر تمام‌شده را دوباره نسازد؛
- processing page stage واقعی را نمایش دهد؛
- تست چندمنبعی و تست قفل selection وجود داشته باشد؛
- Ruff و کل pytest suite سبز باشند.
