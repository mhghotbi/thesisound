# 02 — مدل state رابط Operator UI

مرتبط: این مدل state پایهٔ هر دو مسیر است — طراحی اولیه در [`01-operator-user-workflow.md`](01-operator-user-workflow.md) و پیاده‌سازی as-built در [`05-web-ui-auth-and-first-slice.md`](05-web-ui-auth-and-first-slice.md) به بعد.

## هدف

این سند قرارداد میان domain state، اجرای workflow و نمایش UI را تعریف می‌کند. مسئله اصلی این است که یک پروژه می‌تواند هم‌زمان:

- یک lifecycle state مشخص داشته باشد؛
- آخرین run موفق یا شکست‌خورده داشته باشد؛
- نیازمند تصمیم کاربر باشد؛
- artifactهای stale یا warningدار داشته باشد.

فشرده‌کردن همه این وضعیت‌ها در یک badge مانند `processing` یا `failed` اطلاعات مهم را از بین می‌برد. UI باید سه محور مستقل را نگه دارد.

## سه محور state

### ۱. Project lifecycle state

state قطعی domain که فقط application workflow می‌تواند تغییر دهد.

```text
DRAFT
BRIEF_READY
SOURCES_COLLECTING
SOURCE_SELECTION_REQUIRED
CORPUS_BUILDING
CORPUS_READY
EPISODE_PLANNING
EPISODE_PLANNED
SCRIPT_DRAFTING
SCRIPT_READY
SCRIPT_VERIFYING
SCRIPT_VERIFIED
AUDIO_GENERATING
AUDIO_READY
AUDIO_VERIFYING
COMPLETE
```

نام دقیق enum باید از کد domain خوانده شود. UI نباید نسخه دوم این enum را با spelling یا ترتیب مستقل نگه دارد.

### ۲. Execution state

وضعیت یک run مشخص:

```text
not_started
queued
running
passed
passed_with_warnings
failed_retryable
failed_permanent
cancel_requested
cancelled
interrupted
stale
```

`stale` یعنی run در گذشته معتبر بوده، اما یکی از input artifactها یا تنظیمات upstream تغییر کرده است.

### ۳. Attention state

وضعیت مشتق‌شده برای اینکه operator بداند چه اقدامی لازم است:

```text
none
action_available
waiting_for_user
blocked_by_failure
blocked_by_configuration
review_recommended
complete
```

Attention state در domain ذخیره نمی‌شود؛ server آن را از lifecycle state، آخرین run، warningها و وجود artifact معتبر محاسبه می‌کند.

---

## اصل مالکیت state

- domain مالک project lifecycle است؛
- run record مالک execution state است؛
- artifact store مالک وجود و hash خروجی‌هاست؛
- UI server یک read model مشتق‌شده می‌سازد؛
- browser فقط read model را render می‌کند و command می‌فرستد.

Browser نباید با مشاهده فایل‌ها یا حدس از URL تصمیم بگیرد stage کامل شده است.

## stageهای UI

| UI stage | lifecycleهای مرتبط | artifact اصلی | primary action |
|---|---|---|---|
| Brief | `DRAFT`, `BRIEF_READY` | Research Brief | ساخت، ویرایش یا تأیید brief |
| Sources | `SOURCES_COLLECTING`, `SOURCE_SELECTION_REQUIRED` | source manifests و parse report | افزودن، parse و تأیید corpus |
| Corpus | `CORPUS_BUILDING`, `CORPUS_READY` | blocks، document map، evidence و claims | اجرا یا retry evidence pipeline |
| Episode | `EPISODE_PLANNING`, `EPISODE_PLANNED` | coverage، budget، plan و packs | prepare episode یا review |
| Script | `SCRIPT_DRAFTING`, `SCRIPT_READY`, `SCRIPT_VERIFYING`, `SCRIPT_VERIFIED` | draft، checks و verification | write، verify یا revise |
| Audio | `AUDIO_GENERATING`, `AUDIO_READY`, `AUDIO_VERIFYING`, `COMPLETE` | segments، QA و final audio | generate، verify یا export |

جدول بالا navigation را تعریف می‌کند، نه transition. transition فقط در application service معتبر است.

