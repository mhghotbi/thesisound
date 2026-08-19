# 03 — مرحله‌بندی ایجنت‌ها و قرارداد اجرا

مرتبط: شکل سیستم در [`02-architecture.md`](02-architecture.md)؛ جزئیات پیاده‌سازی در [`../02-pipeline/`](../02-pipeline/). gateهای این سند مرجع‌اند و [`05-quality-evaluation.md`](05-quality-evaluation.md) همان مقادیر را برای مرور سریع تکرار می‌کند.

> **بازنگری ۲۰۲۶-۰۸-۱۹ (سند ۱۰):** برای نیت `source_coverage` چهار stage جدید اضافه می‌شود (J0، J2، N0، Q′ در زیر) و قرارداد stageهای K، N، O، P، Q و R با «استخراج ۲.۰» و ممیزی promptها تغییر می‌کند؛ تغییرها در هر stage با «(سند ۱۰)» علامت خورده‌اند. متن کامل promptها در ضمیمهٔ A سند ۱۰ است.

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

## Stage J0 — Chapter detector · deterministic (سند ۱۰، P1)

**کار:** گروه‌بندی پیوستهٔ بلاک‌ها بر اساس `heading_path` (عمق ۰ سپس ۱) یا TOC سند؛ اگر هیچ‌کدام، یک فصل. خروجی `SourceChapter[]` با `detected_from: heading | toc | single` و دقیقهٔ برآوردی.
**ممنوع:** فراخوانی مدل · تأیید انسانی (فعلاً) · برش متن.

## Stage J — Document mapper · bounded model transform

**هدف:** ساخت نقشهٔ ساختاری و نقش بخش‌ها، بدون فشرده‌کردن کل سند به یک summary.
**ورودی:** heading tree، metadata بلاک‌ها، متن بخش در window کنترل‌شده. (سند ۱۰) partition = فصل، نه بودجهٔ کاراکتر؛ زیرتقسیم فقط اگر فصل از بودجه بزرگ‌تر باشد.
**خروجی:** function هر section، dependencies، key concepts، threadهای بین‌بخشی، flag «لازم برای فهم». (سند ۱۰، `document_map/1.1.0`) هر `key_concept` باید عیناً در بلاک‌های همان section آمده باشد.
**ممنوع:** داوری دربارهٔ درستی نویسنده · merge کردن بخش‌های متعارض · حذف section به بهانهٔ کم‌اهمیتی بدون ثبت.

## Stage J2 — Concept cells and edges · bounded model transform + gate قطعی (سند ۱۰، P1)

**واحد اجرا:** یک فصل. سه فراخوانی: سلول‌ها (`concept_cells/1.0.0`)، consolidate فقط با metadata (`concept_cells_consolidate/1.0.0`)، یال‌ها درون‌فصل و سپس بین دو فصل همسایه (`concept_edges/1.0.0`).
**خروجی:** `ConceptCell` (برچسب فارسی و مبدأ، نوع، tier ۱–۳، `block_ids`، `section_ids`، دلیل ریزدانگی، دقیقه) و `ConceptEdge` (۸ نوع، وزن، اطمینان، دلیل، `created_by`).
**gate قطعی:** هر section غیر front-matter ≥ ۱ سلول · هر سلول ≥ ۱ بلاک موجود · بدون برچسب ساختاری/بودار · dedup Jaccard ≥ ۰٫۸۵ · بودجهٔ فصل · توزیع tier · **بدون دور** در یال‌های ترتیبی (تعمیر با حذف کم‌وزن‌ترین یال و هشدار) · گزارش یتیم‌ها · پرچم `needs_review` برای هم‌پوشانی لغوی کم.
**ممنوع:** سلول برای مفهومی که در بلاک‌ها نیست · بریدن متن · حذف یال‌های `created_by=user` در بازسازی (overlay).

## Stage K — Evidence extractor · bounded model transform، قابل parallel شدن

