# 29 — ممیزی UI/UX رابط وب Thesisound

تاریخ: ۲۰۲۶-۰۸-۰۸ · مبنا: کد فعلی `src/thesisound/web/` روی branch `main` · اسناد مرجع: PRODUCT.md، DESIGN.md، docs/16–20

---

## Executive verdict

رابط فعلی **از نظر صداقت با state بسیار بهتر از میانگین محصولات مشابه است** (بدون درصد جعلی، gateهای صریح، PRG، CSRF، preflight پیش از مصرف API) اما **به‌عنوان یک محصول قابل‌استفاده برای دانشجوی علوم انسانی هنوز قابل‌قبول نیست**. پنج مشکل بنیادی، نه cosmetic:

1. **ناوبری دوگانه و متناقض.** هر صفحه هم یک `workflow-switcher` سراسری دارد و هم یک `step-rail` دست‌نویس که تعداد و نام مراحلش صفحه‌به‌صفحه عوض می‌شود (۴ مرحله → ۵ مرحله با نام‌های متفاوت). کاربر هیچ نقشه ثابتی از سفر ندارد و Project Overview (S-03 در docs/18) اصلاً پیاده نشده است.
2. **حذف منبع، حذف واقعی و بی‌بازگشتِ فایل خام کاربر با یک POST بدون هیچ تأیید است** — در حالی که متن UI در همان صفحه قول می‌دهد «فایل‌های خام شما حذف نمی‌شوند». نقض مستقیم docs/19 (impact summary) و data-loss prevention.
3. **جداسازی Simple/Operator وجود ندارد.** status خام انگلیسی، verdict داخلی، plan hash، turn ID و evidence ID و نسبت unsupported claims در سطح اول همان UIای نمایش داده می‌شوند که برای دانشجوی علوم انسانی طراحی شده؛ صفحه فنی system-check هم در ناوبری اصلی است.
4. **Polling یعنی reload کامل صفحه هر ۳ ثانیه.** scroll، focus، `<details>` باز و context صفحه‌خوان هر ۳ ثانیه نابود می‌شود. HTMX در base.html لود شده اما در هیچ template حتی یک attribute از آن استفاده نشده است.
5. **State نمایشی در یک مورد واقعاً غلط است:** منطق تعیین مرحله جاری در `processing.html` وارونه است — مرحله جاری واقعی هیچ نشانه‌ای نمی‌گیرد و مراحل بعدیِ منتظر، همگی `is-current` می‌شوند.

طراحی بصری پایه (app.css) به DESIGN.md وفادار و از کلیشه‌های AI dashboard دور است؛ مشکل اصلی معماری اطلاعات، state و recovery است، نه رنگ.

---

## محدودیت‌های شواهد (Evidence limits)

- **برنامه اجرا نشده است.** این محیط امکان اجرای FastAPI/uvicorn را ندارد. بنابراین این سند برای همه یافته‌ها **code review** است، نه visual audit زنده. مسیرهای ۱–۱۴ خواسته‌شده (ورود تا resume) روی کد و template دنبال شده‌اند، نه در browser.
- به جای screenshot زنده، **بازسازی وفادار صفحه‌ها از روی template و app.css** در فایل پروژه «Thesisound Current UI.dc.html» (۸ صفحه/state) ساخته و بازبینی شده است. هر یافته‌ای که فقط با اجرای واقعی قابل‌تأیید است (رفتار polling زیر load، focus order واقعی، رفتار back/refresh با session) صریحاً با برچسب «نیازمند اجرای زنده» علامت خورده است.
- تست‌های `test_web_*` خوانده شده‌اند اما **اجرا نشده‌اند**؛ ادعای pass/fail نمی‌شود.
- این مخزن به‌صورت فقط‌خواندنی mount شده؛ تغییر کد مستقیم در repo از این محیط ممکن نیست. اصلاح‌ها به‌صورت spec دقیق (docs/30) و طراحی مرجع تحویل می‌شوند.

## Screenshot / recreation inventory

