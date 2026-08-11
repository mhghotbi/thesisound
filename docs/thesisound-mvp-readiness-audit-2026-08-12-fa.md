# Thesisound — MVP Readiness Audit

**تاریخ audit:** ۲۰۲۶-۰۸-۱۲
**Baseline:** commit `434f5c0` (branch `main`)
**دامنه:** بررسی read-only از repo، workflowها، تست‌ها، artifactهای واقعی در `workspaces/`، و پژوهش وب درباره‌ی NotebookLM. هیچ کدی تغییر نکرد.

**معیار این audit:** feature-completeness یا معماری ایده‌آل نیست. سؤال این است:

```text
Does it work?
Does the user get real value?
Is the quality good enough to trust/use?
Is it cheap and simple enough for an early MVP?
```

---

## ۱. MVP واقعی محصول

مسیر پیاده‌شده در repo با شش gate انسانی: Brief → منابع → تأیید corpus → تأیید Episode Plan → بازبینی script → شروع صوت.

**وضعیت اثبات‌شده‌ی این مسیر:**

| مرحله | اجرای واقعی ثبت‌شده |
|---|---|
| Brief → corpus → evidence | ۳ پروژه |
| → coverage → plan → script | **۱ پروژه** (`f781a5c7`، ۱۰ دقیقه، یک EPUB انگلیسی) |
| → audio | **۱ بار**، ۹ اوت، برای یک script قدیمی‌تر؛ archive شده، `final.wav` هیچ‌جا باقی نمانده |
| PDF فارسی → script | **صفر** |
| PDF اسکن‌شده / OCR | **صفر** (فقط harness در `benchmarks/persian_ocr/`، بدون result) |
| web discovery → capture | **صفر** (stage `web_source_capture` هرگز اجرا نشده) |
| چند منبع + reconciliation | **صفر** |
| مدت‌های غیر از ۱۰ دقیقه | **صفر** |

پس: مسیر end-to-end یک بار کامل شده، ولی **نه با script فعلی، نه با منبع فارسی، و نه در بیش از یک پیکربندی**.

---

## ۲. Product Value

**نقطه‌ی قوت واقعی:** خروجی موجود در `script/script-draft.json` از نظر source fidelity خوب است. ۲۲ turn، هر turn محتوایی به `claim_id` و `evidence_id` واقعی وصل، attribution درست، nuance آرنت (تمایز Labor/Work/Action، تکثر، برآمدن جامعه) حفظ شده. فارسی طبیعی و قابل‌شنیدن است. این جدی‌تر از یک summary معمولی است.

**سه مشکل ارزشی که در همان فایل قابل اندازه‌گیری‌اند:**

۱. **چگالی اطلاعات بسیار پایین.** از یک کتاب کامل، ۷۰ claim استخراج شد؛ فقط **۶ claim** وارد اپیزود ۱۰ دقیقه‌ای شد. یعنی ۹۱٪ از کاری که هزینه‌اش پرداخت شد دور ریخته شد.

۲. **تکرار ساختاری.** الگوی هر segment: A ادعا را می‌گوید → B همان را به‌شکل سؤال بازگو می‌کند → A **همان `claim_id`** را دوباره توضیح می‌دهد → B خلاصه می‌کند. در `seg-001`، turnهای ۳ و ۴ و ۵ هر سه `clm-d47c35b404043ad8` هستند.

۳. **علتش hardcode شده است.** در `episode/budget-report.json`:

```text
available_claim_seconds: 195        ← ۳٫۲۵ دقیقه محتوای واقعی
explanation_expansion_factor: 4.0   ← src/thesisound/services/episode_budget.py:17
estimated_supported_minutes: 13.0
```

یعنی ۳٫۲۵ دقیقه محتوا با ضریب ثابت ۴ به «۱۳ دقیقه قابل‌پشتیبانی» تبدیل می‌شود. این دقیقاً padding است — همان چیزی که `PRODUCT.md` قول داده بود انجام ندهد: «corpus ناکافی با padding به مدت هدف نمی‌رسد».

