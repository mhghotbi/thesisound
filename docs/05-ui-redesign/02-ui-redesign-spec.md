# 02 — Spec بازطراحی UI رابط وب Thesisound

تاریخ: ۲۰۲۶-۰۸-۰۹ · پیش‌نیاز: [`01-ui-ux-audit.md`](01-ui-ux-audit.md) · واژگان: [`03-product-language.md`](03-product-language.md) · مرجع بصری: صفحه‌های بازطراحی‌شده در پروژه طراحی («Thesisound Flow»، ۱۰ صفحه مسیر کامل)

این سند قرارداد طراحی مقصد است. هیچ قاعده domain جدیدی تعریف نمی‌کند؛ فقط presentation، معماری اطلاعات و الگوهای تعامل را مشخص می‌کند. Stack همان Jinja + HTMX سمت server می‌ماند.

---

## Design thesis

Thesisound باید حس **یک میز مطالعه جدی** را بدهد: آرام، کاغذی، متن‌محور، با یک اقدام روشن در هر لحظه — نه یک dashboard و نه یک «ابزار AI». چیزی که آن را از NotebookLM-clone جدا می‌کند، صداقت با شواهد است: هر عدد یک واحد واقعی دارد، هر ادعا مسیر ردیابی تا منبع دارد، و وقتی منابع کافی نیستند، محصول با احترام «نه» می‌گوید و راه اصلاح می‌دهد. کاربر در هر مرحله باید به یک چیز اعتماد کند: **آنچه می‌بینم، وضعیت واقعی است و اقدام پیشنهادی از همان وضعیت آمده است.**

## ۱. معماری اطلاعات و ناوبری

```text
/login → /login/verify
/projects                     فهرست + empty state
/projects/new                 تعریف هدف
/projects/{id}                Project Overview (صفحه جدید — خانه پروژه)
  /brief /sources /processing /episode /script /audio
/system-check                 فقط در حالت پیشرفته
```

قواعد:

- **یک ناوبری واحد:** `StepRail` سراسری با ۶ مرحله ثابت: «هدف و برداشت → منابع → پردازش → طرح اپیزود → متن اپیزود → شنیدن». همه‌جا همین ۶ نام، همین ترتیب. `workflow.css` و همه railهای دست‌نویس حذف می‌شوند.
- هر آیتم rail یکی از حالت‌ها: complete / current / available / locked. حالت locked دلیل کوتاه دارد («پس از تأیید منابع باز می‌شود») و از read model می‌آید.
- کنترل «بازگشت و اصلاح» داخل همان rail است (روی مراحل complete)، نه یک جعبه جدا.
- فهرست پروژه‌ها به **Overview** لینک می‌دهد، نه به میانه flow. Primary action داخل Overview است.
- **حالت پیشرفته (Operator):** toggle صریح در header، ذخیره در session، برچسب دائمی «حالت پیشرفته» هنگام فعال بودن. Simple پیش‌فرض است. یک backend، یک state machine؛ تفاوت فقط در density، واژگان و کنترل‌های اضافه. حالت ساده هیچ gate، failure state یا dependency را حذف نمی‌کند — فقط presentation را ساده می‌کند.
- **مرجع action سمت server است.** مرورگر حدس نمی‌زند چه actionای مجاز است؛ read model فهرست actionهای مجاز را می‌فرستد.

## ۲. مدل نمایش state (سه محور، طبق [`../03-web-ui/02-interface-state-model.md`](../03-web-ui/02-interface-state-model.md))

- **StatusLabel** دوجزئی: (وضعیت مرحله) + (نیاز به اقدام). مثال: «در حال استخراج شواهد» / «منتظر تصمیم شما» / «متوقف‌شده — قابل تلاش دوباره».
- هیچ status/verdict انگلیسی خام در حالت ساده. نگاشت واژگان در python (read model) نگهداری می‌شود، نه در template:

| مقدار داخلی | حالت ساده | حالت پیشرفته |
|---|---|---|
| running | در حال انجام | running · نام stage |
| passed | انجام شد | passed |
| passed_with_warnings | انجام شد، با چند نکته | passed_with_warnings + شمار |
| failed (retryable) | متوقف شد — قابل ادامه | failed_retryable + کد خطا |
| failed (permanent) | متوقف شد — نیازمند اصلاح ورودی | failed_permanent + کد |
| blocked | منتظر تصمیم شما | blocked + دلیل gate |
| stale | نیازمند به‌روزرسانی (ورودی تغییر کرده) | stale + artifactهای affected |
| interrupted | اجرا قطع شد — در حال بررسی | interrupted + heartbeat |