## state هر stage در UI

برای هر stage یک `StageView` ساخته می‌شود:

```json
{
  "key": "script_verification",
  "label": "راستی‌آزمایی سناریو",
  "status": "failed_retryable",
  "started_at": "2026-08-08T10:20:00Z",
  "finished_at": "2026-08-08T10:21:40Z",
  "attempt": 2,
  "progress": {
    "completed_units": 8,
    "total_units": 10,
    "unit_label": "turn"
  },
  "warnings": 1,
  "error_code": "UNSUPPORTED_CLAIM",
  "primary_action": "revise_failed_turns",
  "technical_details_available": true
}
```

`progress` فقط زمانی وجود دارد که total unit واقعی و ثابت باشد. برای model call با زمان نامعلوم progress bar زمانی ساخته نمی‌شود؛ spinner و نام task کافی است.

## الگوریتم مشتق‌سازی وضعیت پروژه

ترتیب اولویت برای badge سطح پروژه:

1. اگر run فعال وجود دارد: `running`؛
2. اگر آخرین run شکست permanent دارد: `blocked_by_failure`؛
3. اگر آخرین run retryable شکست خورده: `action_available` با action retry؛
4. اگر human gate باز است: `waiting_for_user`؛
5. اگر artifact upstream تغییر کرده و downstream stale است: `review_recommended`؛
6. اگر project lifecycle برابر `COMPLETE` است: `complete`؛
7. در غیر این صورت: `action_available`.

warning نباید state موفق را به failure تبدیل کند. `passed_with_warnings` باید جدا نمایش داده شود.

## human gateها

Gateهای زیر نیازمند state صریح `waiting_for_user` هستند:

- تأیید Research Brief؛
- انتخاب corpus؛
- تصمیم درباره source warningدار؛
- رفع corpus insufficiency؛
- تصمیم درباره تغییر upstream که downstream را invalidate می‌کند؛
- بازبینی نهایی پیش از export، اگر policy پروژه آن را لازم کند.

UI نباید با timeout یا refresh از human gate عبور کند.

## action policy

هر action از server با این شکل به browser داده می‌شود:

```json
{
  "id": "retry_parse_with_mineru",
  "label": "تلاش دوباره با MinerU",
  "method": "POST",
  "endpoint": "/projects/p-123/sources/s-1/parse-runs",
  "enabled": true,
  "destructive": false,
  "requires_confirmation": false,
  "reason_disabled": null
}
```

Browser actionهای مجاز را حدس نمی‌زند. server بر اساس state و precondition آن‌ها را تولید می‌کند.

### actionهای ممنوع

- اجرای episode planning پیش از `CORPUS_READY`؛
- اجرای script پیش از وجود evidence pack معتبر؛
- علامت‌زدن دستی یک gate به‌عنوان pass؛
- تغییر مستقیم project state از فرم؛
- حذف artifact منفرد بدون invalidation plan؛
- retry با overwrite همان run record.

## idempotency و run identity

هر command اجرایی باید `run_id` جدید و یک idempotency key داشته باشد. اجرای دوباره یک POST در اثر refresh نباید دو job مستقل بسازد.

پیشنهاد:

```text
idempotency key = hash(project_id + stage + input_artifact_hashes + config_hash + client_nonce)
```

اگر همان درخواست فعال یا کامل‌شده وجود دارد، server باید نتیجه همان run را برگرداند؛ مگر operator صریحاً `force_new_attempt` بفرستد.

## تغییر upstream و stale شدن downstream

هر artifact باید input hashهای خود را ثبت کند. هنگام تغییر brief، duration، source selection یا parsed source:

1. server dependency graph را محاسبه می‌کند؛
2. UI فهرست artifactهای affected را نشان می‌دهد؛
3. operator تغییر را تأیید می‌کند؛
4. artifactهای downstream حذف نمی‌شوند، بلکه ابتدا `stale` علامت می‌خورند؛
5. rebuild موفق artifact جدید می‌سازد؛
6. cleanup قدیمی یک action جدا و کم‌اولویت است.

این رفتار امکان audit و مقایسه runها را حفظ می‌کند.

## run فعال و concurrency