**نتیجه:**

```text
Acceptable MVP value — ولی مشروط
```

ارزش هسته (اعتماد + ردیابی) واقعی است و از NotebookLM متمایز است. اما آنچه امروز به گوش کاربر می‌رسد، شش ایده است که سه بار تکرار شده‌اند. با یک اپیزود دیگر، کاربر متوجه الگو می‌شود.

---

## ۳. Core Features

**Must work for MVP**
document ingestion (PDF/EPUB) · parse-quality gate · evidence extraction · claim prioritization · episode planning · script writer · TTS · cache/reuse · دانلود/پخش (WAV و MP3 هر دو موجودند)

**Useful but not essential**
document map (برای اسناد بلند لازم است، برای مقاله نه) · coverage audit · glossary · Research Brief (به‌عنوان یک فرم، نه یک stage مدل)

**Premature / Overengineered برای امروز**
claim reconciliation + disagreement graph · OCR self-hosted (۵ مدل در `models.lock.json`) · web/source discovery · script reviser · ASR + audio QA · multiple content modes · observability ledger دوگانه (SQLite + filesystem)

**Future feature**
M8 cross-source semantic reconciliation · authority ranking · approval روی هر مرحله

**مورد شاخص:** `claim_reconciliation` روی یک پروژه‌ی تک‌منبعی ۲۳٬۱۴۰ توکن ورودی و ۵٬۳۰۳ خروجی مصرف کرد و `episode/disagreement-graph.json` را با `nodes: [], edges: []` تولید کرد. یعنی ~۰٫۰۷ دلار در هر اجرا برای خروجی خالی، در حالت رایج MVP.

---

## ۴. End-to-End Reliability

| مسیر | وضعیت |
|---|---|
| PDF انگلیسی digital | parse با verdict `pass`/`warning`؛ تا script برده نشده |
| **PDF فارسی digital** | هر سه فایل `FA-*.pdf` با parser `native` و verdict **`warning`** — هیچ‌کدام وارد corpus نشدند. **مسیر فارسی هرگز به script نرسیده.** |
| **PDF فارسی اسکن‌شده** | هیچ اجرایی، هیچ benchmark result. مسیر OCR عملاً unvalidated است. |
| سند بلند (EPUB کتاب) | کار می‌کند: ۱۹۸ block، map سلسله‌مراتبی در ۱۱ partition |
| تولید script | یک بار موفق |
| تولید audio | یک بار، برای script قدیمی؛ فایل نهایی موجود نیست |

**نقاط شکست محتمل و کیفیت‌شان:**

- ✅ error handling کاربرپسند خوب است — `web/error_messages.py` خطاها را به rate_limit / auth / timeout / … دسته‌بندی و به فارسی ترجمه می‌کند.
- ✅ resume/retry منطقی است — `corpus_reuse`، `episode_reuse`، و `episode_duration_cost.py` که **از قبل** به کاربر می‌گوید تغییر مدت گران است یا ارزان. این طراحی خوبی است.
- ⚠️ **خروجی ناقص می‌تواند سالم به نظر برسد:** verifier در اجرای واقعی روی `gemini-3.6-flash` رفت — **همان مدلی که script را نوشت**. خروجی‌اش ۲۲ توکن بود (`pass`، بدون issue). `verification.json` می‌گوید `unsupported_claim_ratio: 0.0`. این تأیید مستقل نیست؛ یک مهر لاستیکی است.
- ⚠️ `config/model-routing.toml` فعلی `script_verifier = "gemini_fast"` است، نه `gemini_reviewer`. این ضمانت «writer داور خودش نیست» را در config عملاً خاموش کرده. **۸ تست به همین دلیل fail می‌شوند.**

---

## ۵. Quality

**Source fidelity:** خوب. excerpt matching، evidence validator و locator binding واقعاً کار می‌کنند. attribution درست است.

