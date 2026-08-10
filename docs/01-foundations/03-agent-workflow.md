# 03 — مرحله‌بندی ایجنت‌ها و قرارداد اجرا

مرتبط: شکل سیستم در [`02-architecture.md`](02-architecture.md)؛ جزئیات پیاده‌سازی در [`../02-pipeline/`](../02-pipeline/). gateهای این سند مرجع‌اند و [`05-quality-evaluation.md`](05-quality-evaluation.md) همان مقادیر را برای مرور سریع تکرار می‌کند.

## اصل اول: بیشتر مراحل «ایجنت» نیستند

واژهٔ agent فقط برای مدلی با هدف محدود، ورودی محدود و خروجی schema-bound به کار می‌رود. هیچ agent اجازه ندارد pipeline را تغییر دهد، منبع را بدون ثبت اضافه کند یا ابزار جدید انتخاب کند.

| نوع stage | مسئولیت | مثال |
|---|---|---|
| Deterministic | کار قابل‌تعریف با کد | hash، dedup، state transition، schema validation |
| Bounded model transform | تفسیر یا تولید محدود | research brief، document map، episode plan |
| Human gate | تصمیمی که بر روایت اثر می‌گذارد | انتخاب منبع، پذیرش scope، تأیید نمونهٔ صوت |

## قواعد مشترک تمام model stageها

هر فراخوانی مدل باید این‌ها را داشته باشد: `stage_name`، `prompt_version`، `model_id`، `input_artifact_hashes`، schema (JSON Schema یا Pydantic)، budget توکن/زمان، retry policy، طبقه‌بندی failure، سیاست نگه‌داری پاسخ خام، و نتیجهٔ ارزیابی.

**مدل اجازه ندارد:** URL، DOI، نقل‌قول یا metadata جعل کند · منبع جدید را بی‌صدا وارد corpus کند · schema را با prose اضافی بشکند · uncertainty را حذف کند · منبع metadata-only را full-text فرض کند · stage بعدی را خودش اجرا کند.

---

# Workflow دقیق

## Stage A — Project initializer · deterministic

**ورودی:** raw user input، settings اختیاری، فایل‌ها و URLهای اولیه.
**کار:** ساخت project ID، workspace، file hash، manifest ورودی خام؛ `state=DRAFT`.
**failure:** فایل unreadable، فرمت unsupported، خطای permission در workspace.

مدل در این مرحله استفاده نمی‌شود.

## Stage B — Research brief builder · bounded model transform

**هدف:** تبدیل ورودی مبهم به مسئله‌ای که بتوان برایش منبع پیدا کرد و اپیزود طراحی کرد.
**ورودی مجاز:** raw input، تنظیمات audience/depth/duration/mode، **metadata** فایل‌های کاربر — نه کل متن فایل.
**خروجی:** `ResearchBrief`
**gate:** central question مشخص · scope متناسب با مدت · objectiveهای قابل سنجش · ambiguity بحرانی ثبت‌شده.
**ممنوع:** پاسخ‌دادن به خود موضوع · پیشنهاد منبع با عنوان ساختگی · فرض اینکه یک نام حتماً به شخص خاصی اشاره دارد وقتی ابهام واقعی هست.
**retry:** حداکثر ۲ بار — اول با validation error، بعد با instruction دقیق‌تر برای فیلد ناقص. سپس human correction.

## Stage C — Query planner · bounded model transform

**هدف:** ساخت query family، نه پیداکردن مستقیم منبع.
**ورودی:** ResearchBrief، metadata منابع کاربر، coverage targetها، شمارهٔ round.
**خروجی:** فهرست `SearchQuery` با purpose و source role.
**query familyها** بسته به موضوع: primary work/person exact · canonical overview · scholarly interpretation · criticism/counter-position · recent scholarship · منابع فارسی · edition/translation metadata.
**سقف:** دور اول ۱۲ query، دور دوم ۸، gap round ۵؛ هر query باید reason و provider داشته باشد.
**ممنوع:** نتیجهٔ ساختگی · queryهای عمومی تکراری · استفاده از recency برای موضوعی که recency در آن ارزش ندارد · query برای جمع‌آوری نامحدود منبع.

