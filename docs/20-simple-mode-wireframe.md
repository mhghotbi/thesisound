# 20 — وایرفریم Simple Mode

## هدف

این سند منبع حقیقت وایرفریم حالت ساده Thesisound است. حالت ساده یک workflow جدا نیست؛ همان domain state، application command، artifact، human gate و recovery policy مربوط به Operator UI را با زبان ساده‌تر و جزئیات کمتر نمایش می‌دهد.

فایل تصویری مرجع این نسخه با نام `thesisound-simple-mode-wireframe-v1.png` تولید شده است.

## جریان کامل

```text
خانه و پروژه‌های اخیر
→ تعریف هدف یادگیری
→ تأیید Research Brief
→ افزودن منابع
→ بررسی منابع قابل‌استفاده و تأیید corpus
→ پردازش و Action Required
→ بازبینی طرح اپیزود و پوشش
→ شنیدن، خواندن و مشاهده منبع
```

## ۱. خانه و پروژه‌های اخیر

اهداف:

- ساخت پروژه جدید؛
- ادامه پروژه قبلی؛
- نمایش وضعیت running، waiting for user، failed و complete؛
- ورود صریح به «حالت پیشرفته / Operator UI».

این صفحه نباید فقط فرم ساخت پروژه جدید باشد. Resume بخشی از مسیر اصلی است.

## ۲. تعریف هدف یادگیری

ورودی‌های سطح اول:

- موضوع یا سؤال مرکزی؛
- سطح مخاطب؛
- مدت هدف؛
- نوع روایت.

تنظیمات کم‌کاربرد پشت progressive disclosure قرار می‌گیرند. `research-assisted` تا زمان پیاده‌سازی Source Discovery غیرفعال است و نباید به‌صورت پنهان به `source-bound` تبدیل شود.

## ۳. تأیید Research Brief

سیستم برداشت خود را به زبان انسانی بازگو می‌کند. کاربر می‌تواند:

- برداشت را تأیید کند؛
- سؤال مرکزی را اصلاح کند؛
- مفاهیم ضروری اختیاری اضافه کند؛
- exclusions اختیاری اضافه کند.

ذخیره و تأیید دو action متفاوت‌اند. stage بعدی فقط بر اساس brief تأییدشده اجرا می‌شود.

## ۴. افزودن منابع

قابلیت‌های لازم:

- upload فایل؛
- نمایش upload، inspection و parse status به زبان ساده؛
- retry منبع شکست‌خورده؛
- لینک یا متن در زمان پیاده‌سازی adapter مربوطه.

Source Discovery در این نسخه به‌شکل disabled / به‌زودی نمایش داده می‌شود.

## ۵. بررسی منابع و تأیید corpus

هر منبع یکی از این وضعیت‌های ساده را دارد:

- در حال بررسی؛
- آماده استفاده؛
- نیازمند بازبینی؛
- قابل‌استفاده نیست.

Uploaded، parsed، usable و selected نباید با یک تیک واحد مخلوط شوند.

Human gate صریح:

> اپیزود فقط بر اساس منابع انتخاب‌شده ساخته می‌شود.

منبعی که blocking quality failure دارد قابل انتخاب نیست.

## ۶. پردازش و Action Required

Progress فقط با stage یا unit واقعی نمایش داده می‌شود. درصد ساختگی و ETA غیرقابل‌اعتماد ممنوع است.

حالت‌های اصلی:

- running؛
- waiting for user؛
- failed retryable؛
- blocked by configuration؛
- interrupted؛
- passed with warnings؛
- complete.

Simple Mode یک اقدام اصلی پیشنهاد می‌دهد. log، run detail، artifact و strategyهای پیشرفته در Operator UI باز می‌شوند.

## ۷. بازبینی طرح اپیزود و پوشش

صفحه باید نشان دهد:

- corpus چند دقیقه محتوای معتبر پشتیبانی می‌کند؛
- مدت درخواستی چقدر است؛
- ساختار پیشنهادی اپیزود؛
- منابع اصلی؛
- gapهای مادی؛
- action پیشنهادی.

اگر corpus ناکافی باشد، تولید مسدود می‌شود. actionهای معتبر:

- کاهش مدت؛
- افزودن منبع؛
- تغییر تمرکز؛
- توقف.

`Continue anyway` وجود ندارد.

## ۸. شنیدن، خواندن و مشاهده منبع

اجزای اصلی:

- audio player؛
- navigation بخش‌ها؛
- transcript؛
- تب منابع؛
- source detail برای بخش انتخاب‌شده؛
- دریافت audio و transcript.

برای جمله‌ها یا پاراگراف‌های مهم، مسیر «مشاهده منبع» باید در دسترس باشد. trace زیر با Operator UI مشترک است:

```text
script turn
→ claim
→ evidence
→ supporting excerpt
→ source locator
```

## جایگاه Operator UI

Operator UI حذف نمی‌شود و برای این موارد است:

- dashboard پروژه و attention؛
- pipeline stage و attempt؛
- parser و source quality؛
- run history و artifact؛
- script verification؛
- Audio QA و ASR diff؛
- log و structured error؛
- token، latency و cost؛
- provider و diagnostics.

Simple و Advanced mode یک backend و یک workflow دارند. تفاوت فقط در زبان، چگالی اطلاعات و سطح کنترل است.

## variantهای اجباری پیش از طراحی UI نهایی

- PDF رمزگذاری‌شده یا خراب؛
- استخراج ضعیف متن فارسی؛
- provider configuration ناقص؛
- corpus ناکافی؛
- script verification failure؛
- interruption پس از restart؛
- audio segment معیوب؛
- stale شدن downstream پس از تغییر upstream.

## قید پیاده‌سازی

Browser action مجاز را حدس نمی‌زند. server read model و permitted actionها را می‌فرستد. Simple Mode فقط presentation را ساده می‌کند؛ هیچ gate، failure state یا dependency را حذف نمی‌کند.