**Coverage:** ضعیف — نه به‌خاطر باگ، بلکه به‌خاطر انتخاب: ۶ از ۷۰ claim.

**Script:** فارسی طبیعی و قابل شنیدن؛ ولی repetition ساختاری و ساختار dialogue مصنوعی (B همیشه سؤال‌کننده‌ی مطیع). یک ریسک TTS هم هست: اصطلاحات لاتین inline (`زحمت (Labor)`، `حیات فعال (Vita Activa)`) — چون glossary `first_use_form` را این‌طور تعریف کرده. تلفظ اینها توسط TTS فارسی بررسی نشده.

**Audio:** در تنها اجرای ثبت‌شده، ۱۸ chunk `pass` و ۶ `manual_review`. اما هر شش مورد `similarity_ratio` بین ۰٫۹۹۲ تا ۰٫۹۹۸ دارند، با `pronunciation_review: []`، `truncated: false`، `repeated_phrases: []`. یعنی **۲۵٪ از chunkها بی‌دلیل کاربر را به بازبینی فنی می‌فرستند** — noise تقسیم جمله در ASR است، نه مشکل صوت. (نکته‌ی خوب: `audio_asr_enabled` پیش‌فرض `False` است، پس این مسیر پیش‌فرض روشن نیست.)

**معیار نهایی:** بله، خروجی از «PDF را به یک LLM عمومی بدهم» بهتر است — به‌شرط اینکه تکرار حل شود. با تکرار فعلی، کاربر بعد از اپیزود دوم متوجه می‌شود.

---

## ۶. Backend Efficiency

اندازه‌گیری‌شده روی تنها اجرای کامل (`f781a5c7`، ۱۰ دقیقه، یک EPUB):

| stage | calls | input tok | output tok | model-time |
|---|---:|---:|---:|---:|
| `document_map_part` | ۱۱ | ۵۹۷٬۸۶۴ | ۲۶٬۲۳۶ | ۳۲۰s |
| `evidence_extraction` | ۴۴ | ۱۲۴٬۹۶۰ | ۲۰٬۹۵۷ | ۱۶۶s |
| `script_verifier` | ۲ | ۲۶٬۳۸۱ | **۲۲** | ۸۵s |
| `episode_plan` | ۱ | ۲۳٬۴۵۷ | ۸۵۳ | ۲۸s |
| `claim_reconciliation` | ۲ | ۲۳٬۱۴۰ | ۵٬۳۰۳ | ۱۱۵s |
| `glossary` | ۱ | ۲۱٬۷۸۷ | ۵۹۹ | ۲۰s |
| `coverage_audit` | ۱ | ۱۷٬۹۲۷ | ۵۰۹ | ۱۵s |
| ۴ × `script_segment` | ۴ | ۲۶٬۶۸۳ | ۳٬۱۹۹ | ۱۳۳s |
| **جمع** | **۶۷** | **۸۶۲٬۴۵۵** | **۵۷٬۷۴۲** | **۸۸۲s** |

به‌علاوه در همان پروژه، **۲۷۳ call و ۲٫۹۸M توکن ورودی** در revisionهای archive‌شده (تلاش‌های قبلی) سوخته است.

**wasteهای واقعی و قابل‌رفع:**

1. **`document_map_part` = ۶۹٪ کل توکن ورودی.** کل کتاب map می‌شود تا در نهایت ۶ claim استفاده شود.
2. **۷۰ claim تولید، ۶ استفاده.** priorization بعد از هزینه انجام می‌شود، نه قبلش.
3. **`claim_reconciliation` روی تک‌منبع** — خروجی خالی، هزینه‌ی کامل. conditional نیست.
4. **TTS و ASR کاملاً sequential**‌اند (`audio_pipeline_service.py:119` و `:146`: `for chunk in chunks:`). ۲۴ chunk پشت‌سرهم. در مقابل، document map و evidence extraction با ۴ worker موازی‌اند. این عدم تقارن بی‌دلیل است و مستقیماً latency کاربر است.
5. **verifier همیشه اجرا می‌شود** و ۲۶k توکن مصرف می‌کند تا ۲۲ توکن برگرداند.

