# 04 — UX خطا و بازیابی Operator UI

مرتبط: تاکسونومی خطا (E1–E12) در این سند مرجع اصلی است و در as-built slices ([`05`](05-web-ui-auth-and-first-slice.md)–[`10`](10-local-live-e2e-runbook.md)) و [`../06-operations/03-production-sop.md`](../06-operations/03-production-sop.md) استفاده می‌شود.

## هدف

Thesisound یک pipeline طولانی با provider خارجی، model transform، parser، quality gate و artifactهای وابسته است. شکست در این سیستم استثنا نیست. UX باید خطا را به یک وضعیت تشخیص‌پذیر و قابل‌اقدام تبدیل کند، بدون اینکه جزئیات فنی را پنهان یا کاربر را به retry کور تشویق کند.

## اصول

### ۱. خطا باید محل، علت و اثر داشته باشد

پیام «Something went wrong» قابل‌قبول نیست. هر خطا باید مشخص کند:

- در کدام stage رخ داده؛
- چه چیزی شکست خورده؛
- چه artifactهایی ساخته یا ساخته نشده‌اند؛
- آیا downstream معتبر مانده است؛
- action پیشنهادی چیست.

### ۲. Retry همیشه پاسخ درست نیست

اگر corpus ناکافی، فایل encrypted یا claim بدون evidence است، retry همان ورودی فقط هزینه را تکرار می‌کند. UI باید میان retry، اصلاح ورودی، انتخاب strategy دیگر و توقف تمایز بگذارد.

### ۳. artifact ناقص معتبر نیست

وجود فایل به معنی موفقیت stage نیست. فقط artifactی که schema و quality gate را گذرانده و run record آن `passed` است، می‌تواند state را جلو ببرد.

### ۴. هیچ failure نباید history را overwrite کند

هر attempt run مستقل دارد. operator باید بتواند attemptها را مقایسه کند و بفهمد کدام ورودی یا provider تغییر کرده است.

### ۵. recovery باید محدود و قابل‌ممیزی باشد

skip gate، edit state و دستکاری raw artifact recovery محسوب نمی‌شوند. actionهای recovery باید application command رسمی باشند.

---

## taxonomy خطا

