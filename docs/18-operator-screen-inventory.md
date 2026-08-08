# 18 — موجودی صفحه‌های Operator UI

## هدف

این سند screenها، routeها، مسئولیت هر صفحه و مرز نسخه اول Operator UI را مشخص می‌کند. موجودی صفحه به معنی تعهد به طراحی بصری نهایی نیست؛ مبنای wireframe و implementation slice است.

## مدل navigation

```text
/projects
  /new
  /{project_id}
    /brief
    /sources
    /pipeline
    /episode
    /script
    /audio
    /runs/{run_id}
    /artifacts/{artifact_key}
/settings
```

در نسخه اول navigation در سطح پروژه ثابت است. stageهای unavailable دیده می‌شوند اما disabled هستند و precondition را توضیح می‌دهند.

## اولویت release

### Operator UI v0.1

- Project list؛
- Create project؛
- Project overview؛
- Brief editor؛
- Source workspace؛
- Pipeline monitor؛
- Episode review؛
- Script review؛
- Run detail و Artifact inspector؛
- Local settings.

### Operator UI v0.2

پس از TTS vertical slice:

- Audio review؛
- segment player؛
- ASR diff؛
- regenerate defective segment؛
- final package export.

### Operator UI v0.3

پس از Source Discovery:

- query plan review؛
- source candidate list؛
- authority/evidence availability؛
- deduplication groups؛
- source selection gate.

---

## S-01 — Project List

**Route:** `/projects`

### هدف

انتخاب پروژه موجود یا ایجاد پروژه جدید.

### داده اصلی

- title؛
- project ID؛
- source mode؛
- duration؛
- lifecycle state؛
- attention state؛
- last activity؛
- آخرین run؛
- primary next action.

### interaction

- search محلی بر اساس title یا ID؛
- filter: active، waiting، failed، complete؛
- sort پیش‌فرض بر اساس last activity؛
- create project؛
- open project.

### empty state

توضیح کوتاه درباره workflow و دکمه `Create first project`. نمونه demo جعلی ساخته نمی‌شود.

### ممنوع

- اجرای stage مستقیم از card؛
- حذف پروژه با یک click؛
- نمایش درصد پیشرفت تخمینی بدون واحد واقعی.

## S-02 — Create Project

**Route:** `/projects/new`

### fieldها

- title یا central topic؛
- central question اختیاری؛
- audience؛
- prior knowledge؛
- duration؛
- content modes؛
- output language؛
- source mode.

### primary action

`Create project and build brief`

### validation

- title خالی مجاز نیست؛
- duration در بازه domain؛
- حداقل یک mode؛
- research-assisted اگر implement نشده disabled با توضیح؛
- field error کنار field، نه فقط banner.

### پس از submit

PRG pattern: POST سپس redirect به Brief. submit تکراری با idempotency key پروژه دوم نسازد.

## S-03 — Project Overview

**Route:** `/projects/{project_id}`

### هدف

نقشه وضعیت کل پروژه و action بعدی.

### بخش‌ها

1. header: title، state، duration و source mode؛
2. stage timeline؛
3. action required panel؛
4. latest run؛
5. warning و failure؛
6. artifact summary؛
7. usage summary.

### primary action

از read model می‌آید: confirm brief، add source، retry، prepare episode، verify script یا continue to audio.

### secondary actions

- open latest run؛
- inspect artifacts؛
- edit project settings؛
- view historical runs.

### ممنوع

- چند primary button هم‌ارزش؛
- collapse کردن failure در toast؛
- تغییر lifecycle state از dropdown.

## S-04 — Brief Editor

**Route:** `/projects/{project_id}/brief`

### هدف

ساخت، اصلاح و تأیید Research Brief.

### fieldهای قابل‌ویرایش

- central question؛
- audience؛
- prior knowledge؛
- learning objectives؛
- must-include concepts؛
- exclusions؛
- duration؛
- modes؛
- language.

### نماها

- form view پیش‌فرض؛
- raw JSON در artifact drawer؛
- model run metadata؛
- diff میان نسخه قبلی و فعلی.

### actionها

