# 21 — Web UI، Session و OTP

## هدف

این سند قرارداد اولین vertical slice رابط وب را ثبت می‌کند:

```text
OTP login
→ project list
→ create project
→ Research Brief confirmation
→ source upload and selection
→ corpus confirmation
→ processing handoff
```

این slice جایگزین pipeline یا state machine نیست. routeها فقط application commandهای معتبر را اجرا می‌کنند و `ProjectState` موجود منبع حقیقت باقی می‌ماند.

## احراز هویت

رابط وب از session cookie امضاشده استفاده می‌کند.

قواعد:

- cookie در production باید `Secure` باشد؛
- session secret در production باید تغییر کند؛
- POSTها CSRF token دارند؛
- مقصد `next` فقط path داخلی است؛
- login و logout state پروژه را تغییر نمی‌دهند.

## OTP آزمایشی

تا قبل از اتصال سرویس پیامک، development login زیر فعال است:

```text
phone: 0912000000
otp:   999999
```

این رفتار فقط با `THESISOUND_ALLOW_TEST_OTP=true` فعال می‌شود.

Startup در محیط `production` در این حالت fail می‌شود. production همچنین `UI_DEMO_MODE`، session secret پیش‌فرض و cookie ناامن را رد می‌کند.

## OTP Port

لایه وب به `OtpSenderPort` وابسته است. Adapter فعلی `NullOtpSender` است و delivery واقعی انجام نمی‌دهد.

Adapter پیامک آینده باید بدون تغییر routeها جایگزین شود:

```text
OtpSenderPort
├── NullOtpSender          development
└── SmsProviderAdapter     production
```

Challenge store فعلی in-memory است و برای یک process محلی مناسب است. پیش از deployment چند-worker باید به storage مشترک با rate limiting منتقل شود.

## Source UI demo mode

در اولین slice، upload واقعی است اما نتیجه parse quality در `THESISOUND_UI_DEMO_MODE=true` شبیه‌سازی می‌شود تا interaction source selection قابل تست باشد.

قواعد:

- manifest UI جای artifact ingestion را نمی‌گیرد؛
- هر source شبیه‌سازی‌شده با `is_demo_result` علامت می‌خورد؛
- محدودیت در domain source ثبت می‌شود؛
- production اجازه فعال‌کردن demo mode را ندارد؛
- اتصال `DocumentIngestionService` کار بعدی است.

## RTL و bidi

ریشه document برابر `dir="rtl"` است. این داده‌ها isolation مستقل دارند:

- شماره موبایل و OTP؛
- filename؛
- timestamp؛
- model ID؛
- run/project ID؛
- URL و hash؛
- cost و token count.

استفاده از RTL والد برای این داده‌ها مجاز نیست.

## مسیرهای فعلی

```text
/login
/login/verify
/projects
/projects/new
/projects/{project_id}/brief
/projects/{project_id}/sources
/projects/{project_id}/processing
```

## Definition of Done این slice

- login تستی با credential توسعه کار کند؛
- production با test OTP بالا نیاید؛
- کاربر ناشناس به login هدایت شود؛
- project روی `WorkspaceStore` ذخیره شود؛
- save و confirm Brief یکی نباشند؛
- source انتخاب‌نشده وارد corpus نشود؛
- source غیرآماده قابل انتخاب نباشد؛
- corpus بدون حداقل یک source تأیید نشود؛
- UI درصد یا ETA جعلی نشان ندهد؛
- flow موبایل و keyboard قابل‌استفاده باشد.