## Stage D — Search executors · deterministic adapters

**کار:** اجرای query روی provider تعیین‌شده، ثبت metadata درخواست/پاسخ، normalize کردن نتیجه، احترام به rate limit، backoff و retry.

**provider routing:** امروز تنها مسیر اجراشونده **Gemini Google Search grounding** است؛ سیاست هر stage در [`../04-integrations/01-gemini-grounding.md`](../04-integrations/01-gemini-grounding.md). مقادیر `SearchQuery.provider` در `domain.py` (`openalex`, `semantic_scholar`, `crossref`, `google_books`, `open_library`, `web`) برای connectorهای آینده رزرو شده‌اند و connector مستقلی پشتشان نیست.

**retry:** 429 → backoff بر اساس header · 5xx → حداکثر ۳ بار · 4xx syntax/auth → بدون retry خودکار · نتیجهٔ خالی → replan توسط query planner، نه تکرار همان request.

## Stage E — Source normalizer and deduplicator · deterministic

**کار:** canonical DOI، عنوان normalize‌شده، author/year، canonical URL، تشخیص duplicate، access level، ردیابی origin.
**کلیدهای dedup به‌ترتیب:** DOI ← OpenAlex/S2 ID ← ISBN + edition ← canonical URL ← عنوان normalize‌شده + نویسندهٔ اول + سال.

مدل در dedup تصمیم نهایی نمی‌گیرد؛ فقط duplicateهای مبهم را flag می‌کند.

## Stage F — Source triage · hybrid

**deterministic:** نوع منبع، venue/publisher، سال انتشار، در دسترس بودن full text، DOI/ISBN، کلاس domain، وضعیت duplicate.
**model transform:** دلیل relevance، perspective، نقش محتمل منبع، محدودیت‌ها، دلیل پذیرش/رد.
**خروجی:** `SourceCandidate`
**gate:** مدل نباید `access=FULL_TEXT` تعیین کند؛ access فقط از connector یا وضعیت parse می‌آید.
**source classes:** primary text · peer-reviewed یا university press · academic reference · نهاد معتبر · وب عمومی · نامعلوم. این‌ها ranking hint‌اند، نه حکم نهایی دربارهٔ حقیقت.

## Stage G — Human source selection · human gate

کاربر برای هر منبع یکی را انتخاب می‌کند: Include · Exclude · Background only · Recommended reading only.

سیستم باید نمایش دهد: دلیل پیشنهاد، role، access، محدودیت، وضعیت duplicate، و اینکه full text موجود هست یا نه.

**قانون:** بدون انتخاب صریح کاربر، منبع کشف‌شده وارد evidence corpus نمی‌شود.

## Stage H — Parser inspector/router · deterministic

**inspect:** نوع فایل، رمزگذاری، تعداد صفحه، نمونهٔ چگالی متن، صفحه‌های صرفاً تصویری، احتمال multi-column، اندازه، زبان.
**route:** native برای متن ساده · EPUB برای EPUB · Docling پیش‌فرض برای سند ساختاریافته · MinerU برای scan و layout پیچیده · OCR محلی برای صفحهٔ تصویری ([`../04-integrations/04-self-hosted-ocr.md`](../04-integrations/04-self-hosted-ocr.md)).
**ممنوع:** انتخاب parser توسط LLM بر اساس filename.

## Stage I — Parse quality auditor · deterministic-first، مدل فقط هنگام شک

**heuristic:** صفحهٔ خالی، outlierهای چگالی متن، replacement char، تکرار header/footer، از دست رفتن heading، ناهنجاری ترتیب صفحه، پوشش locator.
**ورودی مدل:** فقط نمونه‌های مشکوک + render صفحه، نه کل سند.
**خروجی:** pass · pass_with_warning · retry_with_other_parser · manual_review.
**retry:** حداکثر یک fallback خودکار parser؛ بعد از آن manual review — نه چرخهٔ بی‌نهایت parserها.

