# 01 — اصول و مرزهای Operator UI

> **وضعیت: اصول معتبر، جزئیات صفحه‌ها تاریخی.** این سند پیش از افزودن OTP/session auth نوشته شد. شرح صفحه‌های واقعاً ساخته‌شده در [`05-web-ui-auth-and-first-slice.md`](05-web-ui-auth-and-first-slice.md) تا [`10-local-live-e2e-runbook.md`](10-local-live-e2e-runbook.md) و هدف فعلی رابط در [`../05-ui-redesign/02-ui-redesign-spec.md`](../05-ui-redesign/02-ui-redesign-spec.md) است. آنچه اینجا مانده اصول و معیارهایی است که هنوز برقرارند.

## هدف

رابطی برای اجرای امن، مشاهده‌پذیر و قابل‌بازیابی pipeline. کار توسعه، benchmark، بازبینی کیفیت و debugging را از CLI ساده‌تر می‌کند، بدون اینکه منطق domain یا orchestration را دوباره در لایهٔ UI پیاده کند.

## مرز Operator UI و End-user UI

| | Operator UI | End-user UI |
|---|---|---|
| مخاطب | صاحب پروژه، توسعه‌دهنده، ارزیاب | کاربر غیرمتخصص |
| نمایش | stage، gate، warning، token usage، خطای فنی | زبان ساده، جزئیات فنی کمتر |
| کنترل | retry کنترل‌شده، اجرای دوبارهٔ stage | مسیر هدایت‌شده |

این دو نباید اشتباه گرفته شوند: Operator UI ابزار مهندسی و کنترل کیفیت است، نه نسخهٔ ناقص یک SaaS. در بازطراحی فعلی این تفکیک به‌صورت toggle «حالت پیشرفته» روی یک backend و یک state machine پیاده می‌شود، نه دو محصول جدا.

## اصول UX

1. **Domain منبع حقیقت است.** UI هیچ state، claim، locator، ID یا gate جدیدی اختراع نمی‌کند؛ آنچه نمایش می‌دهد از project state، run record و artifact معتبر ساخته می‌شود.
2. **Human gate صریح است.** هر جا تصمیم انسانی لازم است pipeline متوقف می‌شود و UI یک action روشن نشان می‌دهد. انتخاب منبع، تأیید brief و تصمیم دربارهٔ corpus ناکافی با پیش‌فرض پنهان رد نمی‌شوند.
3. **Progress واقعی، نه نمایشی.** درصد جعلی نمایش داده نمی‌شود؛ progress بر اساس stage قطعی و subtask ثبت‌شده است. اگر مدت باقی‌مانده قابل‌اعتماد نیست، ETA نشان داده نمی‌شود.
4. **Resume بر restart مقدم است.** کاربر باید بتواند پروژهٔ متوقف‌شده را از آخرین artifact معتبر ادامه دهد. اجرای دوبارهٔ کل pipeline فقط وقتی پیشنهاد می‌شود که ورودی upstream تغییر کرده باشد.
5. **خطا بخشی از flow است.** failed، warning، insufficient coverage و stale run حالت‌های عادی سیستم‌اند، نه modal استثنایی. صفحهٔ پروژه همیشه توضیح می‌دهد چه شد و action بعدی چیست.
6. **Progressive disclosure.** اطلاعات اصلی در سطح صفحه؛ stack trace، raw JSON، prompt metadata و پاسخ provider در «جزئیات فنی».
7. **تغییر ورودی اثر downstream را آشکار می‌کند.** پیش از تغییر duration، brief، انتخاب منبع یا سند parse‌شده، UI نشان می‌دهد کدام artifact نامعتبر می‌شود.

## قواعد ثابت جریان

- **research-assisted** تا پیاده‌سازی Source Discovery با برچسب «هنوز در دسترس نیست» نمایش داده می‌شود و بی‌صدا به `source-bound` تبدیل نمی‌شود.
- **ذخیره و تأیید دو action متفاوت‌اند.** فقط brief تأییدشده مبنای stage بعدی است.
- **corpus ناکافی دکمهٔ مبهم `Continue anyway` ندارد.** actionهای معتبر: کاهش duration، افزودن منبع، تغییر brief، توقف. هر override پژوهشی آینده باید صریح و ثبت‌شده باشد.
- **`Confirm corpus` فقط وقتی فعال است** که حداقل یک منبع از quality gate عبور کرده باشد.
- **UI اجازهٔ اجرای stage بدون پیش‌نیاز را نمی‌دهد؛** actionهای دستی از application service معتبر عبور می‌کنند، نه ساخت مستقیم فایل خروجی.
- **ویرایش آزاد script مجاز نیست،** چون grounding contract را می‌شکند. اگر editor اضافه شد، هر turn ویرایش‌شده باید دوباره check و verify شود.
- **stageهای در دسترس‌نبودن دیده می‌شوند اما disabled با دلیل‌اند.** پنهان‌کردن کامل، نقشهٔ pipeline را از operator می‌گیرد.
- **هر صفحه فقط یک primary action دارد؛** raw JSON، دانلود artifact و rerun در سطح secondary می‌مانند.

## trace اجباری

```text
script turn → claim ID → evidence ID → supporting excerpt → source block → locator
```

## معیار پذیرش

- یک operator بدون مراجعه به README پروژهٔ one-source را تا `script_verified` اجرا کند؛
- در هر لحظه بداند پروژه در چه stageای است و چرا متوقف شده؛
- هیچ stage نامعتبر از UI قابل اجرا نباشد؛
- retry ورودی‌های قبلی را حفظ کند و run جدید بسازد؛
- تغییر upstream اثر downstream را پیش از تأیید نشان دهد؛
- trace از script به منبع با حداکثر سه interaction دیده شود؛
- خطای provider، quality gate و corpus insufficiency از هم قابل‌تشخیص باشند؛
- اجرای قطع‌شده پس از restart سرویس ادامه‌پذیر باشد.

## خارج از محدوده

تیم و collaboration، billing و quota، public sharing، rich text editor عمومی، ویرایش drag-and-drop اپیزود، analytics dashboard محصول، و automation خودمختار بدون human gate.
