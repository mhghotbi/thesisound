# 16 — جریان کار Operator UI

## هدف

Operator UI یک رابط محلی برای اجرای امن، مشاهده‌پذیر و قابل‌بازیابی pipeline فعلی Thesisound است. این رابط قرار نیست در این مرحله تجربه نهایی کاربر عمومی باشد؛ قرار است کار توسعه، benchmark، بازبینی کیفیت و debugging را از CLI ساده‌تر کند، بدون اینکه منطق domain یا orchestration را دوباره در لایه UI پیاده کند.

Operator در نسخه اول همان صاحب پروژه، توسعه‌دهنده یا ارزیاب کیفیت است. بنابراین UI می‌تواند جزئیات فنی بیشتری از یک محصول عمومی نشان دهد، اما نباید کاربر را مجبور کند ساختار فایل‌های workspace یا فرمان‌های CLI را حفظ باشد.

## مرز Operator UI و End-user UI

### Operator UI

- local-first و تک‌کاربره؛
- مناسب اجرای pipeline، بازبینی artifactها و recovery؛
- نمایش stage، gate، warning، token usage و خطای فنی؛
- اجازه retry کنترل‌شده و اجرای دوباره stage؛
- بدون authentication، billing، collaboration و multi-tenancy؛
- وفادار به state machine و artifactهای فعلی.

### End-user UI

- برای کاربر غیرمتخصص؛
- زبان ساده‌تر و جزئیات فنی کمتر؛
- onboarding، hosted deployment، privacy controls و مدیریت حساب؛
- پس از تثبیت TTS، Source Discovery و multi-source reconciliation.

این دو نباید با هم اشتباه گرفته شوند. Operator UI یک ابزار مهندسی و کنترل کیفیت است، نه نسخه ناقص یک SaaS عمومی.

## اصول UX

### ۱. Domain منبع حقیقت است

UI هیچ state، claim، locator، ID یا gate جدیدی اختراع نمی‌کند. وضعیت نمایش‌داده‌شده باید از project state، run record و artifactهای معتبر ساخته شود.

### ۲. Human gate باید صریح باشد

هر جا تصمیم انسانی لازم است، pipeline باید متوقف شود و UI یک action روشن نشان دهد. انتخاب منبع، تأیید Research Brief و تصمیم درباره corpus ناکافی نباید با پیش‌فرض پنهان رد شوند.

### ۳. Progress واقعی، نه نمایشی

درصد پیشرفت جعلی نمایش داده نمی‌شود. progress بر اساس stageهای قطعی و subtaskهای ثبت‌شده نشان داده می‌شود. اگر مدت باقی‌مانده قابل‌اعتماد نیست، ETA نمایش داده نمی‌شود.

### ۴. Resume بر restart مقدم است

کاربر باید بتواند پروژه متوقف‌شده را از آخرین artifact معتبر ادامه دهد. اجرای دوباره کل pipeline فقط زمانی پیشنهاد می‌شود که ورودی upstream تغییر کرده باشد.

### ۵. خطا بخشی از flow است

failed، warning، insufficient coverage و stale run حالت‌های عادی سیستم هستند، نه modalهای استثنایی. صفحه پروژه باید همیشه توضیح دهد چه اتفاقی افتاده و action بعدی چیست.

### ۶. Progressive disclosure

اطلاعات اصلی در سطح صفحه دیده می‌شوند؛ stack trace، raw JSON، prompt metadata و provider response در بخش «جزئیات فنی» باز می‌شوند.

### ۷. تغییر ورودی اثر downstream را آشکار می‌کند

پیش از تغییر duration، Research Brief، source selection یا parsed document، UI باید نشان دهد کدام artifactهای downstream نامعتبر می‌شوند و نیاز به rebuild دارند.

---

## جریان اصلی نسخه اول

```text
Projects
→ Create or resume project
→ Define and confirm Research Brief
→ Add source
→ Inspect and parse source
→ Confirm usable corpus
→ Run evidence pipeline
→ Review coverage and episode plan
→ Run script pipeline
→ Review verification result
→ Continue to TTS when available
```

## مرحله ۰ — فهرست پروژه‌ها

### هدف کاربر

- دیدن پروژه‌های موجود؛
- فهمیدن stage فعلی؛
- پیدا کردن پروژه‌هایی که نیاز به اقدام دارند؛
- ادامه آخرین پروژه بدون مراجعه به workspace.

### اطلاعات لازم