| کد | نمونه‌ها | recovery |
|---|---|---|
| **E1** Input validation | title خالی، duration خارج از بازه، mode نامعتبر، فایل unsupported یا بیش از limit | اصلاح مستقیم field یا انتخاب فایل دیگر. run ساخته نمی‌شود مگر validation نیازمند inspection backend باشد |
| **E2** File/document inspection | PDF رمزگذاری‌شده، فایل corrupt، ناسازگاری MIME با extension، از دست رفتن دسترسی، تغییر hash هنگام read | upload مجدد یا حذف منبع (و ارائهٔ password اگر روزی پشتیبانی شد). retry خودکار محدود است |
| **E3** Parser execution | crash پارسر، نبودن MinerU CLI در PATH، timeout، out-of-memory، خروجی نامعتبر parser | retry همان parser برای خطای گذرا، parser دیگر، کاهش resource demand یا رفع dependency |
| **E4** Parse quality gate | پوشش کم متن، ترتیب خواندن نامعتبر، OCR فارسی ضعیف، صفحه‌های خالی زیاد، از بین رفتن heading | parser/OCR دیگر، preview و تصمیم انسانی، یا رد منبع. **retry با همان strategy توصیه نمی‌شود** |
| **E5** Provider/configuration | نبود API key، model ID نامعتبر، quota یا rate limit، outage provider، timeout شبکه | رفع config، retry با backoff، provider/model جایگزین در صورت سازگاری contract |
| **E6** Structured model output | JSON/schema نامعتبر، پاسخ ناقص، prompt leakage، finish reason نامناسب، اتمام repair budget | schema repair محدود، attempt جدید، مدل سازگار دیگر، یا اصلاح prompt contract توسط توسعه‌دهنده |
| **E7** Deterministic validation | نبودن excerpt در block، locator نامعتبر، claim ID ناشناخته، evidence خارج از pack، claim تکراری، شکستن ترتیب prerequisite | rebuild هدفمند از نزدیک‌ترین stage upstream. **UI نباید اجازهٔ pass دستی بدهد** |
| **E8** Corpus insufficiency | ناکافی بودن شواهد معتبر برای مدت هدف، پوشش‌نداشتن مفهوم must-include، منبع فقط metadata، باقی‌ماندن gap مادی | کاهش duration، افزودن منبع، تغییر brief یا توقف. **این وضعیت failure provider نیست** |
| **E9** Script verification | claim بدون پشتوانه، انتساب اشتباه، ناسازگاری glossary، تکرار، اختلاف duration، prompt leakage | revision هدفمند فقط برای turnهای مسئله‌دار، سپس checks و verifier دوباره. پس از سقف revision پروژه blocked می‌شود |
| **E10** Audio generation/QA | شکست synthesis، segment بریده، جابه‌جایی گوینده، خطای تلفظ، افتادگی در ASR، WAV نامعتبر، شکست assembly در FFmpeg | بازتولید segment معیوب، اجرای دوبارهٔ QA یا رفع dependency. کل audio فقط با تغییر global voice config rebuild می‌شود |
| **E11** Artifact integrity | artifact حذف‌شده، hash mismatch، JSON خراب، ارجاع manifest به run ناموجود، جلوتر بودن state از artifact معتبر | rebuild از آخرین ancestor معتبر، restore از backup، یا blocked کردن پروژه. **overwrite خام مجاز نیست** |
| **E12** Interrupted/stale | restart سرویس، توقف heartbeat، crash worker، بسته‌شدن مرورگر با ادامهٔ job، باز ماندن run record | reconcile کردن وضعیت worker، علامت‌زدن interrupted در صورت قطعی‌بودن، سپس resume یا retry |

---

## ساختار ErrorRecord

هر خطای قابل‌نمایش باید structured باشد:

```json
{
  "error_id": "err_01H...",
  "code": "PARSE_LOW_TEXT_COVERAGE",
  "category": "parse_quality_gate",
  "severity": "blocking",
  "stage": "document_parse",
  "project_id": "p-123",
  "source_id": "s-1",
  "run_id": "r-9",
  "summary_fa": "متن کافی از این PDF استخراج نشد.",
  "impact_fa": "این منبع هنوز نمی‌تواند وارد corpus شود.",
  "recommended_action": "retry_with_alternate_parser",
  "retryable": true,
  "technical_details": {
    "parser": "docling",
    "text_coverage": 0.18,
    "threshold": 0.60
  },
  "created_at": "2026-08-08T10:30:00Z"
}
```

stack trace و provider raw response می‌توانند در diagnostic attachment باشند، اما لازم نیست در ErrorRecord سطح اول قرار بگیرند.

## anatomy پنل خطا

ترتیب نمایش:

1. **چه اتفاقی افتاد؟** جمله کوتاه و مشخص؛
2. **اثر چیست؟** آیا stage یا کل پروژه متوقف شده؛
3. **چرا؟** یک دلیل قابل‌فهم یا «علت هنوز مشخص نیست»؛
4. **پیشنهاد اصلی:** یک primary recovery action؛
5. **گزینه‌های دیگر:** حداکثر دو secondary action؛
6. **جزئیات فنی:** error code، run ID، metrics و logs؛
7. **artifact status:** چه چیزی معتبر یا ناقص است.

toast برای failure اصلی کافی نیست. toast فقط نتیجه action کوتاه مانند «تنظیم ذخیره شد» را نشان می‌دهد.

## recovery matrix