- generate draft؛
- save edits؛
- confirm brief؛
- rebuild brief؛
- view affected downstream artifacts پس از تغییر.

### قواعد

`Save` و `Confirm` یکی نیستند. draft ذخیره‌شده تا زمان confirm human gate را نمی‌بندد.

## S-05 — Source Workspace

**Route:** `/projects/{project_id}/sources`

### هدف

مدیریت upload، inspection، parse و corpus selection.

### layout پیشنهادی

- بالا: upload area؛
- وسط: source table/cards؛
- پایین یا side panel: source detail؛
- footer ثابت: corpus summary و primary action.

### اطلاعات هر source

- filename و source ID؛
- file type/size؛
- inspection status؛
- parser و parse status؛
- quality gate؛
- text coverage؛
- warning count؛
- selected for corpus.

### actionها

- upload؛
- inspect؛
- parse auto؛
- choose parser؛
- retry؛
- preview extracted text؛
- compare parser attempts؛
- include/exclude؛
- remove source؛
- confirm corpus.

### stateهای صفحه

- no source؛
- upload in progress؛
- inspection failed؛
- parse running؛
- parse warning؛
- parse failed retryable؛
- usable source not selected؛
- corpus ready.

### ممنوع

- انتخاب خودکار source warningدار بدون اطلاع؛
- مخلوط‌کردن metadata-only و parsed full text؛
- حذف source upstream بدون impact summary.

## S-06 — Pipeline Monitor

**Route:** `/projects/{project_id}/pipeline`

### هدف

اجرای stage بعدی، مشاهده run فعال و recovery از failure.

### بخش‌ها

- stage timeline؛
- current run panel؛
- deterministic/model indicator؛
- progress units واقعی؛
- warning/error panel؛
- usage and latency؛
- recent runs.

### actionها

- run next stage؛
- run full available slice؛
- retry failed stage؛
- cancel؛
- open run detail؛
- inspect input/output artifacts.

### رفتار `Run full available slice`

این action فقط تا human gate یا failure بعدی اجرا می‌کند. نباید gate انسانی را دور بزند.

### refresh

HTMX polling فقط هنگام run فعال. status update نباید scroll یا focus کاربر را reset کند.

## S-07 — Run Detail

**Route:** `/projects/{project_id}/runs/{run_id}`

### هدف

بازبینی یک attempt مشخص و مقایسه آن با attemptهای دیگر.

### داده

- stage؛
- attempt؛
- input hashes؛
- config hash؛
- timestamps؛
- model/provider؛
- token usage؛
- latency؛
- finish reason؛
- warning/error؛
- artifact links؛
- retry lineage.

### actionها

- retry from same inputs؛
- compare with previous attempt؛
- open artifact؛
- copy diagnostic bundle.

### historical banner

اگر run آخرین attempt نیست، banner صریح نشان داده شود. action تاریخی نباید با primary action پروژه اشتباه شود.

## S-08 — Episode Review

**Route:** `/projects/{project_id}/episode`

### هدف

فهمیدن sufficiency corpus و بررسی plan قبل از script generation.

### ترتیب صفحه

1. coverage verdict؛
2. duration support؛
3. blocking gaps؛
4. segment outline؛
5. claim coverage؛
6. disagreement graph؛
7. budget details؛
8. evidence packs.

### actionها

- prepare/rebuild episode؛
- reduce duration؛
- return to sources؛
- edit brief؛
- continue to script؛
- inspect evidence pack.

### visual requirement

Coverage باید با عبارت دقیق نمایش داده شود؛ صرفاً score رنگی کافی نیست. مثال: «corpus برای حدود ۱۸ دقیقه از هدف ۲۵ دقیقه evidence معتبر دارد.»

## S-09 — Script Review

**Route:** `/projects/{project_id}/script`

### هدف

خواندن script، بررسی verification و trace کردن ادعاها.

### layout

- summary header؛
- segment navigation؛
- transcript panel؛
- evidence/issue side panel؛
- verification result؛
- revision diff.

### interaction هر turn

click روی turn باید claim، evidence، excerpt و locator را در side panel باز کند. operator نباید برای trace به raw JSON برود.

### actionها