- عنوان و project ID؛
- mode و duration؛
- project state؛
- آخرین run و زمان آن؛
- وضعیت attention: در حال اجرا، نیازمند تصمیم، شکست‌خورده یا آماده ادامه؛
- action اصلی پیشنهادی.

### action اصلی

- `Continue` برای پروژه ناقص؛
- `Review failure` برای شکست؛
- `Open result` برای خروجی آماده؛
- `Create project` برای پروژه جدید.

## مرحله ۱ — ایجاد پروژه و Research Brief

### ورودی حداقلی

- عنوان، سؤال یا موضوع؛
- مخاطب؛
- prior knowledge؛
- duration؛
- modeهای محتوایی؛
- زبان خروجی؛
- source mode: `source-bound` یا `research-assisted`.

### رفتار

1. کاربر پروژه را ایجاد می‌کند.
2. سیستم Research Brief را می‌سازد.
3. UI brief را به شکل fieldهای قابل‌ویرایش نشان می‌دهد، نه فقط raw JSON.
4. کاربر تغییرات را ذخیره و brief را تأیید می‌کند.
5. فقط brief تأییدشده می‌تواند مبنای stageهای بعدی باشد.

### قواعد

- تغییر duration بعداً مجاز است، اما باید اثر آن بر evidence budget، episode plan و script را نشان دهد.
- تغییر سؤال مرکزی یا learning objective پس از ساخت evidence، downstream artifacts را stale می‌کند.
- `research-assisted` تا پیش از پیاده‌سازی Source Discovery باید با برچسب «هنوز در دسترس نیست» نمایش داده شود؛ نباید بی‌صدا به `source-bound` تبدیل شود.

## مرحله ۲ — Source Workspace

### هدف کاربر

- افزودن فایل؛
- دیدن نتیجه inspection و parse؛
- فهمیدن اینکه متن استخراج‌شده قابل‌استفاده است یا نه؛
- انتخاب parser یا retry در صورت شکست.

### جریان

```text
Upload
→ file inspection
→ parser routing
→ parse execution
→ quality gate
→ accepted / warning / failed
```

### اطلاعات سطح اول

- نام فایل، نوع و اندازه؛
- encrypted یا سالم؛
- parser انتخاب‌شده؛
- تعداد صفحه یا block؛
- پوشش متن؛
- quality gate status؛
- warningهای مهم مانند OCR ضعیف، ترتیب خواندن مشکوک یا متن کم.

### جزئیات فنی قابل‌بازشدن

- SHA-256؛
- parser attempts؛
- timing؛
- artifact path؛
- raw parse report؛
- دلایل fallback.

### actionها

- parse؛
- retry همان parser؛
- retry با parser دیگر؛
- inspect parsed text؛
- حذف source از پروژه؛
- تأیید source برای corpus.

حذف source پس از ساخت evidence destructive است و باید اثر downstream را توضیح دهد.

## مرحله ۳ — تأیید corpus

در نسخه one-source، این مرحله ساده است اما باید مستقل بماند تا بعداً Source Discovery به آن اضافه شود.

### کاربر باید ببیند

- sourceهای پذیرفته‌شده؛
- sourceهای ردشده یا warningدار؛
- mode پروژه؛
- محدوده‌ای که اپیزود بر اساس آن ساخته می‌شود؛
- هشدار اینکه source انتخاب‌نشده وارد evidence نمی‌شود.

### human gate

دکمه `Confirm corpus and continue` فقط زمانی فعال است که حداقل یک source از quality gate عبور کرده باشد.

## مرحله ۴ — اجرای Evidence Pipeline

### جریان

```text
Build semantic blocks
→ Map document
→ Build analysis profile
→ Extract evidence
→ Validate evidence
→ Build claims
→ Corpus ready
```

### UI باید نشان دهد

- stage جاری؛
- stageهای تمام‌شده؛
- warning و failure؛
- input artifact hash؛
- model run usage در transformهای مدل‌محور؛
- action بعدی.

UI نباید اجازه دهد کاربر stage downstream را بدون پیش‌نیاز اجرا کند. actionهای دستی باید از application service معتبر عبور کنند، نه اینکه فایل خروجی را مستقیماً بسازند.

## مرحله ۵ — Episode Preparation و Coverage Review

### خروجی‌های اصلی

- coverage report؛
- claim priorities؛
- budget report؛
- disagreement graph؛
- episode plan؛
- evidence packs.

### ترتیب نمایش

