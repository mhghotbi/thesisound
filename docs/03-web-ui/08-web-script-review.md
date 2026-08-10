# 08 — تأیید طرح، ساخت و بازبینی سناریو در وب

as-built؛ ادامهٔ مستقیم [`07-web-episode-planning.md`](07-web-episode-planning.md).

## هدف

این slice human gate میان `EPISODE_PLANNED` و `SCRIPT_DRAFTING` را واقعی می‌کند و pipeline موجود سناریوی فارسی را به رابط وب متصل می‌کند.

```text
EPISODE_PLANNED
→ explicit approval
→ persisted script run
→ grounded Persian draft
→ deterministic checks
→ independent verification
→ at most one targeted revision
→ SCRIPT_VERIFIED
```

## قواعد محصول

- مشاهده صفحه، approval یا run ایجاد نمی‌کند.
- approval فقط با POST و هویت session ثبت می‌شود.
- approval به hash دقیق Episode Plan متصل است.
- تغییر طرح approval را باطل می‌کند.
- هر artifact set marker همان plan hash را دارد؛ artifact نسخه دیگر reuse یا نمایش داده نمی‌شود.
- script generation بدون approval از CLI یا وب مجاز نیست.
- source خارج از corpus تأییدشده وارد checks نمی‌شود.
- retry artifactهای سالم را reuse می‌کند.
- glossary بدون manifest کامل، resumable محسوب نمی‌شود.
- UI درصد و ETA حدسی نمایش نمی‌دهد.
- این slice در `SCRIPT_VERIFIED` متوقف می‌شود.

## routeها

```text
GET  /projects/<id>/script
POST /projects/<id>/script/approve
POST /projects/<id>/script/retry
```

فرم approval روی صفحه Episode Plan نیز وجود دارد، اما endpoint و قرارداد approval در script subsystem متمرکز است.

## persistence

```text
<workspace>/<id>/episode/plan-approval.json
<workspace>/<id>/script-build-run.json
<workspace>/<id>/runs/script/<run-id>.json
<workspace>/<id>/script/approved-plan-hash.txt
<workspace>/<id>/script/...
```

`approved-plan-hash.txt` مرجع اتصال همه artifactهای resumable به نسخه طرح است. اگر marker وجود نداشته باشد یا با approval جاری یکسان نباشد، artifact set پاک و از ابتدا ساخته می‌شود.

## recovery

### failure پیش از شروع مدل

اگر approval با طرح جاری هم‌خوان نباشد، run fail می‌شود ولی project در `EPISODE_PLANNED` می‌ماند تا کاربر طرح جاری را دوباره تأیید کند.

### failure هنگام pipeline

project به `FAILED_RETRYABLE` می‌رود. retry:

- run ID جدید می‌سازد؛
- approval و marker نسخه طرح را دوباره validate می‌کند؛
- glossary، segment draft، checks و verification کامل را reuse می‌کند؛
- artifact نیمه‌ثبت‌شده را معتبر فرض نمی‌کند؛
- فقط مرحله ناقص را ادامه می‌دهد.

### restart و final-write reconciliation

runهای `queued/running` به failure صریح تبدیل می‌شوند، مگر اینکه project و artifactهای نهایی نشان دهند pipeline واقعاً به `SCRIPT_VERIFIED` رسیده است.

اگر project و artifactها کامل باشند، run pointer حتی اگر به‌علت شکست آخرین write روی `running` یا `failed` مانده باشد، به success reconcile می‌شود. اگر project `SCRIPT_VERIFIED` باشد ولی artifact معتبر وجود نداشته باشد، project می‌تواند وارد `FAILED_RETRYABLE` شود.

## صفحه بازبینی

صفحه `/script` نشان می‌دهد:

- stage واقعی اجرا؛
- approval actor و شناسه کوتاه plan hash؛
- word count و مدت تخمینی؛
- verdict کنترل قطعی؛
- verdict verifier و unsupported-claim ratio؛
- نسخه draft یا revised؛
- turnها بر اساس segment و speaker؛
- claim IDهای هر turn؛
- عنوان منبع، locator، evidence ID و excerpt هر reference.

صفحه فقط artifactهای متصل به plan hash جاری را نمایش می‌دهد.

## مرز بعدی

گام بعدی باید `SCRIPT_VERIFIED → AUDIO_GENERATING` باشد و شامل voice selection، chunking، TTS run persistence، audio assembly و QA واقعی صدا شود.