## Stage J — Document mapper · bounded model transform

**هدف:** ساخت نقشهٔ ساختاری و نقش بخش‌ها، بدون فشرده‌کردن کل سند به یک summary.
**ورودی:** heading tree، metadata بلاک‌ها، متن بخش در window کنترل‌شده.
**خروجی:** function هر section، dependencies، key concepts، threadهای بین‌بخشی، flag «لازم برای فهم».
**ممنوع:** داوری دربارهٔ درستی نویسنده · merge کردن بخش‌های متعارض · حذف section به بهانهٔ کم‌اهمیتی بدون ثبت.

## Stage K — Evidence extractor · bounded model transform، قابل parallel شدن

**واحد اجرا:** یک argument unit یا section کوچک، نه chunk تصادفی.
**خروجی:** claims، تعاریف، تمایزها، مثال‌ها، اعتراض‌ها، قیدها، excerpt دقیق پشتیبان، locator.
**gate:** excerpt باید substring یا match نرمال‌شدهٔ متن ورودی باشد · locator باید متعلق به همان block باشد · confidence پایین حذف نمی‌شود بلکه flag می‌شود · inference از direct support جداست.
**validation قطعی پس از مدل:** تطابق excerpt، وجود block ID، محدودهٔ locator، تشخیص claim تکراری.

## Stage L — Claim reconciler · bounded model transform + خوشه‌بندی deterministic

**هدف:** وصل‌کردن claimهای مشابه به یک canonical claim، بدون نابودکردن اختلاف‌ها.
**اول deterministic:** نرمال‌سازی lexical، duplicate دقیق/نزدیک، پیوند منبع و locator.
**سپس مدل، فقط برای خوشه‌های مبهم:** equivalent · narrower/broader · supports · contradicts · unrelated.
**خروجی:** `ClaimRecord`
**ممنوع:** merge دو تفسیر مخالف صرفاً به این دلیل که دربارهٔ یک مفهوم‌اند.

## Stage M — Coverage auditor · bounded model transform

**هدف:** سنجش کفایت corpus برای brief، نه زیادکردن تعداد منبع.
**خروجی برای هر subquestion:** well covered / partial / missing، به‌همراه evidence و claim IDs، نقش غایب، و ریسک نادیده‌گرفتن.
**stop conditions:** پوشش central question و objectiveهای اصلی · قابل‌قبول بودن gap باقی‌مانده با scope فعلی · بی‌نتیجه بودن دو round اخیر · تأیید کاربر برای ادامه با corpus فعلی.
**ممنوع:** trigger شدن جست‌وجوی جدید با هر gap کوچک.

## Stage N — Episode architect · bounded model transform

**هدف:** تبدیل claim ledger به مسیر فهم شنیداری.
**خروجی:** listener outcome، segmentها، claim IDs هر segment، پرسش کلیدی، speaker dynamic، بودجهٔ زمان، claimهای عمداً حذف‌شده.
**gate:** مجموع زمان در محدوده · هر segment purpose مستقل دارد · prerequisite پیش از مفهوم وابسته · هیچ claim خارج از ledger · حذف مهم ثبت شده.

## Stage O — Evidence pack builder · deterministic

**کار برای هر segment:** claim IDs، evidence items، block اصلی، block همسایه در صورت وابستگی، نامزدهای glossary، انتساب منبع.
**retrieval در MVP:** claim mapping، heading/locator، SQLite FTS5، neighbor expansion.

مدل نمی‌تواند خودش کل corpus را browse کند؛ evidence pack محدود دریافت می‌کند.

## Stage P — Glossary builder · bounded model transform + override انسانی

**خروجی هر term:** اصطلاح مبدأ، معادل فارسی ترجیحی، صورت اولین کاربرد، صورت کاربردهای بعدی، راهنمای تلفظ، وضعیت مورد اختلاف، اصطلاح‌هایی که نباید در هم ادغام شوند.
**gate:** اصطلاح‌های contrastive جدا بمانند · ترجمهٔ جاافتاده با citation ثبت شود · نام اشخاص و آثار consistent باشد.