- write script؛
- run checks؛
- verify؛
- revise failed turns؛
- compare draft/revised؛
- record calibration؛
- continue to audio.

### قواعد

- unsupported turn برجسته شود؛
- issue باید به turn و rule متصل باشد؛
- manual edit در v0.1 غیرفعال؛
- revised script بدون verification دوباره قابل پذیرش نیست.

## S-10 — Audio Review

**Route:** `/projects/{project_id}/audio`

**Release:** v0.2

### بخش‌ها

- segment generation table؛
- waveform یا player ساده؛
- expected text و ASR text؛
- semantic diff؛
- pronunciation audit؛
- loudness/duration؛
- final assembly.

### actionها

- generate missing segments؛
- regenerate failed segment؛
- rerun ASR؛
- rerun Audio QA؛
- assemble؛
- export.

### ممنوع

- regenerate کل audio وقتی فقط یک segment معیوب است؛
- پنهان‌کردن speaker swap یا truncation در warning عمومی.

## S-11 — Artifact Inspector

**Route:** `/projects/{project_id}/artifacts/{artifact_key}`

### هدف

بازبینی artifact بدون خروج از UI.

### قابلیت‌ها

- formatted JSON/JSONL؛
- line wrapping؛
- search؛
- copy path؛
- download؛
- hash و size؛
- generated-by run؛
- input dependencies؛
- stale/current badge.

### امنیت و privacy

rendered prompt فقط اگر policy و environment اجازه دهد نمایش داده می‌شود. نبود آن نباید به‌عنوان خطا تعبیر شود.

## S-12 — Local Settings

**Route:** `/settings`

### scope

- provider availability؛
- parser availability؛
- FFmpeg status؛
- workspace path؛
- environment diagnostics؛
- privacy flags؛
- default model IDs.

### قواعد

- secret کامل هرگز render نشود؛
- API key در v0.1 از environment خوانده می‌شود؛
- صفحه فقط presence و validation status را نشان می‌دهد؛
- تغییر setting حساس نیازمند restart اگر runtime چنین محدودیتی دارد.

---

## componentهای مشترک

این componentها باید از یک view model مشترک تغذیه شوند:

- `ProjectStateBadge`؛
- `AttentionBanner`؛
- `StageTimeline`؛
- `RunStatusPanel`؛
- `WarningList`؛
- `ErrorRecoveryPanel`؛
- `ArtifactLink`؛
- `ImpactSummaryDialog`؛
- `TechnicalDetailsDisclosure`؛
- `UsageSummary`.

در نسخه اول design system جداگانه لازم نیست، اما state label و action hierarchy باید در همه صفحه‌ها یکسان باشد.

## confirmation pattern

confirmation فقط برای actionهای destructive یا پرهزینه استفاده شود:

- حذف project/source؛
- تغییر upstream با invalidation گسترده؛
- force rerun؛
- پاک‌کردن historical artifacts؛
- regenerate پرهزینه audio.

action عادی مانند retry stage با همان input به modal نیاز ندارد، مگر هزینه قابل‌توجه داشته باشد؛ در آن صورت cost summary در خود action panel نشان داده می‌شود.

## ترتیب wireframe

wireframeها به این ترتیب ساخته شوند:

1. Project Overview؛
2. Source Workspace؛
3. Pipeline Monitor؛
4. Episode Review؛
5. Script Review؛
6. Project List و Create Project؛
7. Run Detail و Artifact Inspector؛
8. Audio Review.

دلیل این ترتیب این است که پیچیده‌ترین interactionها در overview، sources و pipeline هستند. شروع از login یا landing page ریسک اصلی UX را حل نمی‌کند.

## معیار پذیرش screen inventory

- هر lifecycle state حداقل یک screen owner دارد؛
- هر human gate در یک صفحه action روشن دارد؛
- هر failure قابل‌بازیابی route و recovery panel دارد؛
- هیچ primary action بدون precondition server-side نیست؛
- artifact مهم بدون route inspection باقی نمی‌ماند؛
- صفحه‌های v0.1 برای اجرای one-source تا `script_verified` کافی‌اند؛
- page refresh و browser back command تکراری ایجاد نمی‌کنند.