- رنگ هرگز تنها حامل state نیست: هر label متن + نشانه شکلی متمایز دارد (دایره توپر=در جریان، تیک=کامل، مثلث=هشدار، مربع=متوقف).

## ۳. Anatomy صفحه‌ها

### Project Overview (جدید)
هدف: پاسخ ۵ثانیه‌ای به «چه شد، کجاییم، بعدش چی». سطح اول: عنوان + سؤال مرکزی، StepRail، پنل «اقدام لازم» (حداکثر یکی)، خلاصه آخرین اتفاق («دیروز: ساخت شواهد کامل شد، ۴۲ ادعای مستند»). Disclosure: آخرین runها، artifactها (پیشرفته). Primary: از attention state. Secondary: ورود به مرحله جاری. Mobile: rail عمودی فشرده.

### فهرست پروژه‌ها
ردیف = عنوان + StatusLabel دوجزئی + آخرین تغییر (جلالی) + یک لینک «ادامه». گروه‌بندی بر اساس attention: «منتظر شما» بالا، بعد «در حال انجام»، بعد بقیه. جست‌وجو/فیلتر فقط وقتی ‎>۷ پروژه.

### تعریف هدف / برداشت
همان ساختار فعلی؛ اصلاحات: حفظ کامل valueها پس از خطا، خطای field-level کنار field با `aria-describedby`، مدت هدف با رقم فارسی. brief: نمایش diff ساده پس از ویرایش (پیشرفته).

### منابع
سطح اول هر منبع: نام، منشأ، وضعیت ساده (در حال بررسی / آماده استفاده / نیازمند بازبینی / قابل‌استفاده نیست) + یک جمله دلیل. Disclosure «جزئیات فنی»: parser، coverage، parserهای آزموده. Actionها: «افزودن به اپیزود / کنار گذاشتن» (toggle، بی‌خطر) و «حذف فایل…» (danger، همیشه با صفحه تأیید). Footer ثابت: «اپیزود بر اساس n منبع ساخته می‌شود» + primary تأیید (disabled با دلیل متصل).

### پردازش
StageList با state درست (فقط یک current). polling با `hx-get` fragment هر ۲s فقط هنگام run فعال؛ توقف در visibility hidden؛ `aria-live="polite"` روی عنوان مرحله. failure → ErrorRecoveryPanel (§۵).

### طرح اپیزود
ترتیب: ۱) حکم پوشش با جمله دقیق («منابع برای حدود ۱۸ دقیقه از هدف ۲۵ دقیقه شواهد معتبر دارند») ۲) gapهای مادی ۳) ساختار بخش‌ها ۴) تأیید. حالت ناکافی: actionها به ترتیب کم‌هزینه‌ترین؛ «ادامه به هر قیمت» وجود ندارد (حفظ رفتار فعلی).

### متن اپیزود (سناریو)
دو لایه: **خواندن** (ستون باریک ۶۶ch، متن گفتار با نام گوینده، شماره turn در حاشیه؛ بدون ID در سطح اول) و **ردیابی** (کلیک روی turn → پنل شواهد: نقل‌قول، locator، منبع؛ حداکثر ۳ تعامل تا منبع). گزارش کیفیت: دو جمله فارسی + جزئیات در disclosure. hash تأیید طرح فقط در حالت پیشرفته.

### شنیدن (صوت)
سطح اول: player نهایی + transcript همگام + دریافت فایل. کنترل قطعه‌ها، ASR diff و شباهت: حالت پیشرفته یا disclosure.

## ۴. Component model

| Component | مسئولیت | جایگزین |
|---|---|---|
| `AppHeader` | برند، nav، toggle حالت پیشرفته، خروج | header فعلی |
| `StepRail` | ۶ مرحله ثابت + وضعیت + rewind | step-rail دستی + workflow-switcher (هر دو حذف) |
| `AttentionPanel` | یک اقدام لازم با دلیل | notice‌های پراکنده |
| `ProjectRow` | ردیف فهرست با StatusLabel | project-row فعلی |
| `SourceRow` | منبع + وضعیت ساده + actions | source-row فعلی (فقط برای منابع) |
| `StatusLabel` | label دوجزئی متن+شکل | badgeهای وضعیت |
| `ErrorRecoveryPanel` | anatomy ۷بخشی خطا | notice--danger + دکمه retry |
| `ImpactSummary` | صفحه تأیید destructive با فهرست اثر | — (جدید) |
| `TechnicalDetails` | disclosure جزئیات فنی | details فعلی (استاندارد می‌شود) |
| `TranscriptTurn` | turn خواندنی + trace | source-row برای turnها |
| `EvidenceDrawer` | نقل‌قول → locator → منبع | details تو در تو |
| `AudioPlayer` | player + transcript همگام | audio خام |