| # | صفحه/State | منبع بازسازی | وضعیت |
|---|---|---|---|
| 01 | ورود (شماره موبایل) | `auth/login.html` | بازسازی‌شده |
| 02 | تأیید کد OTP | `auth/verify.html` | بازسازی‌شده |
| 03 | فهرست پروژه‌ها + empty state | `projects/index.html` | بازسازی‌شده |
| 04 | پروژه جدید | `projects/new.html` | بازسازی‌شده |
| 05 | تأیید برداشت (باز و locked) | `projects/brief.html` | بازسازی‌شده |
| 06 | منابع (خالی، ready، review، locked) | `projects/sources.html` | بازسازی‌شده |
| 07 | پردازش (running، failed) | `projects/processing.html` | بازسازی‌شده |
| 08 | طرح اپیزود (blocked، planned) | `projects/episode.html` | بازسازی‌شده |
| 09 | سناریو (verified) | `projects/script.html` | بازسازی‌شده |
| 10 | صوت | `projects/audio.html` | code review فقط |
| 11 | آمادگی اجرا | `system-check.html` | بازسازی‌شده |
| — | interruption / browser back / refresh زیر run فعال | — | **blocked: نیازمند اجرای زنده** |

---

## ماتریس تطبیق spec ↔ implementation

| Flow/Screen | الزام محصول/سند | پیاده‌سازی فعلی | Gap | Severity |
|---|---|---|---|---|
| Project Overview | docs/18 S-03: نقشه وضعیت + action بعدی در `/projects/{id}` | **وجود ندارد**؛ فهرست پروژه‌ها مستقیم به میانه یک stage لینک می‌دهد | کاربر برگشته هیچ نمای کلی ندارد | **P0** |
| ناوبری پروژه | docs/16: شش تب ثابت، disabled با توضیح | دو سیستم موازی: workflow-switcher + step-rail دست‌نویس ناسازگار (۴ یا ۵ مرحله، نام‌های متفاوت در new/sources/episode/script/audio) | نقشه سفر ناپایدار؛ «تأیید برداشت» در script/audio از rail حذف می‌شود | **P0** |
| سه محور state | docs/17: lifecycle / execution / attention جدا | `read_models.py` همه را در یک label+tone فشرده می‌کند؛ badge وضعیت run خام انگلیسی کنار عنوان فارسی | passed_with_warnings، stale، interrupted اصلاً قابل‌نمایش نیستند | **P0** |
| مرحله جاری پردازش | progress واقعی | منطق `is-current` در `processing.html` وارونه است (سطر ۲۶) | نمایش state غیرواقعی | **P0** |
| Polling | docs/17: HTMX partial، حفظ scroll/focus، توقف در idle | `window.location.reload()` هر ۳s در ۴ صفحه؛ HTMX لود شده و استفاده نشده | reset کامل صفحه، شکستن a11y و فرم/disclosure باز | **P0** |
| حذف منبع | docs/18-19: impact summary اجباری، بدون one-click delete | POST مستقیم + `shutil.rmtree` روی uploads (source_routes.py ~۳۷۸) بدون confirmation؛ دکمه «حذف منبع» هم‌وزن «حذف از مجموعه» کنار هم | حذف بی‌بازگشت فایل خام با یک کلیک اشتباه؛ تناقض با متن UI «فایل‌های خام حذف نمی‌شوند» | **P0** |
| Simple/Operator | PRODUCT.md: دانشجو نباید parser/run/hash ببیند | یک UI واحد: `{{ corpus_run.status }}` خام، `{{ checks.verdict }}`، `plan_hash[:12]`، turn_id، evidence_id، «اپیزود صوتی verified آماده است»، system-check در nav اصلی | مرز mode فقط در حد یک `<details>` جزئیات فنی است | **P0** |
| Error UX | docs/19: ErrorRecord ساختاریافته، anatomy هفت‌بخشی | `last_error` خام (شامل پیام exception/provider) مستقیم render می‌شود؛ `workflow_error` از query param خوانده و نمایش داده می‌شود؛ recovery همیشه فقط «تلاش دوباره» | تفکیک E1–E12، retry budget و strategy جایگزین وجود ندارد | **P1** |
| Form errors | DESIGN.md: خطا کنار field | همه خطاها فقط banner بالای صفحه؛ در `new.html` پس از خطا فقط topic بازیابی می‌شود و انتخاب‌های audience/duration/mode به پیش‌فرض reset می‌شوند | داده کاربر از بین می‌رود | **P1** |
| Brief | docs/18 S-04: Save≠Confirm، diff، fieldهای کامل | Save/Confirm جدا ✓؛ اما learning objectives و audience قابل‌ویرایش نیستند و diff وجود ندارد | جزئی، پذیرفتنی برای slice | P2 |
| Corpus gate | حداقل یک source عبور کرده | دکمه تأیید با `selected_count==0` غیرفعال ✓؛ اما دلیل غیرفعال بودن به دکمه متصل نیست و جمله «بر اساس 0 منبع…» با رقم لاتین render می‌شود | توضیح disabled و ارقام | P1 |
| Insufficient corpus | بدون «Continue anyway»، کاهش مدت/افزودن منبع | پیاده شده ✓ (episode.html blocked) — بهترین صفحه فعلی | ترتیب actionها و لحن قابل بهبود | P2 |
| Historical run / stale | banner historical، stale label | هیچ نمایشی از stale/historical وجود ندارد؛ صفحه script کاملاً به run record آخری گیت شده و پس از restart ممکن است محتوای معتبر پنهان شود | **نیازمند اجرای زنده برای تأیید رفتار restart** | P1 |
| Mobile | reflow، دسترسی ناوبری | `.app-nav { display:none }` در ≤760px بدون هیچ جایگزین (منو/همبرگر) | مسیر «پروژه جدید» و system-check در موبایل گم می‌شود | P1 |
| a11y live region | docs/17: aria-live محدود برای stage فعال | هیچ `aria-live` در کل codebase نیست (grep: صفر نتیجه) | screen reader از reload هم آسیب می‌بیند | P1 |