**چیزهایی که خوب‌اند و نباید دست بخورند:** cache/reuse بر پایه‌ی hash، `document_map_part_cache`، `parsed_document_cache`، پیش‌بینی هزینه‌ی تغییر مدت، و ASR خاموش به‌صورت پیش‌فرض.

---

## ۷. Cost per Episode

با نرخ‌های committed در `config/model-pricing.toml`:

**اندازه‌گیری‌شده (۱۰ دقیقه، یک EPUB کتاب، بدون ASR، مسیر موفق):**

```text
flash-lite  723,080 in + 47,257 out  →  $0.34
flash       139,375 in + 10,485 out  →  $0.29
LLM total                            →  $0.62
TTS (700s × 25 tok/s @ $20/M)        →  $0.35
──────────────────────────────────────────────
≈ $0.97 per episode
```

**هزینه‌ی واقعیِ رسیدن به آن اپیزود (با احتساب تلاش‌های archive‌شده): ≈ $2.5–3.**

**برون‌یابی — با برچسب صریح «تخمینی»** (هیچ اجرایی در ۵/۱۵/۳۰/۶۰ دقیقه وجود ندارد):

| مدت | LLM | TTS | جمع تقریبی |
|---|---|---|---|
| ۵ دقیقه | ~$0.45 | ~$0.15 | **~$0.60** |
| ۱۵ دقیقه | ~$0.80 | ~$0.45 | **~$1.25** |
| ۳۰ دقیقه | ~$1.2 | ~$0.90 | **~$2.1** |
| ۶۰ دقیقه | ~$2.5 | ~$1.80 | **~$4.3** |

هزینه‌ی ingestion تقریباً ثابت و تابع اندازه‌ی منبع است، نه مدت؛ TTS خطی است.

**داده‌ای که نداریم:** قیمت ASR (عمداً unpriced)، هزینه‌ی per-request برای Google Search و URL Context، هیچ اجرای multi-source، و هیچ اجرای غیر ۱۰ دقیقه. ضمناً ledger عملاً خالی از داده‌ی واقعی است: ۴۷۶ call که ۴۶۲تای آن `project_id = NULL` است و فقط ۱۳ رکورد `cost_micros` دارد. **یعنی cost telemetry برای اجراهای واقعی wire نشده.**

**قضاوت:** ~$1 برای یک اپیزود ۱۰ دقیقه‌ای برای MVP بدون درآمد قابل‌قبول است. آنچه قابل‌قبول نیست، ~$3 هزینه‌ی واقعی به‌ازای هر اپیزود موفق به‌خاطر rerunها، و پرداخت هزینه‌ی map کل کتاب برای استفاده از ۹٪ آن است.

---

## ۸. Overengineering Audit

اگر این‌ها امروز نبودند، کاربر افت ارزش حس می‌کرد؟ **نه:**

- **claim reconciliation + disagreement graph** — تک‌منبعی، خروجی خالی، هزینه‌ی کامل
- **OCR self-hosted با ۵ مدل قفل‌شده** (`models.lock.json`، PaddleOCR + Bina + VLM fallback) — هیچ اجرا، هیچ نتیجه‌ی benchmark
- **web/source discovery** — stage `web_source_capture` صفر بار اجرا شده
- **script reviser** — صفر بار اجرا شده
- **ASR + expected-vs-heard QA + targeted regeneration** — پیش‌فرض خاموش، و در تنها اجرای روشن، ۶ false positive تولید کرد
- **دو observability store موازی** (SQLite ledger + filesystem model-runs) — ledger عملاً بلااستفاده است
- **۲۰ ProjectState، ۸۴ متغیر محیطی، ۱۳ prompt stage با نسخه‌بندی** — برای محصولی با صفر کاربر
- **Research Brief به‌عنوان یک stage مدل با gate اجباری** — هر سه پروژه‌ی ثبت‌شده brief عملاً یکسانی گرفتند (`learning_objectives: ["فهم روشن موضوع و ایده‌های اصلی آن"]`، `subquestions: []`، `ambiguities: []`). کاربر مجبور است چیزی boilerplate را تأیید کند.

