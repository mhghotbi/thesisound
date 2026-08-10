# 03 — موجودی صفحه‌های Operator UI

> **وضعیت: نیت طراحی اولیه، تاریخی.** routeهای این سند با کد فعلی یکی نیستند (`/pipeline` امروز `/processing` است؛ `/runs/{id}` و `/artifacts/{key}` و `/settings` پیاده نشده‌اند و جایشان `/observability`، `/readiness` و `/system-check` آمده). صفحه‌های واقعاً ساخته‌شده در [`05-web-ui-auth-and-first-slice.md`](05-web-ui-auth-and-first-slice.md) تا [`09-audio-vertical-slice.md`](09-audio-vertical-slice.md) و routeهای هدف در [`../05-ui-redesign/02-ui-redesign-spec.md`](../05-ui-redesign/02-ui-redesign-spec.md) ثبت شده‌اند. این سند برای شناسه‌های S-01…S-12 نگه داشته شده که [`../05-ui-redesign/01-ui-ux-audit.md`](../05-ui-redesign/01-ui-ux-audit.md) به آن‌ها ارجاع می‌دهد.

## موجودی صفحه‌ها

| ID | صفحه | route طراحی‌شده | مسئولیت و قاعدهٔ کلیدی |
|---|---|---|---|
| S-01 | Project List | `/projects` | فهرست با وضعیت attention؛ ورود به پروژه |
| S-02 | Create Project | `/projects/new` | PRG pattern؛ submit تکراری با idempotency key پروژهٔ دوم نسازد |
| S-03 | Project Overview | `/projects/{id}` | نقشهٔ وضعیت کل پروژه و action بعدی. بخش‌ها: header (title، state، duration، source mode)، stage timeline، پنل action required، آخرین run، warning/failure، خلاصهٔ artifact و usage. primary action از read model می‌آید. **ممنوع:** چند primary هم‌ارزش، collapse کردن failure در toast، تغییر lifecycle state از dropdown |
| S-04 | Brief Editor | `/projects/{id}/brief` | fieldهای کامل قابل‌ویرایش + diff نسخهٔ قبلی. **`Save` و `Confirm` یکی نیستند**؛ draft ذخیره‌شده human gate را نمی‌بندد |
| S-05 | Source Workspace | `/projects/{id}/sources` | upload، inspection، parse و انتخاب corpus |
| S-06 | Pipeline Monitor | `/projects/{id}/pipeline` | اجرای stage بعدی و recovery. `Run full available slice` فقط تا human gate یا failure بعدی اجرا می‌کند و gate را دور نمی‌زند. polling فقط هنگام run فعال و بدون reset کردن scroll/focus |
| S-07 | Run Detail | `/projects/{id}/runs/{run_id}` | یک attempt: hashها، model/provider، usage، latency، finish reason، retry lineage. اگر آخرین attempt نیست، **banner تاریخی صریح** لازم است |
| S-08 | Episode Review | `/projects/{id}/episode` | sufficiency corpus و بررسی plan پیش از تولید متن |
| S-09 | Script Review | `/projects/{id}/script` | متن، وضعیت verifier و trace هر turn تا منبع |
| S-10 | Audio Review | `/projects/{id}/audio` | وضعیت segmentها، ASR diff، بازتولید هدفمند |
| S-11 | Artifact Inspector | `/projects/{id}/artifacts/{key}` | نمایش artifact با hash، size، run سازنده، وابستگی‌ها و badge stale/current. rendered prompt فقط اگر policy اجازه دهد؛ نبودش خطا نیست |
| S-12 | Local Settings | `/settings` | فقط presence و validation status: در دسترس بودن provider و parser، وضعیت FFmpeg، مسیر workspace، flagهای privacy. **secret کامل هرگز render نمی‌شود** |

## قواعد مشترک

**componentهای هم‌منبع.** `ProjectStateBadge`، `AttentionBanner`، `StageTimeline`، `RunStatusPanel`، `WarningList`، `ErrorRecoveryPanel`، `ArtifactLink`، `ImpactSummaryDialog`، `TechnicalDetailsDisclosure` و `UsageSummary` باید از یک view model مشترک تغذیه شوند. (فهرست مقصد بازطراحی در spec متفاوت است.)

**confirmation فقط برای destructive یا پرهزینه:** حذف پروژه/منبع، تغییر upstream با invalidation گسترده، force rerun، پاک‌کردن artifact تاریخی، بازتولید پرهزینهٔ صوت. retry با همان ورودی modal لازم ندارد؛ اگر هزینه قابل‌توجه است، cost summary در خود پنل action بیاید.

## معیار پذیرش

- هر lifecycle state حداقل یک screen owner دارد؛
- هر human gate در یک صفحه action روشن دارد؛
- هر failure قابل‌بازیابی route و recovery panel دارد؛
- هیچ primary action بدون precondition سمت server نیست؛
- artifact مهم بدون route inspection نمی‌ماند؛
- page refresh و browser back فرمان تکراری ایجاد نمی‌کنند.