---

## یافته‌ها — P0 (Blocking)

### F-01 · حذف بی‌بازگشت منبع بدون تأیید و با copy متناقض
- **Screen/state:** منابع؛ هر source
- **Evidence:** `source_routes.py` سطرهای ~۳۶۱–۳۹۷: `delete_source` سه `shutil.rmtree` روی uploads و artifactها اجرا می‌کند. `sources.html`: دکمه «حذف منبع» با استایل `button--quiet` بلافاصله کنار «حذف از مجموعه». `_workflow_navigation.html` سطر ۲۸: «فایل‌های خام شما حذف نمی‌شوند.»
- **Problem:** destructive action واقعی (پاک‌شدن فایل کاربر از دیسک) بدون confirmation، بدون impact summary، هم‌وزن یک toggle بی‌خطر، و در تضاد با قول متنی UI.
- **User impact:** از دست رفتن دائمی فایل منبع (شاید تنها نسخه کاربر) با یک کلیک اشتباه؛ دو دکمه مجاور هر دو با واژه «حذف» شروع می‌شوند.
- **Root cause:** الگوی POST-redirect بدون لایه confirmation؛ نبود `ImpactSummary` که docs/19 الزام کرده.
- **Recommended change:** صفحه/دیالوگ تأیید GET-رندر با نام فایل، اثر downstream (اگر در corpus بوده) و دکمه danger صریح؛ تغییر label toggle به «کنار گذاشتن از اپیزود / افزودن به اپیزود»؛ حذف فایل خام فقط پس از تأیید، یا soft-delete با پاک‌سازی جدا.
- **Acceptance criteria:** هیچ مسیر یک‌کلیکی به rmtree نمی‌رسد؛ تست: POST بدون توکن تأیید ⇒ 4xx؛ label دو action شباهت واژگانی ندارند.

### F-02 · دو سیستم ناوبری موازی و step rail ناسازگار
- **Screen/state:** همه صفحات پروژه
- **Evidence:** `base.html` هر صفحه پروژه‌دار `_workflow_navigation.html` (۶ لینک pill + کنترل rewind) را می‌کشد؛ همان صفحه یک `step-rail` hard-code شده هم دارد. شمارش: new/brief/sources/processing = ۴ مرحله («تعریف هدف، تأیید برداشت، منابع، پردازش»)؛ episode = ۵ («…مجموعه شواهد، طرح اپیزود»)؛ script = ۵ اما «تأیید برداشت» حذف شده؛ audio = ۵ با نام‌های کوتاه‌شده متفاوت («هدف، منابع، طرح، سناریو، صوت»). دو فایل CSS با دو زبان بصری (`app.css` توکن‌های سبز/کاغذی؛ `workflow.css` خاکستری generic با `#1f2937` و radius 14).
- **Problem:** کاربر هم‌زمان دو نقشه متفاوت از یک سفر می‌بیند که با هم و با خودشان در صفحات مختلف تناقض دارند؛ Simple Mode هرگز کل سفر (صوت/شنیدن) را در ابتدای مسیر نشان نمی‌دهد.
- **User impact:** پاسخ «الان کجام؟ چند مرحله مانده؟» در هر صفحه فرق می‌کند؛ اعتماد از بین می‌رود.
- **Root cause:** step rail در هر template کپی-دستی شده؛ workflow-switcher بعداً و با CSS جدا اضافه شده.
- **Recommended change:** یک component سراسری `StepRail` با ۶ مرحله ثابت (هدف/برداشت → منابع → پردازش → طرح → سناریو → شنیدن) که از read model وضعیت هر مرحله (complete/current/locked+دلیل) را می‌گیرد؛ حذف workflow.css و ادغام rewind در همان rail؛ حذف همه railهای دست‌نویس.
- **Acceptance criteria:** یک include واحد؛ تعداد/نام مراحل در همه صفحات یکسان؛ تست snapshot برای هر lifecycle state.