**آنچه نباید حذف شود:** excerpt matching، evidence/locator binding، artifact hash binding، rewind/archive، parse-quality gate. اینها پایه‌ی تفاوت با NotebookLM‌اند.

---

## ۹. Underbuilding Audit

**Missing MVP requirement:**

1. **مسیر منبع فارسی هرگز end-to-end کار نکرده.** هر سه PDF فارسی verdict `warning` گرفتند و رها شدند. برای یک محصول فارسی‌زبان این blocker است.
2. **verifier مستقل نیست.** config فعلی آن را به مدل ارزان می‌فرستد؛ در اجرای واقعی همان مدل نویسنده بود. ضمانت اصلی ضدهذیان امروز فعال نیست.
3. **`final.wav` فعلی وجود ندارد.** script تأییدشده هرگز به صوت تبدیل نشده. کاربر امروز نمی‌تواند خروجی نهایی را بگیرد.
4. **۱۷ تست fail** از ۸۹۲ (`874 passed, 17 failed, 1 skipped`) — ۸تا مربوط به همین regression مسیر verifier، بقیه: `test_gates.py` (ارجاع gate به یک خط خالی)، `test_script_pipeline.py` (cache-hit)، `test_observability_phase56.py`.
5. **cost telemetry برای اجراهای واقعی wire نشده** — بدون آن، runaway cost قابل‌تشخیص نیست.

**Nice to have:** blind comparison با NotebookLM · human scoring · Persian OCR benchmark · UI v2 · latency dashboard.

---

## ۱۰. Release Scope

**Keep for MVP**
upload (PDF/EPUB/TXT) → parse-quality gate → blocks → document map → evidence extraction → prioritization → coverage audit → episode plan → script writer → deterministic checks → verifier (با مدل مستقل) → TTS → assemble → دانلود WAV/MP3. به‌علاوه: cache/reuse، rewind/archive، error messages فارسی، `doctor`.

**Simplify / Change before MVP**

- ضریب ۴٫۰ expansion → حذف یا کاهش شدید؛ به‌جایش claimهای بیشتر وارد اپیزود کنید
- verifier → مدل واقعاً مستقل، و conditional (فقط وقتی deterministic checks issue دارند)
- claim reconciliation → skip وقتی `len(sources) == 1`
- Research Brief → فرم ساده‌ی بدون gate اجباری
- TTS → موازی
- gateها: از ۶ به ۳ (corpus / plan / شروع صوت)

**Defer until real users**
web/source discovery · OCR self-hosted · ASR + audio QA + regeneration · script reviser · multiple content modes · SQLite ledger · M8/M9/M10

---

## ۱۱. Final Verdict

### MVP Verdict

```text
NOT READY — CORE GAPS  (و هم‌زمان OVERBUILT FOR CURRENT STAGE)
```

معماری، provenance و resumability از سطح یک MVP جلوترند. اما سه چیز پایه‌ای کار نمی‌کنند: مسیر منبع فارسی هرگز به script نرسیده، verifier مستقل نیست، و خروجی صوتی فعلی وجود ندارد. هم‌زمان، حجم زیادی از پیچیدگی برای مسیرهایی ساخته شده که صفر بار اجرا شده‌اند.

### What already works

1. Source fidelity و ردیابی claim → evidence → locator (واقعی و قابل‌بررسی)
2. ingestion اسناد بلند بدون truncation (EPUB کتاب، ۱۹۸ block، ۱۱ partition)
3. cache/reuse و پیش‌بینی هزینه‌ی تغییر مدت
4. rewind/archive بدون از دست رفتن ورودی خام
5. پیام‌های خطای فارسی دسته‌بندی‌شده + `doctor` preflight