1. آیا corpus برای duration انتخاب‌شده کافی است؟
2. چه موضوع‌هایی پوشش داده یا حذف شده‌اند؟
3. segmentهای اپیزود چه هستند؟
4. هر segment به کدام claim و evidence متصل است؟
5. جزئیات deterministic budget و retrieval trace.

### تصمیم‌های کاربر

اگر corpus ناکافی است، UI نباید دکمه مبهم `Continue anyway` ارائه کند. actionهای معتبر عبارت‌اند از:

- کاهش duration؛
- اضافه‌کردن source؛
- تغییر Research Brief؛
- توقف پروژه.

هر override پژوهشی آینده باید صریح، ثبت‌شده و قابل‌ممیزی باشد.

## مرحله ۶ — Script Review

### نمای پیش‌فرض

- verifier status؛
- duration تخمینی؛
- issue count؛
- segment list؛
- متن فارسی قابل‌خواندن.

### trace قابل‌بازشدن برای هر turn

```text
script turn
→ claim ID
→ evidence ID
→ supporting excerpt
→ source block
→ locator
```

### actionها

- اجرای checks؛
- اجرای verifier؛
- targeted revision در صورت مجازبودن؛
- بازکردن issue؛
- مقایسه draft و revised؛
- ثبت calibration point پس از pass.

UI نباید اجازه ویرایش آزاد script را در نسخه اول بدهد، چون ویرایش دستی می‌تواند grounding contract را بشکند. اگر بعداً editor اضافه شد، هر turn ویرایش‌شده باید دوباره check و verify شود.

## مرحله ۷ — Audio Review

این مرحله پس از Milestone 6 فعال می‌شود.

### اطلاعات اصلی

- وضعیت synthesis هر segment؛
- duration و loudness؛
- ASR comparison؛
- pronunciation issue؛
- segmentهای regenerate‌شده؛
- player نهایی و transcript همگام.

### actionها

- regenerate segment معیوب؛
- اجرای مجدد Audio QA؛
- assemble final audio؛
- بازکردن ASR diff؛
- export package.

---

## navigation

navigation اصلی باید محدود باشد:

```text
Projects
Project overview
  ├── Brief
  ├── Sources
  ├── Pipeline
  ├── Episode
  ├── Script
  └── Audio
```

تب‌های downstream می‌توانند دیده شوند، اما تا پیش‌نیاز آماده نشده باید disabled با توضیح باشند. پنهان‌کردن کامل stageهای بعدی در Operator UI مفید نیست، چون operator باید نقشه کل pipeline را ببیند.

## action اصلی هر صفحه

هر صفحه فقط یک primary action دارد. مثال:

- Brief: `Confirm brief`
- Sources: `Confirm corpus`
- Pipeline: `Run next stage` یا `Retry failed stage`
- Episode: `Prepare script`
- Script: `Run verification` یا `Continue to audio`

actionهای کم‌اهمیت مانند raw JSON، download artifact یا rerun utility در سطح secondary قرار می‌گیرند.

## جریان Research-assisted آینده

پس از پیاده‌سازی Source Discovery:

```text
Confirm brief
→ Generate bounded query plan
→ Search providers
→ Normalize and deduplicate candidates
→ Show source authority, role and evidence availability
→ User selects sources
→ Freeze selected corpus manifest
→ Continue pipeline
```

منبع پیشنهادی تا پیش از انتخاب صریح کاربر وارد corpus نمی‌شود. metadata-only result نیز نباید با full-text usable source یکسان نمایش داده شود.

## معیار پذیرش UX

Operator UI زمانی از نظر flow قابل‌قبول است که:

- یک operator بتواند بدون مراجعه به README پروژه one-source را تا `script_verified` اجرا کند؛
- در هر لحظه بداند پروژه در چه stageای است و چرا متوقف شده؛
- هیچ stage نامعتبر از UI قابل اجرا نباشد؛
- retry ورودی‌های قبلی را حفظ کند و نتیجه آن run جدید بسازد؛
- تغییر upstream اثر downstream را پیش از تأیید نشان دهد؛
- trace از script به source با حداکثر سه interaction قابل مشاهده باشد؛
- خطای provider، quality gate و corpus insufficiency از هم قابل‌تشخیص باشند؛
- operator بتواند اجرای قطع‌شده را پس از restart سرویس ادامه دهد.

## خارج از محدوده نسخه اول

- account و authentication؛
- تیم و collaboration؛
- billing و quota؛
- mobile UI؛
- public sharing؛
- rich text editor عمومی؛
- drag-and-drop episode editing؛
- analytics dashboard محصول؛
- design system کامل؛
- automation خودمختار بدون human gate.