### F-03 · منطق وارونه «مرحله جاری» در فهرست مراحل پردازش
- **Screen/state:** پردازش؛ stage-list
- **Evidence:** `processing.html` سطر ۲۶: `{% if complete %}…{% elif loop.first or not stages[loop.index0 - 1][1] %}is-current{% endif %}`. برای stages=[✓, جاری, بعدی]: مرحله «جاری» (قبلی‌اش complete) شرط `not True` را false می‌کند و **هیچ class نمی‌گیرد**؛ مرحله «بعدی» (قبلی‌اش ناتمام) `is-current` می‌گیرد.
- **Problem:** دقیقاً همان «state غیرواقعی» که PRODUCT.md ممنوع کرده: مرحله در انتظار به‌عنوان جاری نمایش داده می‌شود و مرحله جاری بی‌نشان می‌ماند؛ چند li هم‌زمان is-current می‌شوند.
- **Recommended change:** شرط به `stages[loop.index0 - 1][1] و not complete` اصلاح شود و فقط اولین مرحله ناتمام current باشد (بهتر: index مرحله جاری در route محاسبه شود).
- **Acceptance criteria:** تست template/DOM: دقیقاً یک `is-current` و آن هم اولین ناتمام.

### F-04 · Polling با reload کامل صفحه
- **Screen/state:** پردازش، طرح اپیزود، سناریو، صوت — در حالت running
- **Evidence:** `<script>window.setTimeout(() => window.location.reload(), 3000)</script>` در ۴ template؛ htmx در base.html لود می‌شود ولی grep برای `hx-` صفر نتیجه دارد؛ هیچ `aria-live` وجود ندارد.
- **Problem:** هر ۳ ثانیه scroll و focus صفر می‌شود، `<details>` بازِ «ردیابی شواهد» و «جزئیات فنی» بسته می‌شود، صفحه‌خوان از نو شروع می‌کند، و در tab پس‌زمینه هم reload ادامه دارد.
- **User impact:** خواندن هر چیزی در حین run فعال عملاً ناممکن است؛ همان صفحه‌ای که کاربر باید در آن صبور بماند، خواندنی نیست.
- **Root cause:** میان‌بر پیاده‌سازی؛ زیرساخت HTMX آماده ولی متصل‌نشده.
- **Recommended change:** بخش وضعیت run در یک fragment (`/…/processing/fragment`) از همان read model؛ `hx-get` با `hx-trigger="every 2s"` فقط وقتی run فعال است + توقف در `visibilitychange`؛ `aria-live="polite"` فقط روی سطر عنوان مرحله. (مطابق stack فعلی؛ مهاجرت لازم نیست.)
- **Acceptance criteria:** در حالت running، document reload نمی‌شود (تست: مقدار input آزمایشی و باز بودن details حفظ شود)؛ polling در idle متوقف است.

### F-05 · نبود Project Overview و ورود از فهرست به میانه flow
- **Screen/state:** فهرست پروژه‌ها → پروژه
- **Evidence:** `app.py` هیچ route ای برای `/projects/{id}` ندارد؛ `read_models.py` برای هر state یک URL عمقی (brief/sources/episode/…) می‌سازد.
- **Problem:** S-03 (docs/18) پیاده نشده. کاربری که بعد از یک هفته برمی‌گردد مستقیماً وسط یک فرم یا صفحه وضعیت فرود می‌آید، بدون «چه شد، کجاییم، چه مانده».
- **Recommended change:** route `/projects/{id}` با: عنوان + سؤال مرکزی، StepRail کامل، پنل «اقدام لازم» (از attention state)، آخرین run، و لینک مراحل. فهرست پروژه‌ها به overview لینک بدهد؛ primary action داخل overview بماند.
- **Acceptance criteria:** هر state ای از پروژه در overview یک primary action روشن دارد؛ تست navigation موجود (`test_web_search_and_navigation.py`) به‌روزرسانی شود.