نسخه اول فقط یک run mutating فعال برای هر پروژه دارد. action دوم باید با پاسخ conflict رد شود و UI run فعال را نشان دهد.

کارهای read-only مانند بازکردن transcript یا artifact inspector هم‌زمان مجازند.

قواعد:

- یک پروژه: حداکثر یک command mutating فعال؛
- یک source: حداکثر یک parse run فعال؛
- retry تا پایان یا interruption attempt قبلی مجاز نیست؛
- run متعلق به پروژه دیگر می‌تواند هم‌زمان اجرا شود، اگر resource policy اجازه دهد.

## interruption و stale heartbeat

هر run طولانی heartbeat ثبت می‌کند. اگر heartbeat از threshold عبور کند:

```text
running → interrupted
```

UI باید تفاوت این حالت‌ها را نشان دهد:

- process هنوز زنده است اما کند است؛
- service restart شده است؛
- provider call timeout شده است؛
- run record باز مانده ولی worker وجود ندارد.

`Mark as interrupted` فقط یک repair action مدیریتی است و نباید artifact ناقص را معتبر کند.

## cancel

Cancellation در نسخه اول best-effort است.

```text
running
→ cancel_requested
→ cancelled
```

اگر provider call قابل‌لغو نیست، UI توضیح می‌دهد که cancellation پس از پایان call اعمال می‌شود. artifact نیمه‌کاره نباید project state را جلو ببرد.

## polling و refresh

برای Local Operator UI، polling با HTMX کافی است:

- stage فعال: هر ۲ ثانیه؛
- project overview: هر ۵ ثانیه در زمان اجرای فعال؛
- در حالت idle polling متوقف شود؛
- browser visibility hidden نرخ polling را کاهش دهد.

WebSocket در نسخه اول لازم نیست. server-rendered partial باید از همان read model استفاده کند تا full page و polling fragment اختلاف state نداشته باشند.

## URL و refresh safety

- refresh صفحه نباید command را تکرار کند؛
- POST پس از موفقیت به GET redirect شود؛
- run page با run ID قابل bookmark باشد؛
- بازکردن URL run قدیمی باید banner «historical run» نشان دهد؛
- browser back نباید state project را تغییر دهد.

## consistency check هنگام load

هنگام بازکردن پروژه، server باید consistency سبک انجام دهد:

- artifact مورد انتظار وجود دارد؟
- hash ثبت‌شده با file content منطبق است؟
- project state بدون artifact لازم جلو نرفته است؟
- run فعال heartbeat معتبر دارد؟
- downstream artifact با input فعلی stale نیست؟

عدم تطابق باید به `blocked_by_failure` یا `review_recommended` تبدیل شود؛ نه اینکه با 500 خام پاسخ داده شود.

## نمایش warning

warningها سه سطح دارند:

```text
info       خروجی معتبر است؛ اطلاع مفید
review     خروجی معتبر است؛ بازبینی انسانی توصیه می‌شود
blocking   بدون تصمیم یا اصلاح، ادامه مجاز نیست
```

`blocking warning` از نظر execution failure نیست، اما attention state را `waiting_for_user` می‌کند.

## accessibility state

رنگ تنها حامل state نیست. هر badge باید label متنی و icon متمایز داشته باشد. برای stage فعال از `aria-live` محدود استفاده شود تا polling مداوم screen reader را مختل نکند.

## تست‌های پذیرش state model

حداقل تست‌های integration:

1. پروژه `DRAFT` فقط action ساخت brief دارد؛
2. parse failure retryable action معتبر تولید می‌کند؛
3. تغییر duration پس از episode plan، episode و script را stale می‌کند؛
4. دو POST تکراری با idempotency key یک run می‌سازند؛
5. run بدون heartbeat به interrupted تبدیل می‌شود؛
6. artifact ناقص project state را جلو نمی‌برد؛
7. project با human gate در dashboard به‌عنوان waiting نشان داده می‌شود؛
8. historical run primary action پروژه را تغییر نمی‌دهد؛
9. browser refresh command را تکرار نمی‌کند؛
10. یک پروژه دو run mutating هم‌زمان نمی‌پذیرد.
