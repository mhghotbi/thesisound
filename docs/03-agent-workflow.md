# 03 — مرحله‌بندی ایجنت‌ها و قرارداد اجرا

## اصل اول: بیشتر مراحل «ایجنت» نیستند

در این پروژه واژه agent فقط برای یک مدل دارای هدف محدود، ورودی محدود و خروجی schema-bound استفاده می‌شود. هیچ agent اجازه ندارد آزادانه کل pipeline را تغییر دهد، منبع را بدون ثبت اضافه کند یا از خودش ابزار جدید انتخاب کند.

هر stage باید یکی از این سه نوع باشد:

| نوع | مسئولیت | مثال |
|---|---|---|
| Deterministic | کار قابل‌تعریف با کد | hash، dedup، state transition، schema validation |
| Bounded model transform | تفسیر یا تولید محدود | research brief، document map، episode plan |
| Human gate | تصمیمی که بر روایت اثر می‌گذارد | انتخاب منبع، پذیرش scope، تأیید نمونه صوت |

## قواعد مشترک تمام model stageها

هر فراخوانی مدل باید این موارد را داشته باشد:

1. `stage_name`
2. `prompt_version`
3. `model_id`
4. `input_artifact_hashes`
5. JSON Schema یا Pydantic model
6. token/time budget
7. retry policy
8. failure classification
9. raw response retention policy
10. evaluation result

### مدل اجازه ندارد

- URL، DOI، نقل‌قول یا metadata را جعل کند؛
- source جدید را silently وارد corpus کند؛
- output schema را با prose اضافی بشکند؛
- uncertainty را حذف کند؛
- metadata-only source را full-text evidence فرض کند؛
- stage بعدی را خودش اجرا کند.

---

# Workflow دقیق

## Stage A — Project initializer

**نوع:** deterministic

### ورودی

- raw user input؛
- settings اختیاری؛
- فایل‌ها و URLهای اولیه.

### کار

- project ID؛
- workspace؛
- file hash؛
- raw input manifest؛
- state=`DRAFT`.

### failure

- فایل unreadable؛
- فرمت unsupported؛
- workspace permission error.

مدل در این مرحله استفاده نمی‌شود.

---

## Stage B — Research brief builder

**نوع:** bounded model transform

### هدف

تبدیل ورودی مبهم به مسئله‌ای که بتوان برای آن منبع پیدا کرد و episode طراحی کرد.

### ورودی مجاز

- raw input؛
- تنظیمات audience/depth/duration/mode؛
- metadata فایل‌های کاربر، نه کل متن فایل.

### خروجی

`ResearchBrief`

### ممنوعیت

- پاسخ‌دادن به موضوع؛
- پیشنهاد منبع با عنوان ساختگی؛
- فرض اینکه یک نام حتماً به یک شخص خاص اشاره دارد اگر ambiguity واقعی وجود دارد.

### gate

- central question مشخص؛
- scope متناسب با مدت؛
- objectiveها قابل سنجش؛
- ambiguity بحرانی ثبت شده.

### retry

حداکثر ۲ بار:

1. retry با validation error؛
2. retry با instruction دقیق‌تر برای فیلد ناقص.

اگر هنوز شکست خورد، human correction.

---

## Stage C — Query planner

**نوع:** bounded model transform

### هدف

ساخت query family، نه پیدا کردن مستقیم source.

### ورودی

- ResearchBrief؛
- metadata منابع کاربر؛
- coverage targetها؛
- search round number.

### خروجی

لیست `SearchQuery` با purpose و source role.

### query familyهای لازم

بسته به موضوع:

- primary work/person exact queries؛
- canonical overview؛
- scholarly interpretation؛
- criticism/counter-position؛
- recent scholarship؛
- Persian sources؛
- edition/translation metadata.

### محدودیت

- دور اول حداکثر ۱۲ query؛
- دور دوم حداکثر ۸ query؛
- gap round حداکثر ۵ query؛
- هر query باید reason و provider داشته باشد.

### ممنوعیت

- search result ساختگی؛
- generic queryهای تکراری؛
- استفاده از recency برای موضوعی که recency ارزش ندارد؛
- query برای جمع‌آوری غیرمحدود منابع.

---

## Stage D — Search executors

**نوع:** deterministic adapters

### کار

- اجرای query روی provider تعیین‌شده؛
- ثبت request/response metadata؛
- normalize کردن نتیجه؛
- احترام به rate limit؛
- backoff و retry.

### MVP provider routing

| نیاز | provider |
|---|---|
| scholarly metadata/full-text links | OpenAlex |
| web/reference/institutional pages | Firecrawl Search |
| DOI validation | Crossref |
| books and editions | Google Books/Open Library |
| citation recommendation | بعداً Semantic Scholar |

### retry

- 429: backoff براساس header؛
- 5xx: حداکثر ۳ retry؛
- 4xx syntax/auth: بدون retry خودکار؛
- empty result: query planner replan، نه تکرار همان request.

---

## Stage E — Source normalizer and deduplicator

**نوع:** deterministic

### کار