**واحد اجرا:** یک argument unit یا section کوچک، نه chunk تصادفی. (سند ۱۰، `source_coverage`) فقط بلاک‌های سلول‌های در دامنه، با عمق `extended`.
**خروجی:** (سند ۱۰، استخراج ۲.۰ — `evidence_extraction/2.0.0`) **یک انبارهٔ واحد**: هر قلم یک claim با excerpt و `claim_type` از جمله `definition / distinction / example / objection / response`؛ `must_not_be_lost: bool` روی claim؛ `term`/`contrast` ساختاری؛ `more_claims_available` برای گذر دوم روی بلاک‌های متراکم. فهرست‌های جداگانهٔ تعریف/تمایز/مثال/اعتراض/پاسخ حذف می‌شوند.
**gate:** excerpt باید substring یا match نرمال‌شدهٔ متن ورودی باشد · locator باید متعلق به همان block باشد · confidence پایین حذف نمی‌شود بلکه flag می‌شود · inference از direct support جداست · (سند ۱۰) `excerpt_char_coverage` هر بلاک ثبت و بلاک‌های tier-1 با پوشش < ۰٫۳۵ در گزارش به‌عنوان `thin_extraction` می‌آیند.
**validation قطعی پس از مدل:** تطابق excerpt، وجود block ID، محدودهٔ locator، تشخیص claim تکراری، (سند ۱۰) میدان‌های الزامی هر نوع (`definition` → `term`، `distinction` → `contrast`).

## Stage L — Claim reconciler · bounded model transform + خوشه‌بندی deterministic

**هدف:** وصل‌کردن claimهای مشابه به یک canonical claim، بدون نابودکردن اختلاف‌ها.
**اول deterministic:** نرمال‌سازی lexical، duplicate دقیق/نزدیک، پیوند منبع و locator.
**سپس مدل، فقط برای خوشه‌های مبهم:** equivalent · narrower/broader · supports · contradicts · unrelated.
**خروجی:** `ClaimRecord`
**ممنوع:** merge دو تفسیر مخالف صرفاً به این دلیل که دربارهٔ یک مفهوم‌اند · (سند ۱۰، `claim_reconciliation/1.1.0`) merge بین `claim_type`های متفاوت؛ merge گروه‌ها `canonical_claim_id` برمی‌گرداند و `must_not_be_lost` و قیدها را اجتماع می‌گیرد.

## Stage M — Coverage auditor · bounded model transform

**هدف:** سنجش کفایت corpus برای brief، نه زیادکردن تعداد منبع.
**خروجی برای هر subquestion:** well covered / partial / missing، به‌همراه evidence و claim IDs، نقش غایب، و ریسک نادیده‌گرفتن.
**stop conditions:** پوشش central question و objectiveهای اصلی · قابل‌قبول بودن gap باقی‌مانده با scope فعلی · بی‌نتیجه بودن دو round اخیر · تأیید کاربر برای ادامه با corpus فعلی.
**ممنوع:** trigger شدن جست‌وجوی جدید با هر gap کوچک.
(سند ۱۰) برای `source_coverage` این stage مشورتی است؛ گیت «۸۰٪ مدت» جای خود را به **بررسی پوشش هر سلول** می‌دهد (سلول در دامنه بدون claim → در گزارش، هرگز بلاک‌کننده).

## Stage N0 — Part packer · deterministic (سند ۱۰، P3)

**کار:** بسته‌بندی سلول‌های در دامنه به `LessonPart`ها: آمادگی توپولوژیک روی یال‌های ترتیبی، ترتیب کتاب به‌عنوان prior، جاذبه/دافعهٔ یال‌ها، **قاعدهٔ پرکردن**: هر بخش بین ۰٫۸ و ۱٫۰ × طول اپیزود، مرز ترجیحاً روی تغییر فصل/بخش، فقط بخش آخر کوتاه‌تر. `graph_backed` برای هر بخش محاسبه می‌شود.
**ممنوع:** فراخوانی مدل · وابستگی به گراف برای پیشروی (اگر گراف تُنُک بود، ترتیب کتاب کافی است).

## Stage N — Episode architect · bounded model transform

**هدف:** تبدیل claim ledger به مسیر فهم شنیداری. (سند ۱۰، `episode_plan/1.3.0`) به‌ازای هر بخش، با claimهای همان بخش.
**خروجی:** listener outcome، segmentها، claim IDs هر segment، پرسش کلیدی، speaker dynamic، بودجهٔ زمان، claimهای عمداً حذف‌شده. (سند ۱۰) segmentها `part_index` دارند.
**gate:** مجموع زمان در محدوده (برای `source_coverage`: بدون کف، سقف ۱٫۲۵ × طول اپیزود، وگرنه بازبسته‌بندی) · هر segment purpose مستقل دارد · prerequisite پیش از مفهوم وابسته · هیچ claim خارج از ledger · حذف مهم ثبت شده · (سند ۱۰) **هر claim با `must_not_be_lost` یا در segment است یا با دلیل در `deliberately_omitted_claims`** — هرگز بی‌صدا غایب · `known_concepts` حداکثر یک جملهٔ یادآوری، نه segment.