| وضعیت | primary action | secondary action | retry خودکار |
|---|---|---|---|
| network timeout | retry same inputs | change provider/model | محدود |
| rate limit | retry after backoff | stop run | بله، محدود |
| missing API key | open settings | copy diagnostic | خیر |
| parser crash | retry parser | alternate parser | یک بار برای transient |
| low parse quality | alternate parser | reject source | خیر |
| invalid model schema | schema repair/retry | inspect response | محدود |
| invalid evidence locator | rebuild evidence | inspect block | خیر |
| insufficient corpus | reduce duration | add source/edit brief | خیر |
| verifier issue | targeted revision | inspect evidence | حداکثر طبق policy |
| artifact hash mismatch | rebuild from ancestor | inspect diagnostics | خیر |
| interrupted worker | reconcile/retry | mark interrupted | خیر |
| audio segment defect | regenerate segment | inspect ASR diff | محدود به segment |

## انواع retry

### Retry same inputs

همان input hashes، config و strategy؛ attempt جدید. مناسب transient failure.

### Retry with changed strategy

مثلاً parser دیگر یا model compatible دیگر. UI باید تفاوت config را پیش از اجرا نشان دهد.

### Rebuild from stage

artifactهای downstream را stale می‌کند و از یک stage مشخص دوباره می‌سازد. impact summary اجباری است.

### Force new attempt

حتی اگر idempotency match موجود است attempt جدید می‌سازد. action پیشرفته و کم‌اولویت؛ باید دلیل operator ثبت شود.

### Resume

برای stageهایی که checkpoint معتبر دارند. Resume نباید با retry از ابتدا یکسان نمایش داده شود.

## retry budget

UI باید سقف retry خودکار و دستی را نشان دهد. نمونه:

```text
Attempt 2 of 3
```

پس از تمام‌شدن budget:

- primary action نباید باز هم `Retry` باشد؛
- باید strategy change، config fix یا developer inspection پیشنهاد شود؛
- force retry در بخش advanced باقی بماند.

## corpus insufficiency UX

این یکی از مهم‌ترین failure modeهای محصول است و نباید به خطای عمومی تبدیل شود.

نمونه پیام:

> این corpus برای اپیزود ۲۵ دقیقه‌ای evidence کافی ندارد. برآورد فعلی حدود ۱۸ دقیقه محتوای معتبر است. ادامه با padding یا تکرار مجاز نیست.

Primary action بر اساس کم‌هزینه‌ترین اصلاح:

- `Reduce duration to 18 minutes`
- یا `Add another source`

همچنین باید gapهای material و must-includeهای بی‌پشتوانه نمایش داده شوند.

## Parse Quality UX

نمونه:

> Docling فایل را parse کرد، اما فقط ۱۸٪ صفحات متن قابل‌استفاده دارند. این خروجی وارد corpus نشده است.

Actionها:

- `Try MinerU`
- `Preview extracted text`
- `Reject source`

دکمه `Accept anyway` در نسخه اول وجود ندارد، مگر quality policy بعداً یک human override ثبت‌شده تعریف کند.

## Model/provider UX

پیام provider نباید عیناً به کاربر اصلی نمایش داده شود. UI یک summary پایدار می‌دهد و raw provider code را در details می‌گذارد.

نمونه:

> Gemini در زمان مجاز پاسخ نداد. هیچ artifact جدیدی معتبر نشده است.

Details:

```text
provider_error=DEADLINE_EXCEEDED
attempt=2
elapsed=90s
input_hash=...
```

## Verification UX

Issueها باید actionable و traceable باشند:

- rule؛
- segment/turn؛
- claim/evidence؛
- توضیح؛
- severity؛
- suggested repair scope.

نمونه:

> Turn 14 ادعایی درباره تاریخ انتشار دارد، اما evidence متصل فقط درباره محتوای کتاب است. این turn نیاز به revision دارد.

Primary action:

`Revise 1 failed turn`

نه `Regenerate script`.

## تغییر destructive

پیش از actionی که downstream را invalidate می‌کند، impact summary نشان داده شود:

