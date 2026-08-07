# 01 — نقد نسخه اولیه معماری

این سند عمداً پیشنهاد اولیه را نقد می‌کند. هدف حفظ طرح قبلی نیست؛ هدف حذف بخش‌هایی است که برای یک محصول شخصی کوچک، هزینه و خطای بیشتری از ارزششان دارند.

## ۱. معماری بیش‌ازحد enterprise بود

نسخه اولیه از ابتدا PostgreSQL، pgvector، Redis، worker مستقل، API و Frontend جدا پیشنهاد می‌کرد. این اجزا در production ممکن است منطقی باشند، اما ریسک اصلی Thesisound مقیاس نیست. ریسک اصلی این است که:

- استخراج سند درست نباشد؛
- مدل نکته‌های مهم را حذف کند؛
- فارسی طبیعی نباشد؛
- TTS نام‌ها را خراب بخواند؛
- خروجی از NotebookLM بهتر نباشد.

### اصلاح

نسخه اول CLI-first است:

- فایل و JSON artifact روی دیسک؛
- SQLite در صورت نیاز به index؛
- یک process؛
- بدون queue خارجی؛
- بدون UI تا زمان اثبات vertical slice.

## ۲. ادعای AnyDoc دقیق نبود

در پیشنهاد اولیه AnyDoc به‌عنوان کتابخانه متن‌باز Firecrawl معرفی شده بود. مستندات رسمی فعلی Firecrawl یک `/parse` میزبانی‌شده با موتور Rust را تأیید می‌کنند، اما این برای انتخاب یک dependency متن‌باز مستقل کافی نیست.

### اصلاح

- Docling: parser محلی پیش‌فرض برای فرمت‌های عمومی و PDF ساختاریافته؛
- MinerU: fallback برای scan، layout پیچیده، فرمول و multi-column؛
- Firecrawl Parse: fallback میزبانی‌شده اختیاری، نه dependency اصلی؛
- MarkItDown: ابزار سبک برای conversion ساده، نه parser اصلی PDF دانشگاهی.

انتخاب نهایی باید با benchmark روی corpus خود پروژه انجام شود، نه شهرت GitHub.

## ۳. «چند مدل کوچک پشت سر هم» لزوماً دقیق‌تر نیست

زنجیره خلاصه‌سازی محلی و سپس خلاصه‌سازی سراسری می‌تواند information bottleneck بسازد. وقتی مرحله اول یک قید یا تمایز را حذف کند، مرحله بعد دیگر راهی برای بازسازی آن ندارد.

### اصلاح

- خروجی تحلیل بخش‌ها «section card و evidence record» است، نه خلاصه ادبی کوتاه؛
- planner می‌تواند از recordها استفاده کند؛
- script writer برای هر segment دوباره original spans را دریافت می‌کند؛
- verifier نیز به متن اصلی برمی‌گردد.

خلاصه میانی index است، نه source of truth.

## ۴. تعداد ایجنت‌ها زیاد و مرز مسئولیتشان مبهم بود

هر بار که یک LLM آزادانه تصمیم بگیرد، فضای خطا بزرگ‌تر می‌شود. عبارت‌هایی مثل «agent منابع را پیدا کند» یا «agent corpus را بسازد» قرارداد اجرایی نیستند.

### اصلاح

هر stage یکی از سه نوع است:

1. **Deterministic:** دانلود، hash، dedup، state transition، chunk assembly، schema validation؛
2. **Model transform:** ورودی محدود، خروجی schema-bound، بدون tool autonomy؛
3. **Human gate:** انتخاب منابع، تأیید scope و پذیرش کیفیت نمونه.

مدل فقط جایی استفاده می‌شود که ambiguity واقعی وجود دارد.

## ۵. یک score عددی برای اعتبار منبع بیش‌ازحد مطمئن بود

دادن `authority_score=87` به یک منبع، دقت جعلی تولید می‌کند. اعتبار منبع تابع role و claim است. یک متن اصلی ممکن است برای «نظر نویسنده» معتبر و برای «درستی تاریخی ادعا» ناکافی باشد.

### اصلاح

Source triage دو بخش دارد:

- hard facts و کلاس منبع به‌صورت deterministic؛
- relevance، perspective و limitation با کمک مدل.

خروجی به‌جای یک نمره جادویی شامل این‌هاست:

- source role؛
- access level؛
- authority class؛
- use-as-evidence eligibility؛
- relevance reasons؛
- limitations؛
- duplicate status.

## ۶. metadata با evidence مخلوط شده بود