## Stage O — Evidence pack builder · deterministic

**کار برای هر segment:** claim IDs، evidence items، block اصلی، block همسایه در صورت وابستگی، نامزدهای glossary، انتساب منبع. (سند ۱۰) به‌علاوهٔ خودِ `ClaimRecord`ها (متن، `support_status`، قیدها، `must_not_be_lost`) تا نویسنده و verifier عدم‌قطعیت را ببینند.
**retrieval در MVP:** claim mapping، heading/locator، SQLite FTS5، neighbor expansion.

مدل نمی‌تواند خودش کل corpus را browse کند؛ evidence pack محدود دریافت می‌کند.

## Stage P — Glossary builder · bounded model transform + override انسانی

**خروجی هر term:** اصطلاح مبدأ، معادل فارسی ترجیحی، صورت اولین کاربرد، صورت کاربردهای بعدی، راهنمای تلفظ، وضعیت مورد اختلاف، اصطلاح‌هایی که نباید در هم ادغام شوند.
**gate:** اصطلاح‌های contrastive جدا بمانند · ترجمهٔ جاافتاده با citation ثبت شود · نام اشخاص و آثار consistent باشد.

کاربر باید بتواند glossary را override کند. (سند ۱۰، `glossary/1.1.0`) seed قطعی از سلول‌های مفهومی (`label_source → label_fa`) و claimهای `definition`؛ مدل وقتی هم فعال می‌شود که منبع فارسی باشد ولی برچسب مبدأ یا تعریف داشته باشد، نه فقط با توکن لاتین.

## Stage Q — Persian script writer · bounded model transform

**ورودی فقط:** یک segment plan، evidence pack همان segment (با `ClaimRecord`ها)، glossary، دنبالهٔ کوتاه segment قبل، قرارداد سبک، (سند ۱۰) `known_concepts` و موقعیت بخش.
**خروجی:** turnهای فارسی به‌همراه claim IDs.
**ممنوع:** دانش خارج از evidence pack · مثال ساختگی بدون `editorial_only` · نقل‌قول جعلی · filler · تکرار حرف گویندهٔ قبلی · شوخی رادیویی · ترجمه‌زدگی · نسبت‌دادن یک تفسیر به خود نویسنده · (سند ۱۰، `persian_script_segment/1.3.0`) **عدد، تاریخ، نام، مکان، تشبیه یا مقایسه‌ای که در pack نیست** — تشبیهِ لازم فقط در turn ویرایشی و بدون گزارهٔ واقعی · گفتن claim با `support_status` uncertain/contested بدون قید آن · اشاره به مفاهیم حذف‌شده با فشردگی به‌عنوان «گفته‌شده».
**وضع فعلی:** نسخهٔ فعال امروز `1.3.0` است؛ قرارداد grounding و dynamics در system prompt برگشته (P0.5).
**retry:** schema failure → یک retry · evidence failure → revise فقط turnهای مشخص · style failure → یک بازنویسی سبک بدون تغییر claim IDs · بیش از ۳ attempt → human review.

## Stage Q′ — Prose lesson writer · bounded model transform (سند ۱۰، P4)

همان قرارداد Q با واحد «پاراگراف» به‌جای «turn» و بدون گوینده (`persian_lesson_prose/1.0.0`)؛ checks، verifier و remediation مشترک؛ برای `delivery == text` پس از `SCRIPT_VERIFIED` پروژه `COMPLETE` می‌شود.

## Stage R — Script verifier · adversarial model transform + بررسی‌های قطعی

**استقلال:** prompt متفاوت؛ ترجیحاً model call و context مستقل. verifier متن جایگزین کامل تولید نمی‌کند مگر برای turn معیوب، و حق افزودن claim جدید ندارد.
**بررسی‌ها:** claim بدون پشتوانه، انتساب اشتباه، جابه‌جایی certainty، قید ازدست‌رفته، اختلاف فروپاشیده، مثال ساختگی، خطای اصطلاح، ناهماهنگی claim ID، (سند ۱۰، `script_verifier/1.2.0`) جزئیات بی‌پشتوانه (عدد/تاریخ/نام/مکان/نقل‌قول)، تشبیه و مقایسهٔ خارج از pack، استفاده از `known_concepts` به‌عنوان شاهد، claim `must_not_be_lost` برنامه‌ریزی‌شده ولی گفته‌نشده. **چک قطعی جدید:** `unsupported_specifics` در `script_checks` (عدد، سال، نام لاتین، نقل‌قول باید در excerptهای استنادشده یا بلاک‌های pack باشد).
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