- canonical DOI؛
- normalized title؛
- author/year؛
- canonical URL؛
- duplicate detection؛
- access level؛
- origin tracking.

### dedup keys

به‌ترتیب:

1. DOI؛
2. OpenAlex/S2 ID؛
3. ISBN + edition؛
4. canonical URL؛
5. normalized title + first author + year.

مدل در dedup اصلی تصمیم نهایی نمی‌گیرد. فقط duplicateهای مبهم را flag می‌کند.

---

## Stage F — Source triage

**نوع:** hybrid

### deterministic facts

- source type؛
- venue/publisher؛
- publication year؛
- full-text availability؛
- DOI/ISBN؛
- domain class؛
- duplicate state.

### model transform

- relevance reason؛
- perspective؛
- likely source role؛
- limitation؛
- reason for inclusion/rejection.

### خروجی

`SourceCandidate`

### gate

مدل نباید `access=FULL_TEXT` تعیین کند. access فقط از connector/parse state می‌آید.

### source classes

- primary text؛
- peer-reviewed or university press؛
- academic reference؛
- reputable institution؛
- general web؛
- unknown.

این classها ranking hint هستند، نه verdict نهایی درباره حقیقت.

---

## Stage G — Human source selection

**نوع:** human gate

### کاربر برای هر source انتخاب می‌کند

- Include؛
- Exclude؛
- Background only؛
- Recommended reading only.

### سیستم باید نمایش دهد

- دلیل پیشنهاد؛
- role؛
- access؛
- limitation؛
- duplicate؛
- full text موجود یا نه.

### قانون

بدون انتخاب کاربر، source discovered وارد evidence corpus نمی‌شود.

---

## Stage H — Parser inspector/router

**نوع:** deterministic

### inspect

- file type؛
- encryption؛
- page count؛
- text density sample؛
- image-only pages؛
- likely multi-column؛
- size؛
- language.

### route

- Docling default؛
- MinerU برای scan/complex layout؛
- Firecrawl Parse فقط fallback opt-in.

### ممنوعیت

LLM نباید براساس filename parser انتخاب کند.

---

## Stage I — Parse quality auditor

**نوع:** deterministic-first، model-assisted only on suspicion

### heuristic checks

- empty pages؛
- text density outliers؛
- replacement chars؛
- header/footer repetition؛
- heading loss؛
- page order anomaly؛
- locator coverage.

### model input

فقط sampleهای مشکوک + render page، نه کل سند.

### output

- pass؛
- pass_with_warning؛
- retry_with_other_parser؛
- manual_review.

### retry

حداکثر یک parser fallback خودکار. بعد از آن manual review؛ نه چرخه بی‌نهایت parserها.

---

## Stage J — Document mapper

**نوع:** bounded model transform

### هدف

ساخت نقشه ساختاری و نقش بخش‌ها، بدون فشرده‌کردن محتوای کل سند به یک summary.

### ورودی

- heading tree؛
- block metadata؛
- متن بخش در window کنترل‌شده.

### خروجی

- section function؛
- dependencies؛
- key concepts؛
- cross-section threads؛
- required-for-understanding flag.

### ممنوعیت

- داوری صحت نویسنده؛
- merge کردن بخش‌های متعارض؛
- حذف section به دلیل «کم‌اهمیت» بودن بدون ثبت.

---

## Stage K — Evidence extractor

**نوع:** bounded model transform، قابل parallelization

### واحد اجرا

یک argument unit یا section کوچک، نه chunk تصادفی.

### خروجی

- claims؛
- definitions؛
- distinctions؛
- examples؛
- objections؛
- qualifications؛
- exact supporting excerpt؛
- locator.

### gate

- excerpt باید substring یا normalized match متن ورودی باشد؛
- locator باید متعلق به همان block باشد؛
- confidence پایین حذف نمی‌شود، flag می‌شود؛
- inference از direct support جداست.

### deterministic validation

پس از مدل:

- excerpt match؛
- block ID exists؛
- locator bounds؛
- duplicate claim detection.

---

## Stage L — Claim reconciler

**نوع:** bounded model transform + deterministic clustering

### هدف

claimهای مشابه را به canonical claim وصل کند، بدون نابودکردن disagreement.

### ابتدا deterministic

- lexical normalization؛
- exact/near duplicate؛
- source and locator linking.

### سپس مدل

فقط برای خوشه‌های مبهم:

- equivalent؛
- narrower/broader؛
- supports؛
- contradicts؛
- unrelated.

### خروجی

`ClaimRecord`

### ممنوعیت

دو تفسیر مخالف نباید صرفاً چون درباره یک مفهوم‌اند merge شوند.

---

## Stage M — Coverage auditor

**نوع:** bounded model transform

### هدف

سنجش اینکه corpus انتخاب‌شده برای brief کافی است، نه اینکه تعداد source زیاد شود.

### خروجی

برای هر subquestion:

- well covered؛
- partial؛
- missing؛
- evidence/claim IDs؛
- missing role؛
- risk if ignored.

### stop conditions

جست‌وجو متوقف می‌شود اگر:

- central question و objectiveهای اصلی پوشش دارند؛
- gap باقی‌مانده با scope فعلی قابل قبول است؛
- دو search round منبع جدید مؤثر نداده‌اند؛
- user ادامه با corpus فعلی را تأیید کرده است.

### ممنوعیت

هر gap کوچک نباید trigger سرچ جدید باشد.

---

## Stage N — Episode architect

**نوع:** bounded model transform

### هدف

تبدیل claim ledger به مسیر فهم شنیداری.

### خروجی

- listener outcome؛
- segmentها؛
- claim IDs هر segment؛
- key question؛
- speaker dynamic؛
- time budget؛
- deliberately omitted claims.

### gate

- مجموع زمان در محدوده؛
- هر segment purpose مستقل؛
- prerequisite قبل از dependent concept؛
- claim خارج از ledger وجود ندارد؛
- حذف مهم ثبت شده است.

---

## Stage O — Evidence pack builder

**نوع:** deterministic

### کار

برای هر segment:

- claim IDs؛
- evidence items؛
- original block؛
- neighbor block در صورت dependency؛
- glossary candidates؛
- source attribution.

### retrieval MVP

- claim mapping؛
- heading/locator؛
- SQLite FTS5؛
- neighbor expansion.

مدل نمی‌تواند خودش corpus کامل را browse کند؛ evidence pack bounded دریافت می‌کند.

---

## Stage P — Glossary builder

**نوع:** bounded model transform + human override

### خروجی هر term

- source term؛
- preferred Persian؛
- first-use form؛
- later-use form؛
- pronunciation hint؛
- contested status؛
- terms not to collapse.

### gate

- اصطلاح‌های contrastive جدا بمانند؛
- ترجمه جاافتاده با citation/notes ثبت شود؛
- نام اشخاص و آثار consistency داشته باشد.

کاربر باید بتواند glossary را override کند.

---

## Stage Q — Persian script writer

**نوع:** bounded model transform

### ورودی

فقط:

- یک segment plan؛
- evidence pack همان segment؛
- glossary؛
- tail کوتاه segment قبل؛
- style contract.

### خروجی

turnهای فارسی با claim IDs.

### ممنوعیت

- استفاده از knowledge خارج evidence pack؛
- مثال ساختگی بدون `editorial_only`؛
- fake quote؛
- filler؛
- تکرار حرف گوینده قبلی؛
- شوخی رادیویی؛
- ترجمه‌زدگی؛
- نسبت‌دادن یک interpretation به خود نویسنده.

### retry

- schema failure: یک retry؛
- evidence failure: revise فقط turnهای مشخص؛
- style failure: یک style rewrite بدون تغییر claim IDs؛
- بیش از ۳ attempt: human review.

---

## Stage R — Script verifier

**نوع:** adversarial model transform + deterministic checks

### استقلال

- prompt متفاوت؛
- بهتر است model call/context مستقل باشد؛
- verifier replacement prose کامل تولید نمی‌کند مگر برای turn معیوب؛
- verifier حق اضافه‌کردن claim جدید ندارد.

### بررسی‌ها

- unsupported claim؛
- wrong attribution؛
- certainty shift؛
- lost qualification؛
- collapsed disagreement؛
- invented example؛
- terminology error؛
- claim ID mismatch.

### pass condition

- unsupported claim ratio = 0؛
- blocking issue = 0؛
- high issue = 0؛
- medium issue یا revise شده یا accepted with note.

---

## Stage S — TTS segment planner

**نوع:** deterministic-first

### کار

- split در مرز turn و مفهوم؛
- حفظ سؤال و جواب مرتبط؛
- هدف چند دقیقه صوت؛
- prompt/header ثابت؛
- pronunciation notes.

LLM فقط اگر segmentation با punctuation و turn boundary ممکن نبود استفاده می‌شود.

---

## Stage T — TTS renderer

**نوع:** deterministic adapter

### ورودی

- transcript ثابت؛
- speaker voice config؛
- director notes؛
- idempotency hash.

### retry

- transient 5xx: exponential backoff؛
- text token instead of audio: retry؛
- prohibited false positive: prompt template hardening و یک retry؛
- drift/voice mismatch: QA-triggered regenerate.

### ممنوعیت

renderer حق تغییر transcript ندارد.

---

## Stage U — Audio QA

**نوع:** deterministic + bounded model transform

### deterministic

- audio decodable؛
- duration non-zero؛
- no clipping؛
- ASR transcript؛
- missing/repeated substring؛
- final truncation؛
- speaker label leakage؛
- instruction leakage.

### model-assisted

فقط semantic mismatchهایی که diff ساده حل نمی‌کند.

### output

- pass؛
- regenerate segment؛
- manual pronunciation review.

---

# بودجه و توقف

هر project budget دارد:

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

Budget فقط برای هزینه نیست؛ از endless agent loop و افزایش خطا جلوگیری می‌کند.

# مشاهده‌پذیری

برای هر stage ثبت شود:

- input hash؛
- output hash؛
- prompt version؛
- model/provider؛
- latency؛
- usage؛
- retry reason؛
- gate result؛
- warnings.

بدون این داده‌ها بهبود promptها بر اساس حدس خواهد بود.