### What blocks a good MVP

1. مسیر PDF فارسی هرگز end-to-end اجرا نشده (هر سه فایل `warning`)
2. verifier در config و در اجرای واقعی مستقل نیست — ۸ تست fail
3. `final.wav` برای script تأییدشده وجود ندارد
4. ضریب padding ۴٫۰ که تکرار ساختاری تولید می‌کند
5. ۱۷ تست failing روی main

### What is overengineered

1. claim reconciliation + disagreement graph روی تک‌منبع
2. OCR self-hosted با ۵ مدل قفل‌شده، صفر اجرا
3. web/source discovery، صفر اجرا
4. ASR + audio QA + regeneration (پیش‌فرض خاموش، ۶ false positive وقتی روشن)
5. دو observability store موازی + ۲۰ state + ۸۴ env var

### What is missing

1. یک اجرای واقعی فارسی end-to-end
2. cost telemetry برای اجراهای واقعی
3. verifier مستقل فعال
4. اجرای هیچ مدتی به‌جز ۱۰ دقیقه
5. blind comparison با NotebookLM (که همان چیزی است که ادعای تمایز را اثبات می‌کند)

### Cost / Performance Verdict

~$۱ برای هر اپیزود ۱۰ دقیقه‌ای اقتصادی است. اما هزینه‌ی *واقعی* رسیدن به هر اپیزود موفق ~$۳ بود. مهم‌ترین wasteها به ترتیب: (۱) map کل کتاب برای استفاده از ۹٪ آن — ۶۹٪ توکن ورودی؛ (۲) استخراج ۷۰ claim و استفاده از ۶؛ (۳) reconciliation تک‌منبعی با خروجی خالی؛ (۴) verifier همیشه‌روشن که ۲۲ توکن برمی‌گرداند؛ (۵) TTS/ASR sequential که هزینه نیست ولی latency است.

### Next Actions

**۱. `config/model-routing.toml` را به `gemini_reviewer` برگردانید و `config/model-routing copy.toml` را حذف کنید**
Why: ضمانت اصلی ضدهذیان محصول امروز خاموش است · Impact: ۸ تست سبز، verification واقعاً مستقل · **Effort: S**

**۲. یک اجرای کامل با PDF فارسی digital تا `final.wav`**
Why: هیچ اجرای فارسی end-to-end وجود ندارد؛ این تنها آزمون واقعی محصول است · Impact: مشخص می‌شود آیا MVP وجود دارد یا نه · **Effort: M**

**۳. ضریب ۴٫۰ expansion را حذف و به‌جایش claim بیشتری وارد اپیزود کنید**
Why: منشأ مستقیم تکرار ساختاری؛ ۶۴ claim استفاده‌نشده روی میز است · Impact: بزرگ‌ترین جهش کیفیت شنیداری · **Effort: S**

**۴. `claim_reconciliation` و `script_verifier` را conditional کنید**
Why: reconciliation تک‌منبعی خروجی خالی می‌دهد؛ verifier همیشه اجرا می‌شود · Impact: ~۲۵٪ کاهش هزینه و latency در حالت رایج · **Effort: S**

**۵. TTS را موازی کنید**
Why: ۲۴ chunk sequential، در حالی که map/evidence از قبل ۴ worker دارند · Impact: latency صوت ~۳–۴ برابر کمتر · **Effort: S**

**۶. `cost_micros` را برای اجراهای واقعی wire کنید**
Why: ledger عملاً خالی است (۱۳ رکورد priced)؛ بدون آن runaway cost نامرئی است · Impact: قابلیت تصمیم‌گیری با عدد واقعی · **Effort: M**

**۷. مسیرهای صفر-اجرا را پشت feature flag ببرید: web discovery، OCR self-hosted، ASR/QA، reviser**
Why: هیچ evidence نیازی ندارند و maintenance تولید می‌کنند · Impact: کاهش سطح شکست و پیچیدگی نصب · **Effort: M**