```text
Changing duration from 25 to 10 minutes will mark these artifacts stale:
- analysis profile
- evidence extraction plan
- claim priorities
- episode plan
- evidence packs
- script and verification

Parsed document and stable block IDs remain valid.
```

Confirmation باید نام project و action را روشن بگوید. برای حذف کامل پروژه، تایپ title یا project ID قابل‌قبول است؛ برای تغییر عادی duration لازم نیست friction مصنوعی ایجاد شود.

## interrupted run UX

اگر UI پس از restart runی با heartbeat قدیمی ببیند:

1. ابتدا worker/provider state را reconcile کند؛
2. تا زمان نتیجه، banner `Checking interrupted run` نشان دهد؛
3. اگر artifact نهایی معتبر پیدا شد، run را recover و passed کند؛
4. اگر artifact ناقص است، run را interrupted و retry را فعال کند؛
5. project lifecycle بر اساس حدس جلو نرود.

## data loss prevention

- formهای brief unsaved-change warning داشته باشند؛
- upload کامل‌شده پیش از parse persist شود؛
- cancellation artifact معتبر قبلی را پاک نکند؛
- rebuild ابتدا artifact جدید بسازد و سپس current pointer را جابه‌جا کند؛
- cleanup history action جدا داشته باشد؛
- raw user source بدون action صریح حذف نشود.

## diagnostic bundle

Operator باید بتواند diagnostic bundle بدون source text حساس بسازد:

- project ID و state؛
- run record؛
- error records؛
- config names بدون secret؛
- artifact hashes و paths؛
- dependency availability؛
- package version و commit SHA؛
- provider request metadata بدون prompt/source content.

گزینه include sensitive content باید جدا و خاموش باشد.

## logging و privacy

- API key و secret هرگز log نشود؛
- rendered prompt طبق policy پیش‌فرض ذخیره نشود؛
- source excerpt در error summary حداقل باشد؛
- provider raw response می‌تواند copyrighted/private text داشته باشد و باید محدود شود؛
- copy diagnostic باید redaction report نشان دهد.

## نمونه متن‌های UI

### retryable

> اجرای استخراج evidence به‌دلیل timeout متوقف شد. ورودی‌ها سالم‌اند و artifact ناقصی معتبر نشده است.

Primary: `Try again`

### configuration

> مدل متنی پیکربندی نشده است. پیش از ساخت Research Brief، متغیر محیطی provider را تنظیم کنید.

Primary: `Open settings`

### permanent source issue

> این PDF رمزگذاری شده و در وضعیت فعلی قابل‌خواندن نیست.

Primary: `Remove source`

### stale result

> Research Brief پس از ساخت این Episode Plan تغییر کرده است. plan فعلی برای مقایسه قابل مشاهده است، اما برای ادامه معتبر نیست.

Primary: `Rebuild episode`

## telemetry محلی پیشنهادی

حتی در ابزار شخصی، این counters برای اصلاح UX مفیدند:

- failure count بر اساس category/stage؛
- retry success rate؛
- تعداد force retry؛
- time-to-recovery؛
- تعداد invalidationهای downstream؛
- stageهایی که بیشترین manual intervention دارند؛
- parse strategy success بر اساس document type؛
- verifier issues بر اساس rule.

این telemetry می‌تواند local و aggregate باشد؛ source text نباید وارد آن شود.

## معیار پذیرش

- هر error category recovery action مشخص دارد؛
- هیچ blocking failure فقط در toast نمایش داده نمی‌شود؛
- retry attempt قبلی را overwrite نمی‌کند؛
- corpus insufficiency از provider failure متمایز است؛
- تغییر destructive impact summary دارد؛
- operator می‌تواند از آخرین artifact معتبر rebuild کند؛
- diagnostic bundle secret و source text را به‌صورت پیش‌فرض حذف می‌کند؛
- UI پس از service restart runهای interrupted را reconcile می‌کند؛
- action `Accept anyway` بدون policy ثبت‌شده وجود ندارد؛
- targeted recovery بر full regeneration مقدم است.