OpenAlex، Crossref، Google Books و Semantic Scholar اغلب metadata یا abstract می‌دهند. این داده برای کشف منبع خوب است، اما نباید از آن نتیجه گرفت که متن کامل خوانده شده است.

### اصلاح

هر source یک `SourceAccess` دارد:

- full text؛
- partial text؛
- abstract only؛
- metadata only؛
- inaccessible.

فقط full-text source انتخاب‌شده می‌تواند claim evidence تولید کند. Abstract می‌تواند برای discovery یا معرفی منبع استفاده شود، نه برای نسبت‌دادن جزئیات به متن کامل.

## ۷. Search plan فاقد stop condition و budget بود

«جست‌وجوی دقیق و مفصل» بدون حد توقف، به تعداد منبع بیشتر و کیفیت کمتر ختم می‌شود.

### اصلاح

جست‌وجو حداکثر سه round دارد:

1. orientation؛
2. targeted coverage؛
3. gap search فقط برای شکاف ثبت‌شده.

جست‌وجو متوقف می‌شود اگر:

- source-roleهای لازم پوشش داده شده‌اند؛
- دو round اخیر منبع جدید با ارزش بالا نداده‌اند؛
- budget درخواست یا زمان تمام شده؛
- کاربر corpus را تأیید کرده است.

## ۸. ترجمه یک سناریوی کامل انگلیسی ریسک اضافه بود

مسیر «سناریوی انگلیسی صیقل‌خورده → ترجمه فارسی» می‌تواند attribution، certainty و اصطلاحات را در دو مرحله تغییر دهد.

### اصلاح

- ابتدا یک canonical semantic plan ساخته می‌شود: claimها، ترتیب، نقش گوینده و transitions؛
- glossary دو‌زبانه ساخته می‌شود؛
- سناریوی فارسی مستقیماً از plan و evidence pack نوشته می‌شود؛
- verifier تغییر معنا و اصطلاح را بررسی می‌کند.

متن انگلیسی کامل فقط برای آزمایش یا fallback است، نه مسیر اصلی.

## ۹. pgvector برای MVP لازم نبود

کتاب یا corpus یک کاربر در MVP آن‌قدر بزرگ نیست که بدون vector DB قابل بازیابی نباشد. اضافه‌کردن embedding، migration و index tuning زودهنگام است.

### اصلاح

MVP:

- heading path؛
- locator؛
- claim-to-block mapping؛
- SQLite FTS5؛
- deterministic neighbor expansion.

اگر retrieval benchmark نشان داد recall کافی نیست، embedding اضافه می‌شود. در آن زمان Gemini Embedding یا Gemini File Search بررسی خواهد شد.

## ۱۰. TTS به‌عنوان آخرین مرحله ساده دیده شده بود

TTS preview ممکن است در خروجی‌های بلند دچار drift، voice inconsistency، خواندن instruction یا خطای موقت شود. API رسمی نیز تقسیم خروجی بلند و retry را توصیه می‌کند.

### اصلاح

- segmentهای کوتاه چنددقیقه‌ای؛
- idempotency key برای هر segment؛
- retry محدود؛
- ASR پس از تولید؛
- مقایسه expected transcript با transcript صوت؛
- بازتولید فقط segment معیوب.

## ۱۱. model name در معماری hard-code شده بود

مدل‌های Gemini سریع تغییر می‌کنند. previewها shut down می‌شوند و aliasها عوض می‌شوند.

### اصلاح

- نام مدل فقط در config؛
- startup capability check؛
- `models.list` یا smoke test؛
- fallback model؛
- ثبت model ID و prompt version در هر artifact.

## ۱۲. privacy، copyright و data handling غایب بود

کتاب کاربر ممکن است copyrighted، unpublished یا حساس باشد. Free Tier برخی providerها ممکن است داده را برای بهبود محصول استفاده کند.

### اصلاح

- local parsing پیش‌فرض؛
- نمایش هشدار قبل از upload به provider؛
- عدم انتشار متن یا صوت مشتق‌شده بدون حق لازم؛
- raw file و provider response در Git ثبت نمی‌شوند؛
- retention قابل تنظیم؛
- ثبت provenance بدون ذخیره غیرضروری متن کامل در log.

## نسخه بهبود‌یافته در یک جمله

یک orchestrator ساده، deterministic و قابل‌ممیزی که مدل‌ها را به transformهای محدود با schema مشخص تبدیل می‌کند؛ نه مجموعه‌ای از agentهای آزاد که خلاصه‌های یکدیگر را بازنویسی می‌کنند.