---

## ۱۲. NotebookLM — درد کاربر و تطابق با ما

شکایت‌های تکرارشونده‌ی کاربران درباره‌ی تولید صوت از منبع تخصصی:

| درد کاربر NotebookLM | آیا Thesisound برایش ارزش می‌سازد؟ |
|---|---|
| **hostها چیزهایی می‌گویند که در منبع نیست** — به‌ویژه در موضوعات تاریخی، از دانش پس‌زمینه می‌کشند | ✅ **بله، و این تفاوت اصلی است.** هر turn محتوایی به `evidence_id` واقعی bind است، excerpt باید عیناً در block منبع موجود باشد. |
| **قابل استناد نیست** — «به‌عنوان summary گوش کن، نه citation» | ✅ **بله.** source trace در UI موجود است. |
| **کنترل طول ندارد** — ۶ تا ۱۵ دقیقه قفل؛ درخواست ۳ دقیقه، خروجی ۱۴ دقیقه | ⚠️ **نیمه.** مدت ۵ تا ۱۲۰ دقیقه انتخابی است و `duration_cost_hint` هزینه‌ی تغییر را از قبل می‌گوید — این بهتر است. اما ضریب padding ۴٫۰ یعنی تفاوت مدت‌ها معنایی نیست؛ فقط همان محتوا بیشتر کش می‌آید. **همان درد، با مکانیزم متفاوت.** |
| **repetitive و سطحی** | ❌ **نه — امروز ما همین مشکل را داریم**، و از NotebookLM قابل‌اندازه‌گیری‌تر: ۶ ایده در ۲۲ turn. |
| **سند بلند truncate می‌شود؛ نیمه‌ی دوم کتاب نادیده گرفته می‌شود** | ✅ **بله.** hierarchical map روی مرز semantic بدون truncation — این معماری مستقیماً همان درد را هدف گرفته. |
| **لحن casual و بیش‌ازحد پرشور برای کار آکادمیک** | ✅ **بله.** لحن خروجی فارسی جدی و آموزشی است. |
| **همیشه دو صدای یکسان** | ⚠️ خنثی |
| **فارسی در beta** — پشتیبانی هست ولی کیفیتش تضمین‌شده نیست | ⚠️ **فرصت بزرگ، اما اثبات‌نشده.** هیچ اجرای فارسی end-to-end ثبت نشده. |

**جمع‌بندی:** Thesisound دقیقاً روی سه درد اصلی و بی‌پاسخ NotebookLM نشسته است — **hallucination**، **عدم ردیابی**، و **truncation اسناد بلند** — به‌علاوه‌ی یک جای خالی بازار (فارسی جدی). این positioning درست است و توجیه‌کننده‌ی پیچیدگیِ provenance است.

اما دو درد دیگر — **repetition/سطحی بودن** و **بی‌معنا بودن تفاوت مدت‌ها** — را ما هنوز حل نکرده‌ایم و در واقع با ضریب ۴٫۰ خودمان بازتولید کرده‌ایم. Action شماره ۳ همان تک‌تغییری است که این را برمی‌گرداند.

### منابع پژوهش وب

- [aitooldiscovery — NotebookLM Reddit Review](https://www.aitooldiscovery.com/guides/notebooklm-reddit)
- [XDA — Audio Overviews sound so human, you'll believe the misinformation](https://www.xda-developers.com/notebooklm-audio-overviews-sound-human-believe-misinformation/)
- [superlore.ai — Audio Overview Limits 2026](https://superlore.ai/blog/notebooklm-audio-overview-limits-2026)
- [lawsen.substack — NotebookLM podcasts, but good](https://lawsen.substack.com/p/notebooklm-podcasts-but-good)
- [Google Workspace Updates — 50+ languages](https://workspaceupdates.googleblog.com/2025/04/language-expansion-audio-overviews-notebooklm.html)