### F-06 · نشت اطلاعات Operator به سطح اول Simple Mode
- **Screen/state:** پردازش، طرح، سناریو، صوت، منابع، فهرست
- **Evidence:** `{{ corpus_run.status }}` / `{{ planning_run.status }}` / `{{ script_run.status }}` / `{{ audio_run.status }}` خام و انگلیسی به‌عنوان badge کنار عنوان بخش؛ `{{ checks.verdict }}` و `{{ verification.verdict }}` خام؛ «شناسه نسخه: {{ approval.plan_hash[:12] }}»؛ `{{ item.turn.turn_id }}` و evidence_id در سطح اول هر turn؛ «نسبت ادعاهای بدون پشتوانه: ٪…»؛ read_models.py: «اپیزود صوتی verified آماده است»؛ base.html: لینک «آمادگی اجرا» (system-check با PASS/FAIL و `scope=` و `uv run thesisound doctor`) در ناوبری اصلی همه کاربران؛ sources.html: «quality-gate می‌شود»، «candidate می‌سازد».
- **Problem:** PRODUCT.md صریح است: دانشجو نباید run status، hash، ID و verdict داخلی را بفهمد. این‌ها الان نه در drawer، که در header بخش‌ها هستند.
- **Recommended change:** واژه‌نامه نمایش فارسی برای هر status/verdict (نگاشت در read model، نه template)؛ hash/ID/ratio به `TechnicalDetails` منتقل شود؛ system-check از nav اصلی به footer یا حالت پیشرفته برود؛ ورود به «حالت پیشرفته» صریح و برگشت‌پذیر (toggle در header با ذخیره در session).
- **Acceptance criteria:** در حالت ساده، هیچ رشته انگلیسیِ status/verdict/hash در سطح اول DOM نیست (تست DOM)؛ همان داده در حالت پیشرفته موجود است.

### F-07 · خطای خام و recovery تک‌گزینه‌ای
- **Screen/state:** همه stateهای failed
- **Evidence:** `{{ corpus_run.last_error }}`، `{{ planning_run.last_error }}`، `{{ script_run.last_error }}`، `{{ audio_run.last_error }}` مستقیم render می‌شوند (متن exception/provider)؛ read_models.py سطر ~۱۲۵ همان `project.last_error` را attention label فهرست می‌کند؛ `_workflow_navigation.html` متن خطا را از `?workflow_error=` (قابل جعل در URL) می‌خواند؛ recovery در همه صفحات فقط «تلاش دوباره» است — بدون تفکیک E1–E12، بدون retry budget، بدون strategy جایگزین.
- **Problem:** anatomy هفت‌بخشی docs/19 (چه شد/اثر/چرا/پیشنهاد/گزینه‌ها/جزئیات/وضعیت artifact) پیاده نشده؛ کاربر اصلی متن فنی می‌بیند و کاربری که خطایش retryable نیست هم فقط دکمه retry دارد.
- **Recommended change:** `ErrorRecoveryPanel` واحد که از ErrorRecord ساختاریافته (کد، دسته، summary_fa، impact_fa، recommended_action، retryable) تغذیه شود؛ raw text فقط داخل TechnicalDetails؛ پیام‌های flash از session نه از query param.
- **Acceptance criteria:** هیچ `last_error` خام در سطح اول؛ برای حداقل خطاهای پرتکرار (timeout، missing key، low parse quality، insufficient corpus) پیام و action متمایز؛ تست: پیام جعلی در URL render نمی‌شود.

---

## یافته‌ها — P1 (High impact)

### F-08 · خطای فرم فقط banner + از بین رفتن انتخاب‌های کاربر
`app.py create_project`: پس از ValueError فقط `values.topic` به template برمی‌گردد و در `new.html` هم فقط textarea از values استفاده می‌کند؛ audience/prior/duration/mode به پیش‌فرض reset می‌شوند. هیچ template ای خطای field-level ندارد (الزام DESIGN.md).
**اصلاح:** بازگرداندن و بازانتخاب همه valueها؛ پیام خطا زیر field مربوط + `aria-describedby`. **پذیرش:** پس از خطا هیچ ورودی کاربر از بین نمی‌رود.