کاربر باید بتواند glossary را override کند.

## Stage Q — Persian script writer · bounded model transform

**ورودی فقط:** یک segment plan، evidence pack همان segment، glossary، دنبالهٔ کوتاه segment قبل، قرارداد سبک.
**خروجی:** turnهای فارسی به‌همراه claim IDs.
**ممنوع:** دانش خارج از evidence pack · مثال ساختگی بدون `editorial_only` · نقل‌قول جعلی · filler · تکرار حرف گویندهٔ قبلی · شوخی رادیویی · ترجمه‌زدگی · نسبت‌دادن یک تفسیر به خود نویسنده.
**retry:** schema failure → یک retry · evidence failure → revise فقط turnهای مشخص · style failure → یک بازنویسی سبک بدون تغییر claim IDs · بیش از ۳ attempt → human review.

## Stage R — Script verifier · adversarial model transform + بررسی‌های قطعی

**استقلال:** prompt متفاوت؛ ترجیحاً model call و context مستقل. verifier متن جایگزین کامل تولید نمی‌کند مگر برای turn معیوب، و حق افزودن claim جدید ندارد.
**بررسی‌ها:** claim بدون پشتوانه، انتساب اشتباه، جابه‌جایی certainty، قید ازدست‌رفته، اختلاف فروپاشیده، مثال ساختگی، خطای اصطلاح، ناهماهنگی claim ID.
**pass:** unsupported claim ratio = 0 · blocking issue = 0 · high issue = 0 · medium یا revise شده یا با یادداشت پذیرفته شده.

## Stage S — TTS segment planner · deterministic-first

**کار:** شکستن در مرز turn و مفهوم، حفظ پرسش و پاسخ مرتبط در کنار هم، هدف چند دقیقه صوت، header ثابت، یادداشت‌های تلفظ.

LLM فقط وقتی استفاده می‌شود که segmentation با punctuation و مرز turn ممکن نباشد.

## Stage T — TTS renderer · deterministic adapter

**ورودی:** transcript ثابت، پیکربندی صدای گوینده، director notes، hash idempotency.
**retry:** 5xx گذرا → exponential backoff · دریافت متن به‌جای صوت → retry · مثبت کاذب prohibited → سخت‌کردن قالب prompt و یک retry · drift یا ناهماهنگی صدا → بازتولید با trigger شدن QA.
**ممنوع:** renderer حق تغییر transcript ندارد.

## Stage U — Audio QA · deterministic + bounded model transform

**deterministic:** قابل decode بودن صوت، duration غیرصفر، نبود clipping، transcript ASR، محتوای افتاده/تکراری، بریدگی انتها، نشت برچسب گوینده، نشت instruction.
**model-assisted:** فقط ناهماهنگی معنایی‌ای که diff ساده حل نمی‌کند.
**خروجی:** pass · بازتولید segment · بازبینی دستی تلفظ.

---

# بودجه و توقف

```json
{
  "max_search_rounds": 3,
  "max_sources_for_user_review": 30,
  "max_selected_sources": 12,
  "max_parse_fallbacks_per_file": 1,
  "max_model_retries_per_stage": 2,
  "max_script_revision_rounds": 3,
  "max_tts_attempts_per_segment": 3
}
```

Budget فقط برای هزینه نیست؛ از حلقهٔ بی‌پایان agent و انباشت خطا جلوگیری می‌کند.

# مشاهده‌پذیری

برای هر stage ثبت می‌شود: input hash، output hash، prompt version، model/provider، latency، usage، دلیل retry، نتیجهٔ gate، warningها. بدون این داده‌ها بهبود prompt بر اساس حدس خواهد بود. قرارداد مشترک ثبت در [`../04-integrations/05-model-observability.md`](../04-integrations/05-model-observability.md).
