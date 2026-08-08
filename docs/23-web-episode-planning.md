# 23 — ارزیابی پوشش و طرح اپیزود در رابط وب

## هدف

این slice فاصله میان `CORPUS_READY` و human gate بررسی Episode Plan را می‌بندد.

```text
CORPUS_READY
→ coverage audit
→ claim prioritization
→ supported-duration budget
→ disagreement graph
→ Episode Plan
→ segment evidence packs
→ EPISODE_PLANNED
→ توقف برای بررسی کاربر
```

در این مرحله script generation آغاز نمی‌شود.

## یافته‌های review گام قبلی

بازبینی مستقل corpus-building چهار نقص قراردادی را آشکار کرد:

1. project پیش از persist شدن corpus run به `CORPUS_BUILDING` می‌رفت؛ failure در queue می‌توانست project قفل‌شده بدون run بسازد؛
2. retry همان `run_id` را بازنویسی می‌کرد و attempt history از بین می‌رفت؛
3. Research Brief پس از شروع downstream بدون stale marking قابل ویرایش بود؛
4. episode preparation همه artifactهای `claims_ready` را می‌خواند و به فهرست تأییدشده `Project.sources` محدود نبود.

اصلاحات:

- corpus confirmation یک compensated mutation است: اگر run persist نشود، project به snapshot قبلی برمی‌گردد؛
- هر retry یک run جدید با `previous_run_id` می‌سازد؛
- Brief پس از شروع corpus فقط خواندنی است؛
- تغییر تمرکز فقط از recovery پوشش انجام می‌شود و episode artifacts را stale علامت می‌زند؛
- planning در projectهای دارای source registry فقط منابع `FULL_TEXT + INCLUDE` همان project را می‌خواند؛
- fallback به همه claim-readyها فقط برای project legacy بدون source registry حفظ شده است.

## قرارداد planning run

آخرین attempt:

```text
<workspace>/<project_id>/episode/planning-run.json
```

تاریخچه کامل:

```text
<workspace>/<project_id>/runs/episode-planning/<run_id>.json
```

وضعیت‌ها:

```text
queued | running | blocked | succeeded | failed
```

stageها:

```text
queued
→ auditing_coverage
→ prioritizing_claims
→ estimating_budget
→ building_disagreements
→ planning_episode
→ building_evidence_packs
→ complete
```

`blocked` برای کمبود evidence یک failure فنی نیست. project در `EPISODE_PLANNING` می‌ماند تا کاربر یکی از recovery actionهای مجاز را انتخاب کند.

## قواعد پوشش و مدت

دو gate مستقل وجود دارد:

1. مدل structured، پوشش سؤال مرکزی و learning objectiveها را ارزیابی می‌کند؛
2. budget deterministic مدت مؤثر قابل‌پشتیبانی را محاسبه می‌کند.

اگر هر gate کافی نباشد:

- ساخت Episode Plan متوقف می‌شود؛
- دکمه «ادامه به هر حال» وجود ندارد؛
- مدت درخواستی و مدت قابل‌پشتیبانی نمایش داده می‌شوند؛
- material gapها نمایش داده می‌شوند.

Recovery actionها:

- کاهش مدت و اجرای attempt جدید؛
- افزودن منبع؛
- تغییر تمرکز Research Brief.

کاهش مدت تنها وقتی پذیرفته می‌شود که از مقدار قابل‌پشتیبانی بیشتر نباشد.

## قفل upstream و stale marking

بعد از تأیید corpus:

- Brief و انتخاب منابع read-only هستند؛
- تغییر مستقیم endpoint نیز رد می‌شود.

وقتی coverage review تغییر ورودی را درخواست کند:

```text
EPISODE_PLANNING
→ SOURCES_COLLECTING
```

و marker زیر نوشته می‌شود:

```text
<workspace>/<project_id>/episode/stale.json
```

وجود marker یعنی artifactهای episode قبلی نباید به‌عنوان خروجی معتبر بعدی مصرف شوند.

## recovery و restart

اگر process در حالت `queued` یا `running` ری‌استارت شود:

- run برابر `failed` می‌شود؛
- stage برابر `failed` می‌شود؛
- project فعال برابر `FAILED_RETRYABLE` می‌شود؛
- retry یک attempt تازه ایجاد می‌کند؛
- attempt قبلی حفظ می‌شود.

## UI

route اصلی:

```text
/projects/{project_id}/episode
```

حالت‌ها:

- آماده شروع از `CORPUS_READY`؛
- stage واقعی run فعال؛
- failure و retry؛
- blocked coverage و recovery actionها؛
- Episode Plan نهایی با مدت، بخش‌ها، purpose، سؤال محوری و تعداد claimها.

UI درصد یا ETA ساختگی نشان نمی‌دهد و هر سه ثانیه فقط در run فعال refresh می‌شود.

## مرز این slice

خروجی این slice:

```text
EPISODE_PLANNED
```

گام بعدی human gate تأیید طرح و سپس `SCRIPT_DRAFTING` است. هیچ route در این slice اجازه شروع script قبل از تأیید صریح طرح را ندارد.

## Definition of Done

- queue failure project را در حالت نیمه‌ثبت‌شده رها نکند؛
- retry attempt قبلی را overwrite نکند؛
- Brief و source selection پس از confirmation قفل باشند؛
- source خارج از corpus تأییدشده وارد planning نشود؛
- coverage insufficiency blocked باشد، نه failure و نه bypass؛
- duration reduction، add source و change focus recovery واقعی داشته باشند؛
- restart به failure قابل retry تبدیل شود؛
- Episode Plan در UI قابل بررسی باشد؛
- script generation هنوز شروع نشود؛
- Ruff و کل pytest suite سبز باشند.