### F-09 · سه محور state در یک badge فشرده شده
`read_models.py` فقط lifecycle را به label/tone نگاشت می‌کند؛ execution state (running/interrupted/passed_with_warnings/stale) و attention state جدا وجود ندارند. `FAILED_RETRYABLE` و `FAILED_PERMANENT` هر دو «مشاهده مشکل»‌اند؛ interrupted و stale اصلاً قابل‌نمایش نیستند.
**اصلاح:** StatusLabel دو-جزئی (وضعیت مرحله + نیاز به اقدام) طبق docs/17؛ محاسبه attention در server. **پذیرش:** passed_with_warnings و stale نمایش متمایز دارند.

### F-10 · RTL/bidi و ارقام
- `sources.html`: «مشاهده URL اصلی» داخل `<bdi dir="ltr">` — **متن فارسی به‌اجبار LTR** render می‌شود.
- دو نظام رقم مخلوط: step rail با ارقام فارسی (۱۲۳۴)، ولی «{{ minutes }} دقیقه»، «{{ selected_count }} منبع»، شمارنده‌ها و درصدها با رقم لاتین.
- تاریخ میلادی خام `%Y-%m-%d %H:%M` داخل جمله فارسی؛ نه جلالی است نه isolation دارد.
- «اپیزود صوتی verified آماده است» — واژه انگلیسی وسط جمله فارسی بدون bdi.
- brand mark «▥» یک glyph موقت است.
**اصلاح:** حذف dir=ltr از label فارسی؛ یک قاعده واحد ارقام (پیشنهاد: رقم فارسی در متن، رقم لاتین فقط برای identifier/URL داخل bdi)؛ تاریخ جلالی با `<time>` و isolation. **پذیرش:** بازبینی صفحه‌به‌صفحه با checklist bidi؛ هیچ label فارسی LTR نیست.

### F-11 · موبایل: ناوبری حذف می‌شود
`app.css` در ≤760px: `.app-nav { display:none; }` بدون منوی جایگزین؛ «پروژه جدید» فقط از دکمه داخل صفحه فهرست در دسترس می‌ماند و workflow-switcher + step-rail روی موبایل دو ردیف pill اشغال می‌کنند.
**اصلاح:** nav جمع‌شونده یا انتقال به footer ثابت؛ ادغام دو rail (F-02) خودش نصف مشکل را حل می‌کند. **پذیرش:** همه مقاصد nav در ۳۶۰px قابل دسترس‌اند.

### F-12 · disabled بدون دلیل
`_workflow_navigation.html`: مراحل قفل‌شده `<span aria-disabled="true">` بدون هیچ توضیح precondition (الزام docs/16: «disabled با توضیح»)؛ دکمه تأیید corpus هم `disabled` بدون متن متصل (`aria-describedby`) است.
**اصلاح:** tooltip/متن ثابت «پس از تأیید برداشت باز می‌شود» + `aria-describedby`. **پذیرش:** هر disabled یک دلیل قابل‌خواندن (و قابل‌دسترس) دارد.

### F-13 · گیت‌شدن محتوای معتبر به run record آخر
`script.html` کل خروجی را فقط با `script_run.status == "succeeded" and script and checks and verification` نشان می‌دهد؛ اگر run record پس از restart ناقص/غایب باشد ولی project state `SCRIPT_VERIFIED` و artifactها معتبر باشند، صفحه خالی می‌ماند. (**نیازمند اجرای زنده برای تأیید**؛ از کد، مسیر fallback دیده نمی‌شود.) رفتار interrupted/reconcile (docs/17,19) در هیچ template ای وجود ندارد.
**اصلاح:** رندر از artifact معتبر + وضعیت run جدا؛ banner «اجرای قطع‌شده» با repair action.

### F-14 · دوباره‌کاری label مراحل در templateها
نگاشت stage→label فارسی planning در `processing.html` و `episode.html` عیناً تکرار شده (drift قطعی در آینده)؛ نگاشت corpus در python است (`_corpus_stage_label`) — سه الگوی متفاوت برای یک کار.
**اصلاح:** همه نگاشت‌ها به read model/python منتقل شوند.