حذف‌شده از فهرست DESIGN.md: `SourceStatus` (در StatusLabel ادغام)، `Field`/`PrimaryButton`/`SecondaryButton` (الگوی CSS، نه component).

## ۵. الگوی خطا و بازیابی

ErrorRecoveryPanel همیشه با این ترتیب: چه شد (یک جمله فارسی) → اثر (چه چیزی معتبر ماند) → پیشنهاد اصلی (یک primary) → حداکثر دو گزینه دیگر → جزئیات فنی (کد، run، متن خام provider). قواعد: `last_error` خام هرگز در سطح اول نیست؛ retry فقط وقتی retryable؛ پس از سقف تلاش، primary عوض می‌شود؛ پیام‌های flash از session (نه query param). حذف/تغییر destructive همیشه از `ImpactSummary` عبور می‌کند: نام آیتم، فهرست خروجی‌هایی که stale/archive می‌شوند، آنچه باقی می‌ماند، تأیید صریح.

## ۶. قواعد محتوا و واژگان

- واژه‌نامهٔ کامل و معتبر در [`03-product-language.md`](03-product-language.md) است؛ هیچ واژه‌ای مستقل از آن سند در UI اضافه نمی‌شود. واژه انگلیسی در حالت ساده فقط برای نام فایل/URL داخل `<bdi dir="ltr">`.
- ارقام: **رقم فارسی در متن روان؛ رقم لاتین فقط برای identifier، URL و کد داخل bdi.** تاریخ‌ها جلالی + `<time datetime>` میلادی.
- لحن: اول‌شخص محترمانه («من این‌طور فهمیدم» معیار است)، بدون علامت تعجب، بدون وعده («ممکن است چند دقیقه طول بکشد» فقط اگر واقعی).

## ۷. قواعد responsive و دسترس‌پذیری

- ≤760px: nav در footer ثابت یا منوی جمع‌شونده (هرگز حذف)؛ StepRail فشرده افقی scrollable با مرحله جاری visible؛ target ≥44px؛ فرم‌ها تک‌ستونه.
- a11y: `aria-live="polite"` فقط روی عنوان وضعیت run؛ خطای فرم کنار field + انتقال focus به اولین خطا؛ هر disabled با `aria-describedby` دلیل؛ فهرست‌ها با semantics واقعی (`ul/li` یا جدول)؛ contrast متن ≤۱۳px بازبینی شود (muted فعلی مرزی است)؛ حفظ skip link، focus-visible و reduced-motion فعلی.

## ۸. قواعد بصری (مکمل DESIGN.md)

- توکن‌های رنگ/تایپ DESIGN.md دست نمی‌خورند. workflow.css حذف می‌شود.
- الگوی «نوار رنگی کناری» فقط برای notice می‌ماند؛ `interpretation` به تایپوگرافی بزرگ بدون قاب تبدیل می‌شود؛ AttentionPanel با rule افقی و عنوان، نه قاب رنگی.
- «source-row برای همه‌چیز» ممنوع: transcript چیدمان خواندن دارد، جدول‌ها جدول‌اند.
- brand mark «▥» با نشان واقعی جایگزین شود (خارج از این spec).

## ۹. ترتیب پیاده‌سازی و تست

1. **P0:** اصلاح شرط is-current (یک خط)؛ ImpactSummary حذف منبع؛ StepRail واحد؛ fragment polling با HTMX؛ Project Overview؛ نگاشت واژگان status؛ ErrorRecoveryPanel حداقلی.
2. **P1:** field-level errors + حفظ valueها؛ StatusLabel دوجزئی؛ اصلاح bidi/ارقام/تاریخ؛ nav موبایل؛ دلیل disabled؛ flash از session؛ انتقال نگاشت‌های label به python.
3. **P2:** چیدمان خواندنی سناریو، microcopy، empty stateها.

تست‌های لازم (pytest + DOM): دقیقاً یک is-current؛ حذف منبع بدون توکن تأیید → 4xx؛ هیچ status انگلیسی خام در حالت ساده؛ حفظ valueهای فرم پس از خطا؛ fragment polling بدون full reload؛ دلیل disabled در DOM؛ `dir`/`bdi` برای identifierها؛ historical/stale banner.

**variantهایی که هر صفحه باید پیش از تأیید طراحی نشان دهد:** PDF رمزگذاری‌شده یا خراب · استخراج ضعیف متن فارسی · پیکربندی ناقص provider · corpus ناکافی · شکست راستی‌آزمایی متن · قطع‌شدن اجرا و ادامه پس از restart · قطعهٔ صوتی معیوب · stale شدن downstream پس از تغییر upstream. طراحی‌ای که فقط happy path را نشان دهد پذیرفته نیست.