### F-15 · پیام‌های وضعیت وابسته به query param
`?saved=1`، `?rewound`، `?searched`، `?error=…` پس از refresh/back باقی می‌مانند و دوباره نمایش داده می‌شوند؛ notice موفقیت کهنه گمراه‌کننده است.
**اصلاح:** flash message در session (یک‌بارمصرف).

### F-16 · دسترس‌پذیری تکمیلی
- هیچ `aria-live` (مرتبط با F-04).
- خطاها `role="alert"` دارند ✓ اما focus به آن‌ها منتقل نمی‌شود.
- متن ۱۲px با `--muted` (‎#66736b روی #fffdf8) نزدیک مرز AA است — اندازه‌گیری زنده لازم.
- OTP: `pattern` رقم فارسی را می‌پذیرد ✓، اما cooldown ارسال مجدد و شمارش تلاش باقی‌مانده در UI دیده نمی‌شود؛ خطای «کد نادرست» بدون شمارنده.
- جدول‌واره‌ها (`source-row`) semantics فهرست ندارند؛ برای screen reader ارتباط status↔row فقط از ترتیب DOM است.
**علامت:** موارد focus order و contrast «نیازمند اجرای زنده».

---

## یافته‌ها — P2 (Polish)

- **F-17 یکنواختی مؤلفه‌ها:** همه‌چیز (منبع، قطعه صوت، turn سناریو، نتیجه check، preflight) با یک `source-row` سه‌ستونه render می‌شود؛ سلسله‌مراتب بصری بین «خواندن سناریو» و «جدول کنترل» یکی است. سناریو باید مثل متنِ خواندنی چیده شود (ستون باریک، شماره turn در حاشیه)، نه مثل فهرست فایل.
- **F-18 تکرار الگوی نوار کناری رنگی:** `interpretation`، `notice`، `project-row__attention` همگی border-inline-start رنگی — همان الگوی «rounded card با accent کناری» که برای این محصول ممنوع اعلام شده؛ حداقل یکی از این‌ها باید زبان دیگری پیدا کند (مثلاً interpretation با تایپوگرافی بزرگ بدون قاب).
- **F-19 microcopy:** «brief»، «corpus»، «artifact»، «archive»، «quality-gate» در متن فارسی Simple Mode؛ واژه‌نامه فارسی ثابت لازم است (پیشنهاد در docs/30). لحن خوب «من این‌طور فهمیدم» باید معیار بقیه صفحات باشد.
- **F-20 empty stateها:** خوب و بدون demo جعلی ✓؛ فقط empty state منابع می‌تواند مسیر پیشنهادی (فایل یا جست‌وجو) را با مثال واقعی‌تر نشان دهد.

## چیزهایی که درست‌اند و عمداً تغییر نمی‌کنند

- PRG در همه POSTها؛ CSRF همه فرم‌ها؛ preflight پیش از stageهای هزینه‌دار (الگوی نمونه‌وار).
- بدون درصد جعلی/ETA؛ متن صریح «درصد حدس زده نمی‌شود».
- Save ≠ Confirm در brief؛ تأیید طرح متصل به hash؛ گیت corpus با دکمه غیرفعال.
- Insufficient corpus بدون «Continue anyway» و با کاهش مدت/افزودن منبع — مطابق docs/19.
- توکن‌های رنگ/تایپ DESIGN.md در app.css؛ focus-visible واقعی؛ min-height 44px؛ skip link؛ reduced-motion.
- ساختار ledger/رفتار backend، state machine، gateها — خارج از محدوده این ممیزی؛ هیچ تغییر backend contract پیشنهاد نشده مگر افزودن read model نمایش.

## بدهی‌های نیازمند کار backend (خارج از توان UI)

- ErrorRecord ساختاریافته (کد/دسته/summary_fa/impact_fa) — الان فقط `last_error` رشته‌ای ذخیره می‌شود.
- attention/execution state در read model.
- fragment endpointها برای polling.
- reconcile اجرای interrupted پس از restart.
- soft-delete یا مرحله تأیید server-side برای حذف منبع.

## ترتیب اجرا

**P0:** F-01، F-03 (یک‌خطی)، F-04، F-02، F-05، F-06، F-07 · **P1:** F-08…F-16 · **P2:** F-17…F-20.
جزئیات طراحی مقصد در `docs/30-ui-redesign-spec.md`.
