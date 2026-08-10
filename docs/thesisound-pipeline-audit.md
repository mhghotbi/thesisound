# ممیزی جامع پایپلاین Thesisound — کارایی و کیفیت

تاریخ: ۲۰۲۶-۰۸-۱۰ · commit: `4a9159b` (working tree تمیز) · هیچ کدی تغییر نکرد

---

## 1. Executive Verdict

**وضعیت کلی.** معماری Thesisound از نظر طراحی جدی و غیرمعمولاً منضبط است: contractهای نسخه‌دار، artifact store قابل‌ممیزی، gate registry با ارجاع به خط کد، cache محتوا-محور و مستقل از منبع، و امتناع صریح از حدس‌زدن قیمت. اما **پایپلاین هنوز با داده‌ی واقعی اثبات نشده است**: در کل مخزن فقط **یک** اجرای واقعی end-to-end وجود دارد (پروژه `f781a5c7`، کتاب *The Human Condition*، EPUB، ۱۰ دقیقه، explanatory) و همان یک اجرا **سه نقص P0 را آشکار می‌کند که هیچ‌کدام توسط تست‌ها گرفته نشده‌اند**.

**مهم‌ترین قوت‌ها.**
- زنجیره‌ی repair شاهد (تطبیق متساهل → بازنویسی verbatim → بازبررسی سخت‌گیرانه) طراحی درستی است.
- `DocumentMapCache` محتوا-محور و بدون رد منبع — طراحی واقعاً خوب.
- script و audio pipeline هر دو resumable هستند و رویداد `cache.lookup` می‌دهند.
- circuit breaker در evidence extraction جلوی هزینه‌ی خطای سراسری provider را می‌گیرد.
- کیفیت فارسی خروجی واقعی **خوب** است: اصطلاحات منسجم، لحن مناسب دانشجوی علوم انسانی، وفادار به آرنت.

**مهم‌ترین ضعف‌ها.**
- `document_map_merge` برای هر سند چندپارتیشنی **یک no-op خاموش** است (اثبات‌شده در کد و در artifact واقعی).
- Audio QA برای هر chunk با اختلاف املایی، **به‌طور ریاضی مجبور** به false positive است؛ ۶ از ۲۴ chunk (۲۵٪) بدون هیچ نقص واقعی به بازبینی دستی رفتند.
- شکست یک partition، کل document map را از نو می‌خرد: **۲۱۵٬۹۱۲ توکن ورودی دوباره پرداخت شد** درحالی‌که `input_hash` یکسان از قبل محاسبه شده بود.

**آیا pipeline overengineered است؟** نه از نظر تعداد مرحله. مسئله این است که **چند مرحله‌ی گران، ارزش ادعایی‌شان را تحویل نمی‌دهند** (merge = صفر، audio QA = صفر اقدام اصلاحی، verifier = خودارزیابی). پیچیدگی در جای درست است اما در سه نقطه بی‌اثر شده.

**آیا کیفیت فعلی پیچیدگی را توجیه می‌کند؟** `Insufficient evidence` — با یک اجرا و بدون human quality score نمی‌توان قضاوت کرد. اما متن فارسی تولیدشده کیفیت قابل‌دفاعی دارد.

- **بزرگ‌ترین bottleneck اثبات‌شده:** `document_map_part` — ۶۰.۳٪ کل توکن ورودی و ۲۸.۳٪ کل زمان provider، و در HEAD هنوز سریالی.
- **بزرگ‌ترین quality risk:** merge خاموش → هیچ وابستگی بین‌پارتیشنی (۰ مورد اندازه‌گیری‌شده) و working thesis سراسری که در واقع thesis پارتیشن ۱ است.
- **بزرگ‌ترین token/cost waste:** rework دورریخته: از ۳٬۸۴۵٬۰۵۷ توکن ورودی خرج‌شده روی این پروژه، **۷۷.۶٪ در revisionهای archive شده دور ریخته شد**.
- **مهم‌ترین چیزی که هنوز قابل‌اندازه‌گیری نیست:** هزینه‌ی هر call (جدول قیمت خالی است) و هزینه‌ی توکنی retryها (attemptهای ناموفق usage ثبت نمی‌کنند).

**سه اقدام اولویت‌دار بعدی:** R1 (اصلاح merge)، R2 (اصلاح تشخیص جمله‌ی افتاده در Audio QA)، R3 (checkpoint پارتیشنی document map).

---

## 2. Scope and Evidence

**بررسی‌شده.**

| منبع | حجم |
|---|---|
| کد | ۱۴۷ فایل پایتون در `src/thesisound/` |
| prompts | ۶۶ فایل؛ ۱۵ prompt نسخه‌دار اجرایی + ۱۵ سند طراحی `NN_*.md` |
| config | `model-routing.toml`، `model-pricing.toml`، `models.lock.json` |
| تست | ۹۴ فایل تست، `.github/workflows/` |
| ledger | `workspaces/_observability/ledger.sqlite3` (۱۰ MB، schema v3) |
| model-run store | ۳۶۵ فایل `record.json` در `workspaces/*/model-runs/` |
| artifactهای اجرا | document map، blocks، claim ledger، coverage/budget report، episode plan، script، audio QA/ASR/manifest |

**پروژه‌های واقعی.**

| project | state | ماهیت |
|---|---|---|
| `f781a5c7` | `script_verified` | **تنها اجرای واقعی end-to-end.** آرنت، EPUB، ۱۰ دقیقه، fa، explanatory |
| `1296f949` | `failed_retryable` | متوقف در evidence extraction |
| `5136911e` | `source_selection_required` | ناتمام |
| `6c10d0b1` | `sources_collecting` | فقط `project.json` |

**محدودیت‌های تعیین‌کننده.**

1. **n = 1.** هر عدد کیفی از یک اجرا می‌آید. طبق قاعده‌ی ۸ شما، این نماینده‌ی pipeline نیست.
2. **ledger عملاً خالی از داده‌ی واقعی است.** از ۳۵۸ ردیف `model_calls`، ۲۳۲ ردیف `stage='test'` و ۱۱۲ ردیف `requested_model='gemini-test'` هستند. **فقط ۱۴ فراخوانی provider واقعی** در ledger وجود دارد. تحلیل واقعی روی store فایل‌سیستمی (۳۶۵ رکورد) انجام شد.
3. **۶٬۷۷۴ span و ۸٬۵۳۷ event همگی از test suite‌اند** (هر ۴۰ pid، بازه‌ی ۰۸-۰۹/۰۸-۱۰، مدت‌های ۳–۲۰۶ms، project_id هایی که در `workspaces/` وجود ندارند). برای latency تولیدی قابل استفاده نیستند.
4. **اجرای مشاهده‌شده مقدم بر قابلیت concurrency است.** `evidence_extraction_workers` در commit `4ff91d3` (۲۰۲۶-۰۸-۰۹ ۱۳:۲۵ UTC) اضافه شد؛ اجرا ۰۹:۲۸–۱۲:۳۱ UTC بود. پس سریالی‌بودن اندازه‌گیری‌شده وضعیت **آن زمان** است، نه لزوماً HEAD.

**بررسی‌نشده.** اجرای زنده با provider (بدون مجوز هزینه)؛ PDF فارسی اسکن‌شده و OCR (هیچ artifact واقعی ندارد)؛ web/URL capture (هیچ اجرای واقعی)؛ چندمنبعی و منابع متعارض (هیچ اجرا)؛ durationهای ۵/۱۵/۳۰/۶۰؛ mode critical/debate؛ blind listening.

---

## 3. Reconstructed Pipeline

```text
OTP login
  → [G1 human] Research Brief confirm
  → upload  |  Gemini Search → capture (URL Context)
  → parse routing (native / docling / mineru / epub / local OCR)
  → [G2 machine] parse-quality
  → [G3 human] corpus confirm
  → block building (deterministic)
  → document map:  partition → N× document_map_part → document_map_merge
  → evidence extraction (per block)
  → [G4/G5 machine] excerpt validation, evidence retention ≥85%
  → claim prioritization → claim reconciliation → disagreement graph
  → [G6 machine] coverage audit + supported duration
  → [G7 human] Episode Plan approval
  → glossary → persian_script_segment (per segment)
  → [G8 machine] deterministic checks
  → [G9 machine] script verifier  → (conditional) script reviser
  → [G10 human] script review decision
  → TTS segmentation → TTS → WAV validate → ASR → [G11 machine] audio QA
  → (conditional) regeneration → ffmpeg loudnorm + assemble
  → [G12 human] final listen → COMPLETE
```

### جدول مراحل

| Stage | Input | Output | D/M | Tier | Blocking dep | Cache/reuse | Retry | User-visible |
|---|---|---|---|---|---|---|---|---|
| Research Brief | topic | `ResearchBrief` | M | fast + search | — | — | 2 | ✅ G1 |
| Source Discovery | brief | candidates | M | fast + search | brief | `web_search` cache | 2 | ✅ |
| Source Capture | URL | `.web.md` | M | fast + url_ctx | selection | — | 2 | ✅ |
| Ingestion/Parse | file | `ParsedDocument` | D | — | — | `shared_parsed_document` | — | ✅ G2 |
| Block Building | parsed | `document-blocks.jsonl` | D | — | parse | project artifact | — | ➖ |
| **document_map_part** | N partitions | part drafts | M | fast | blocks | ❌ **بدون checkpoint** | 3 | ➖ |
| **document_map_merge** | part drafts | global updates | M | fast | همه‌ی parts | — | 2 | ➖ |
| Extraction planning | map+brief | `EvidenceExtractionPlan` | D | — | map | — | — | ➖ |
| **evidence_extraction** | block | claims | M | fast | plan | `claim_ledger` | 3 | ➖ G4/G5 |
| Claim prioritization | ledger | priorities | D | — | ledger | — | — | ➖ |
| claim_reconciliation | claims | reconciled | M | strong | ledger | — | 2 | ➖ |
| Disagreement graph | claims | graph | D | — | reconcile | — | — | ➖ |
| coverage_audit | ledger+brief | coverage report | M | strong | claims | `coverage_audit` | 2 | ✅ G6 |
| episode_plan | claims+coverage | plan | M | strong | audit | `episode_plan` | 2 | ✅ G7 |
| Evidence packs | plan+claims | packs | D | — | plan | — | — | ➖ |
| glossary | plan+packs | glossary | M | strong | plan | `script_glossary` | 2 | ➖ |
| persian_script_segment | plan+packs+glossary | turns | M | strong | glossary | `script_draft` | 2 | ✅ |
| Script checks | script | checks | D | — | script | `checks` | — | ✅ G8 |
| script_verifier | script+evidence | verdict | M | **reviewer** | checks | `verification` | 2 | ✅ G9 |
| script_reviser | issues | revised | M | strong | verdict | conditional | 2 | ✅ G10 |
| TTS segmentation | script | chunks | D | — | approval | `chunks.json` | — | ➖ |
| TTS | chunk | WAV | M | tts | chunks | per content_hash | 1(+1) | ➖ |
| WAV validate | WAV | verdict | D | — | TTS | — | — | ➖ |
| ASR | WAV | transcript | M | asr | WAV | per wav_sha | 1 | ➖ |
| **audio QA** | expected vs heard | verdict | D | — | ASR | — | — | ✅ G11 |
| Assembly | segments | final.wav | D (ffmpeg) | — | QA | — | — | ✅ G12 |

**Mandatory:** parse، blocks، document map، evidence extraction، coverage، plan، script، checks، TTS، assembly.
**Conditional:** OCR، search/capture، map partitioning (فقط اگر > `maximum_input_characters`)، reconciliation (چندمنبعی)، reviser (فقط اگر verdict ≠ pass)، regeneration (فقط verdict = `regenerate`).
**فقط برای auditability:** disagreement graph، budget report، claim priorities، block-build report.
**قابل parallel شدن:** `document_map_part`، `evidence_extraction` (انجام‌شده)، `persian_script_segment`، TTS، ASR، capture چندمنبعی.
**روی critical path:** همه‌ی مدل‌کال‌ها؛ اما ۹۲٪ زمان دیواری، انتظار انسانی است (بخش ۵).

---

## 4. Observability / Data Adequacy Audit

### واگرایی بنیادی: ledger در برابر filesystem

| منبع | رکورد واقعی | عمیق‌ترین stage |
|---|---|---|
| `ledger.sqlite3` | **۱۴** فراخوانی provider واقعی | `evidence_extraction` |
| `workspaces/*/model-runs/` | **۳۶۵** رکورد | `script_verifier` |

STATUS.md می‌گوید «همه‌ی فراخوانی‌های Gemini از contract یکپارچه‌ی observability عبور می‌کنند». در عمل، store فایل‌سیستمی ۲۶ برابر ledger داده دارد و ledger هیچ‌یک از مراحل script/glossary/plan را ندارد.

### شکستگی‌های همبستگی (اندازه‌گیری‌شده)

```sql
SELECT (workflow_run_id IS NULL), COUNT(*) FROM model_calls GROUP BY 1;
-- (1, 358)   ← هر ۳۵۸ ردیف NULL

SELECT (pipeline_trace_id IS NULL),(parent_span_id IS NULL),COUNT(*) FROM model_calls GROUP BY 1,2;
-- (1, 1, 358)

SELECT kind,status,COUNT(*),SUM(call_count),SUM(total_tokens) FROM pipeline_runs GROUP BY 1,2;
-- هر ۳۵۸ run: call_count=0 , total_tokens=0
```

نتیجه: **بازسازی end-to-end از ledger ممکن نیست.** view `trace_nodes` وجود دارد اما چون `pipeline_trace_id` همیشه NULL است، شاخه‌ی model_call هرگز به span متصل نمی‌شود.

> کد HEAD این را حل کرده است: `observability.py:122-123` مقادیر را از contextvar محیطی می‌گیرد. اما **هیچ اجرایی این مسیر را تمرین نکرده**. `Code-supported inference` — قابلیت هست، شاهد اجرا نیست.

### نقص‌های صحت

1. **`ModelAttemptRecord.started_at` در واقع زمان پایان است.** رکورد بعد از بازگشت فراخوانی ساخته می‌شود و `started_at` یک `default_factory=datetime.now(UTC)` دارد (`model_runner.py:171-182`, `207-217`). اثبات: برای هر ۶۷ رکورد live، `attempt.started_at − latency_ms == record.started_at` با خطای < ۱ ثانیه؛ ۰ مورد نامنطبق. → هر تحلیل هم‌زمانی مبتنی بر این فیلد بدون تصحیح **غلط** است.

2. **attemptهای ناموفق usage ثبت نمی‌کنند.** ۱۵۳ از ۴۸۱ attempt (۳۱.۸٪) هیچ token count ندارند — دقیقاً همان attemptهایی که هزینه‌ی retry را می‌سازند. در `model_runner.py:207-217` حتی وقتی `response is not None` (یعنی مدل خروجی داد و بابتش پول داده شد، ولی deterministic validation ردش کرد) `usage=` پاس داده نمی‌شود. → **هزینه‌ی توکنی retry ساختاراً غیرقابل‌اندازه‌گیری است.**

3. **thinking / cached tokens تقریباً همیشه NULL.** از ۴۸۱ attempt: ۴۳۲ هیچ‌کدام، ۳۰ فقط thinking، ۱۸ فقط cached، ۱ هر دو.

4. **latency فقط provider است.** `response.latency_ms` صرفاً فراخوانی provider را می‌پوشاند؛ backoff، رندر prompt، اعتبارسنجی، نوشتن artifact و queue wait بیرون می‌مانند. تفکیک provider-latency از stage-latency ممکن نیست.

5. **تفکیک rejected از succeeded ناقص است.** ledger `reject()` دارد و ۱ ردیف `rejected` ثبت شده؛ اما در store فایل‌سیستمی، runای که بعد از rejection در attempt بعدی موفق شود `succeeded` ثبت می‌شود و rejection فقط داخل `attempts[]` می‌ماند. success rate سطح-run، ردشدن محتوایی را پنهان می‌کند.

6. **۱ فراخوانی `running` رهاشده** از ۰۸-۰۸ (`b1898e16`) و ۶ رکورد `running` در filesystem — هیچ reconciliation‌ای آن‌ها را نمی‌بندد.

### قابلیت محاسبه‌ی هزینه

ماشین‌آلات کامل است (`services/model_pricing.py`، `CostPricer`، ستون‌های `cost_micros`/`pricing_version`، فرمان‌های `cost` و `observability-reprice`)، اما `config/model-pricing.toml` دارای `version = "unset"` و **صفر ردیف فعال** است — همه کامنت شده. لذا هر call به‌عنوان unpriced حساب می‌شود.

> **ناسازگاری با مستندات:** STATUS.md:70 می‌گوید «Pricing-versioned cost calculation is not implemented yet». این **دیگر درست نیست** — پیاده‌سازی شده و فقط جدول قیمت خالی است.

### ماتریس کفایت داده

| Metric/Question | قابل محاسبه؟ | منبع | محدودیت | Confidence |
|---|---|---|---|---|
| latency provider بر stage | ✅ | `record.attempts[].latency_ms` | فقط n=1 پروژه | High |
| latency کل stage (شامل deterministic) | ❌ | — | span فقط تست است | High |
| queue wait | ❌ | — | اصلاً instrument نشده | High |
| توکن ورودی/خروجی attemptهای موفق | ✅ | `attempts[].usage` | — | High |
| توکن attemptهای ناموفق/ردشده | ❌ | — | `usage` پاس داده نمی‌شود | High |
| thinking / cached tokens | ⚠️ | usage | ۹۰٪ NULL | High |
| هزینه‌ی هر call/stage/episode | ❌ | — | جدول قیمت خالی | High |
| هزینه‌ی TTS/ASR/Search/OCR | ❌ | — | نه ردیف قیمت، نه شمارش دقیقه/کاراکتر | High |
| نرخ retry بر stage | ✅ | `len(attempts)` | — | High |
| علت retry | ✅ | `attempts[].error_message` | — | High |
| نرخ بازیابی attempt ۲/۳ | ✅ | ترکیب status+attempts | n کوچک | Medium |
| بازسازی trace end-to-end | ❌ | — | همبستگی NULL | High |
| cache hit rate | ⚠️ | `pipeline_events` `cache.lookup` | فقط داده‌ی تست | High |
| wall-clock کل workflow | ⚠️ | اختلاف timestamp رکوردها | شکاف‌ها تفکیک‌ناپذیرند | Medium |
| latency ادراک‌شده‌ی کاربر | ❌ | — | instrument نشده | High |
| زمان بازبینی دستی | ❌ | — | instrument نشده | High |
| کیفیت خروجی ↔ پیکربندی | ❌ | — | هیچ human score ذخیره نمی‌شود | High |

---

## 5. Performance and Cost Findings

### توزیع توکن و latency (۳۶۵ رکورد، همه‌ی پروژه‌ها، همه‌ی attemptها)

| stage | runs | attempts | in_tok | out_tok | in:out | %in_tok | Σlat (s) | %lat |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **document_map_part** | 60 | 76 | 2,671,957 | 115,368 | 23.2 | **60.3%** | 775.0 | **28.3%** |
| evidence_extraction | 243 | 320 | 785,982 | 109,620 | 7.2 | 17.7% | 771.0 | 28.2% |
| document_map | 10 | 15 | 576,567 | 13,910 | 41.4 | 13.0% | 85.3 | 3.1% |
| **script_verifier** | 3 | 4 | 79,604 | **42** | **1895.3** | 1.8% | 99.8 | 3.6% |
| script_segment | 8 | 10 | 79,480 | 6,694 | 11.9 | 1.8% | 216.8 | 7.9% |
| glossary | 9 | 16 | 69,818 | 1,787 | 39.1 | 1.6% | 52.9 | 1.9% |
| coverage_audit | 8 | 8 | 69,475 | 3,561 | 19.5 | 1.6% | 88.8 | 3.2% |
| episode_plan | 7 | 11 | 47,276 | 5,028 | 9.4 | 1.1% | 189.2 | 6.9% |
| claim_reconciliation | 11 | 15 | 46,605 | 10,750 | 4.3 | 1.1% | 410.9 | 15.0% |
| document_map_merge | 6 | 6 | 1,538 | 383 | 4.0 | 0.0% | 47.3 | 1.7% |
| **TOTAL** | **365** | **481** | **4,428,302** | **267,143** | 16.6 | 100% | **2,737** | 100% |

### latency بر stage (percentile؛ فقط attemptهای دارای latency)

| stage | model | p50 ms | p95 ms | max ms |
|---|---|--:|--:|--:|
| document_map_part | gemini-3.5-flash-lite | 7,962 | 33,152 | 118,756 |
| evidence_extraction | gemini-3.5-flash-lite | 2,141 | 3,656 | 28,719 |
| document_map | gemini-3.5-flash-lite | 5,413 | 9,048 | 9,588 |
| script_verifier | gemini-3.6-flash | 22,541 | 46,990 | 50,021 |
| script_segment | gemini-3.6-flash | 22,108 | 31,823 | 32,136 |
| claim_reconciliation | gemini-3.6-flash | 17,831 | 50,379 | 50,380 |
| coverage_audit | gemini-3.6-flash | 10,650 | 14,506 | 15,306 |
| episode_plan | gemini-3.6-flash | 16 | 26,200 | 27,549 |
| glossary | gemini-3.6-flash | 1,590 | 16,886 | 19,686 |
| **okian** (qwen3.6-35 / gemma4-31) | — | 413–430 | — | 73,063 |

**دم توزیع واقعی است:** `document_map_part` نسبت p95/p50 برابر ۴.۲ و max/p50 برابر ۱۴.۹ دارد. یک فراخوانی ۱۱۹ ثانیه‌ای در برابر میانه‌ی ۸ ثانیه.

### critical path و زمان دیواری (پروژه `f781a5c7`، live)

```
اولین شروع : 2026-08-09T09:28:14Z
آخرین پایان: 2026-08-09T12:31:15Z
wall clock : 183.0 دقیقه
provider   :  14.7 دقیقه  ← 8.0٪
شکاف       : 168.3 دقیقه  ← 92.0٪
```

بزرگ‌ترین شکاف‌ها:

| مدت | بین | تفسیر |
|--:|---|---|
| 79.1 دقیقه | document_map_part → document_map_part | **بازیابی از شکست** (اجرای کامل دوباره) |
| 32.3 دقیقه | script_verifier → script_verifier | بازیابی از ۵۰۳ |
| 30.5 دقیقه | claim_reconciliation → evidence_extraction | بازیابی از شکست |
| 20.0 دقیقه | episode_plan → glossary | **G7 تأیید انسانی Episode Plan** |

`Measured finding`: **زمان انتظار کاربر عملاً هیچ ارتباطی با هزینه‌ی محاسباتی ندارد.** بهینه‌سازی توکن، time-to-value را جابه‌جا نمی‌کند؛ حذف rerunهای ناشی از شکست و کوتاه‌کردن gateها می‌کند.

### هم‌زمانی (تصحیح‌شده بابت باگ `started_at`)

| stage | attempts | burst wall (s) | provider (s) | avg conc | max conc |
|---|--:|--:|--:|--:|--:|
| evidence_extraction | 52 | 166.5 | 165.8 | **1.00** | 1 |
| document_map_part | 17 | 322.5 | 320.3 | 0.99 | 1 |
| script_segment | 6 | 135.3 | 133.3 | 0.99 | 1 |
| claim_reconciliation | 4 | 117.1 | 115.1 | 0.98 | 1 |
| script_verifier | 3 | 85.5 | 84.5 | 0.99 | 1 |

فاصله‌ی بین پایان یک attempt و شروع بعدی: میانه **۱۴ میلی‌ثانیه**، حداقل ۴ms، حداکثر ۲۷ms، **صفر** مورد همپوشانی. اجرا کاملاً سریالی بود.

**در HEAD:** تنها `evidence_extractor.py` از `ThreadPoolExecutor` استفاده می‌کند (`evidence_extraction_workers=4`). `document_mapper.py:65` (`for part_number, partition in enumerate(...)`) و `audio_pipeline_service.py:115,141` (`for chunk in chunks`) هنوز حلقه‌ی سریالی‌اند. یعنی **۶۰.۳٪ از توکن‌ها و ۲۸.۳٪ از زمان provider هنوز روی مسیر سریالی است.**

### اقتصاد retry

| stage | runs | attempts | att/run | runs با >۱ attempt |
|---|--:|--:|--:|--:|
| evidence_extraction | 243 | 320 | 1.32 | 55 |
| document_map_part | 60 | 76 | 1.27 | 21 |
| glossary | 9 | 16 | **1.78** | 7 |
| episode_plan | 7 | 11 | **1.57** | 4 |
| document_map | 10 | 15 | 1.50 | 5 |
| claim_reconciliation | 11 | 15 | 1.36 | 4 |

**محرک retry (۱۲۲ attempt منجر به تلاش مجدد):**

| # | % | stage | نوع | پیام |
|--:|--:|---|---|---|
| **77** | **63.1%** | evidence_extraction | DeterministicValidation | `supporting_excerpt must be copied from the supplied source block` |
| 5 | 4.1% | document_map_part | ModelProvider | Internal Server Error |
| 4 | 3.3% | glossary | ModelRateLimit | 429 RESOURCE_EXHAUSTED |
| 3 | 2.5% | claim_reconciliation | ModelProvider | Server disconnected |
| 2 | 1.6% | episode_plan | ModelProvider | `additionalProperties is not supported in the Gemini API` |

`Measured finding`: **یک علت، ۶۳٪ از کل retryهای pipeline را می‌سازد.**

مهم: این یک سخت‌گیری تایپوگرافیک نیست. مسیر اعتبارسنجی لایه‌ای و درست است — `_validate_claim_excerpt` (`evidence_extractor.py:357-368`) ابتدا `locate_excerpt` متساهل را می‌زند (که گیومه، خط تیره، ellipsis، ي/ك/ة، ZWNJ، اعراب، ارقام و case را نرمال می‌کند) و اگر پیدا شد، excerpt را به متن **verbatim** بازنویسی می‌کند؛ سپس `validate_evidence_extraction` سخت‌گیرانه دوباره چک می‌کند. پس `None` برگشتن `locate_excerpt` یعنی متن **حتی پس از نرمال‌سازی تهاجمی در بلوک وجود ندارد** — یعنی مدل fast واقعاً paraphrase یا اختراع کرده است.

`Measured finding`: نرخ hallucination شاهد برای `gemini-3.5-flash-lite` در این task ≈ **۷۷ از ۳۲۰ attempt (۲۴٪)**.

**مسیر تخریب خاموش:** `_salvage_draft_inplace` (`evidence_extractor.py:371-399`) در آخرین attempt claimهای نامعتبر را **بی‌صدا حذف** می‌کند و run را `succeeded` نگه می‌دارد. بلوک با claim کمتر (یا صفر) تمام می‌شود بدون آنکه در status منعکس شود.

### پروفایل هزینه‌ی ورودی evidence extraction

| کمیت | مقدار |
|---|--:|
| بلوک انتخاب‌شده | 40 از 198 |
| توکن متن منبع تحلیل‌شده | 55,913 |
| توکن ورودی واقعاً پرداختی (live) | 124,960 |
| **ضریب سربار** | **2.2×** |
| سهم توکن ورودی که متن منبع نیست | **55.3%** |
| میانگین ورودی هر call | 2,840 |
| میانگین توکن منبع هر بلوک | 1,398 |

≈۱٬۴۴۰ توکن ثابت در هر فراخوانی (system prompt + `analysis_profile` JSON + `working_thesis` + `section_context` + schema) بارها ارسال می‌شود.

### بودجه‌ی تحلیل خروجی‌آگاه — هر دو کنترل شکست خورده‌اند

| کنترل | هدف | واقعی | نتیجه |
|---|--:|--:|---|
| `evidence_input_token_budget` | 18,000 | **55,913** | **۳.۱× تجاوز** |
| `block_coverage_target` | 0.35 | **0.2166** | **کم‌پوشش** |

علت در `analysis_profile.py:149-179`: مجموعه‌ی `selected` **قبل از** هر بررسی بودجه با «اولین بلوک هر section دارای `required_for_global_understanding`» seed می‌شود. حلقه‌ی رتبه‌بندی فقط وقتی می‌شکند که `selected_tokens >= target_tokens` — که از همان ابتدا برقرار است. اثبات عددی: sectionهای required = ۴۰، بلوک‌های انتخاب‌شده = ۴۰ (تطابق دقیق). **حلقه‌ی رتبه‌بندی و بودجه هرگز فعال نشدند.**

### rework (بزرگ‌ترین اتلاف اندازه‌گیری‌شده)

| | runs | in_tok | out_tok | provider time |
|---|--:|--:|--:|--:|
| **ARCHIVED (دورریخته)** | 273 | **2,982,602** | 177,710 | 1,619.5 s |
| **LIVE (نهایی)** | 67 | 862,455 | 57,742 | 882.4 s |

**۷۷.۶٪ از توکن ورودی خرج‌شده روی این پروژه در revisionها دور ریخته شد.**

### rerun اثبات‌شده‌ی document map

| زمان | status | in_tok | `input_hash` |
|---|---|--:|---|
| 09:28:14 | succeeded | 62,529 | `2e201743307d` |
| 09:28:39 | succeeded | 55,549 | `c4cd156ebf64` |
| 09:28:56 | succeeded | 47,300 | `b27bd35c3b96` |
| 09:29:58 | succeeded | 50,534 | `fd5237f82b53` |
| 09:30:04 | **failed** | 0 | `ffcc3c407b81` |
| 10:49:27 | succeeded | 62,489 | **`2e201743307d`** ← تکراری |
| 10:49:34 | succeeded | 55,508 | **`c4cd156ebf64`** ← تکراری |
| 10:49:44 | succeeded | 47,341 | **`b27bd35c3b96`** ← تکراری |
| 10:49:53 | succeeded | 50,717 | **`fd5237f82b53`** ← تکراری |
| 10:50:33 | succeeded | 82,901 | `ffcc3c407b81` |
| 10:52:40 | succeeded | 82,996 | `042896385a9a` |

**۴ از ۴ پارتیشن موفق با `input_hash` یکسان دوباره پرداخت شدند: ۲۱۵٬۹۱۲ توکن ورودی برای صفر اطلاعات جدید.** `input_hash` در `model_runner.py:100-109` از قبل محاسبه و ذخیره می‌شود اما هرگز به‌عنوان کلید reuse خوانده نمی‌شود.

---

## 6. Quality Findings

### 6.1 P0 — `document_map_merge` یک no-op خاموش است

**Observation.** در اجرای واقعی، merge این را برگرداند:

```json
{"cross_section_threads": [], "globally_required_section_ids": [], "section_updates": [],
 "warnings": ["No partitions were provided in the input context."], "working_thesis": null}
```

ورودی ۲۵۶ توکن، خروجی ۶۴ توکن، status = **`succeeded`**.

**Evidence.**
- قالب `prompts/document_map_merge/1.0.0/user.md` شامل `{{ partitions | tojson }}` است.
- `prompt_loader.py:13` — `_PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")`. این regex فیلتر Jinja را **نمی‌گیرد**.
- در نتیجه `partitions` نه در `required` می‌آید (پس خطای «متغیر گم‌شده» نمی‌دهد)، نه جایگزین می‌شود، نه در بررسی `unresolved` گیر می‌کند (`prompt_loader.py:131-145`).
- بازتولید مستقیم با متغیرهای واقعی: رشته‌ی تحت‌اللفظی `{{ partitions | tojson }}` در prompt باقی می‌ماند؛ داده‌ی پارتیشن حضور ندارد؛ `_render` بی‌صدا برمی‌گردد.
- **تنها موردی است که در کل ۶۶ فایل prompt این مشکل را دارد.**
- artifact واقعی `sources/*/document-map.json`: `cross_section_threads: 10` (همه محلی)، **`CROSS-PARTITION dependencies: 0`**، و هشدار `"No partitions were provided in the input context."` عیناً در artifact تحویلی ذخیره شده است.

**Interpretation.** برای **هر** سندی که به بیش از یک پارتیشن تقسیم شود — یعنی دقیقاً کتاب‌ها و PDFهای بلندی که README به‌عنوان قابلیت شاخص تبلیغ می‌کند — «global merge» هیچ کاری نمی‌کند. نقشه صرفاً الحاق نقشه‌های مستقل پارتیشنی است.

اثر ثانویه: `_merge_part_drafts` وقتی `merge.working_thesis` تهی است به `next((draft.working_thesis for draft in part_drafts if draft.working_thesis), None)` عقب‌نشینی می‌کند — یعنی **thesis پارتیشن ۱** (فصل‌های آغازین آرنت) به‌عنوان thesis سراسری کل کتاب به هر ۲۴۳ فراخوانی evidence extraction تزریق می‌شود.

اثر سوم: چون هر پارتیشن مستقل تصمیم می‌گیرد کدام sectionهایش «globally required» است، ۴۰ از ۴۷ section علامت خوردند — که بعد selection بلوک را تماماً تعیین کرد (بخش ۵).

**Counterfactual.** با merge سالم انتظار می‌رفت: وابستگی‌های بین‌پارتیشنی > ۰، thesis سراسری از کل متن، و مجموعه‌ی به‌مراتب کوچک‌تری از sectionهای واقعاً globally required.

**Impact.** کیفیت (انسجام مفهومی اسناد بلند)، و هزینه (انتخاب بلوک از سیگنال بی‌اعتبار).
**Confidence: High** (کد + بازتولید + artifact + پیام خود مدل).
**Validation.** اصلاح قالب، اجرای مجدد روی همان EPUB، شمارش وابستگی‌های بین‌پارتیشنی و مقایسه‌ی sectionهای required.

**چرا تست‌ها نگرفتند:** `tests/test_document_mapper_large_inputs.py` از `HierarchicalRunner` ساختگی استفاده می‌کند که `variables` را می‌گیرد و draft آماده برمی‌گرداند — `PromptLoader` را کاملاً دور می‌زند. هیچ تستی هیچ قالب prompt را با متغیرهای نماینده render نمی‌کند. تست فقط ادعا می‌کند `stages[-1] == "document_map_merge"` (یعنی مرحله صدا زده شد)، نه اینکه چیزی دریافت کرد.

### 6.2 P0 — تشخیص «جمله‌ی افتاده» در Audio QA به‌طور ریاضی شکسته است

**Observation.** در اجرای صوتی واقعی (archive `20260809T033602708665Z`): ۲۴ chunk، ۱۸ pass، **۶ `manual_review`**، `regenerated_chunk_ids: []`، `status: "verified"`، `final_duration_seconds: 700.94`.

هر ۶ مورد **false positive** هستند. `similarity_ratio`: ۰.۹۹۷۱، ۰.۹۹۵۳، ۰.۹۹۸۴، ۰.۹۹۵۳، ۰.۹۹۴۸، ۰.۹۹۲۶ — همه بالای آستانه‌ی pass (۰.۹۰). تنها دلیل ردشدن، ناتهی‌بودن `missing_sentences` است.

**Evidence.** `audio_qa.py:108-115`:

```python
def _sentence_similarity(sentence, transcript):
    needle, haystack = _normalize(sentence), _normalize(transcript)
    if needle in haystack: return 1
    return SequenceMatcher(None, needle, haystack, autojunk=False).ratio()
```

`SequenceMatcher.ratio()` بر مجموع طول هر دو رشته نرمال می‌شود. برای جمله‌ای به طول L داخل رونویسی به طول H، سقف نظری = `2L/(L+H)`. اجرای مجدد کد واقعی روی داده‌ی واقعی:

| chunk | ratio | طول جمله | طول رونویسی | **سقف ممکن** | امتیاز واقعی |
|---|--:|--:|--:|--:|--:|
| audio-0001 | 0.9971 | 84 | 345 | **0.392** | 0.387 |
| audio-0007 | 0.9953 | 124 | 323 | **0.555** | 0.550 |
| audio-0009 | 0.9984 | 125 | 310 | **0.575** | 0.575 |
| audio-0011 | 0.9953 | 124 | 317 | **0.562** | 0.558 |
| audio-0015 | 0.9948 | 43 | 577 | **0.139** | 0.135 |
| audio-0016 | 0.9926 | 30 | 135 | **0.364** | 0.352 |

آستانه ۰.۶۰ است. **در هر شش مورد سقف ممکن زیر آستانه است** — یعنی حتی تطابق کامل هم رد می‌شود. و امتیاز واقعی عملاً روی سقف نشسته، که یعنی جملات در عمل کامل تطبیق می‌خورند.

تنها راه فرار، شرط `needle in haystack` است که با یک نویسه‌ی نرمال‌نشده می‌شکند. `_normalize` (`audio_qa.py:93-101`) ي/ك/ۀ، ZWNJ/ZWJ و `U+064B-065F,0670` را می‌پوشاند اما **أ (U+0623)، إ، آ و ء (U+0621)** را نه:

| نوشتار سناریو | رونویسی ASR | برابر پس از نرمال‌سازی؟ |
|---|---|---|
| `تأثیری` | `تاثیری` | ❌ |
| `تأمل` | `تامل` | ❌ |
| `اشیاء` | `اشیا` | ❌ |
| `اصلاً` | `اصلا` | ✅ |

همچنین `_SENTENCES` روی `[.!؟؛]` می‌شکند اما نه روی `:` — و ASR دونقطه را نقطه می‌گیرد، پس مرزبندی جمله بین انتظار و رونویسی متفاوت می‌شود.

نکته‌ی جالب: در `audio-0007` متن سناریو غلط املایی `باپایام` داشت و TTS/ASR آن را `باپایان` تولید کرد — یعنی صوت **درست‌تر** از متن بود، و QA همان را «افتاده» علامت زد.

**Interpretation.** دروازه‌ی Audio QA در مسیر خودکار **بی‌اثر** است: `manual_review` نه regeneration را فعال می‌کند (`_needs_regeneration` فقط `regenerate` را می‌پذیرد، `audio_pipeline_service.py:143-146`) و نه مسدود می‌کند (`audio_qa_accept_manual_review: bool = True` در `config.py:119`). تنها اثرش کاهش `passed_chunk_count` است. پس ۲۵٪ نرخ false positive، هزینه‌ی توکنی ندارد اما **زمان بازبینی انسانی** تولید می‌کند و اعتماد به دروازه را از بین می‌برد.

ریسک معکوس و جدی‌تر: یک نقص **واقعی** با شباهت ≥ ۰.۷۸ نیز `manual_review` می‌گیرد و به همان شکل خاموش پذیرفته می‌شود.

**Confidence: High** (اجرای مجدد کد واقعی روی داده‌ی واقعی).
**Validation.** نرمال‌سازی همزه‌ها + مقایسه‌ی جمله با پنجره‌ی هم‌اندازه به‌جای کل رونویسی؛ اجرای مجدد روی همان ۲۴ chunk؛ انتظار: ۲۴/۲۴ pass. سپس تزریق نقص عمدی (حذف یک جمله) و تأیید اینکه گرفته می‌شود.

### 6.3 P1 — writer و verifier یک مدل بودند

`config/model-routing.toml`: `persian_script_segment = "gemini_strong"`، `script_verifier = "gemini_reviewer"`. کامنت خود فایل هشدار می‌دهد که `gemini_reviewer` وقتی `THESISOUND_MODEL_REVIEWER` تنظیم نباشد به `THESISOUND_MODEL_STRONG` برمی‌گردد «and `doctor` warns about self-grading».

در اجرای واقعی: `script_segment` → `gemini-3.6-flash`، `script_verifier` → `gemini-3.6-flash`. **همان مدل.**

نتیجه‌ی verifier: ۲۶٬۳۸۱ توکن ورودی → **۲۲ توکن خروجی**:
```json
{"verdict": "pass", "issues": [], "unsupported_claim_ratio": 0.0}
```

این مستقیماً قاعده‌ی README را نقض می‌کند: «writer تنها verifier خروجی خودش نیست». نسبت ورودی به خروجی در سطح stage برابر **۱۸۹۵:۱** است.

`Code-supported inference`: verifier در پیکربندی فعلی احتمالاً یک تأییدکننده‌ی گران است نه یک بازبین مستقل. اما با n=1 و بدون ground truth، **`Insufficient evidence`** برای اثبات اینکه verdictها بی‌ارزش‌اند.

### 6.4 کیفیت متن فارسی (اجرای واقعی، ۲۲ turn، ۱۱۱۲ کلمه)

**قوت‌ها (مشاهده‌ی مستقیم).** فارسی طبیعی و شنیداری؛ اصطلاحات منسجم و مطابق glossary (حیات فعال، زحمت، کار، عمل، انسان زحمت‌کش، انسان سازنده، تکثر، امر اجتماعی) با معادل انگلیسی در اولین کاربرد؛ وفادار به آرنت؛ لحن مناسب دانشجوی علوم انسانی؛ بدون نثر عمومی AI.

**ضعف‌ها.**

| مسئله | شاهد |
|---|---|
| **گوینده‌ی دوم عملاً filler است** | B: ۱۱ turn، ۱۰ تای آن `editorial_only=True`، فقط ۱ turn دارای evidence |
| **الگوی بازگویی سه‌گانه** | A بیان می‌کند → B همان را به‌شکل پرسش بازمی‌گوید → A دوباره تأیید و بازگویی می‌کند (turnهای ۰۲/۰۳/۰۴ و ۰۹/۱۰/۱۱ و ۱۵/۱۶/۱۷) |
| **آغازگرهای تأییدی تکراری** | «بله، دقیقاً» / «دقیقاً همین‌طور است» / «دقیقاً» / «کاملاً درست است» در ۴ turn |
| **B هرگز به چالش نمی‌کشد** | هیچ objection، هیچ پرسش از محدودیت، هیچ اختلاف‌نظر |
| **۳۲٪ کلمات بدون شاهد** | ۳۵۵ از ۱۱۱۲ کلمه در turnهای `editorial_only` |

قاعده‌ی «هر turn محتوایی باید claim و evidence معتبر داشته باشد» رعایت شده — اما با **برچسب‌زدن** نیمی از turnها به‌عنوان editorial.

### 6.5 قیف شاهد — overprocessing اندازه‌گیری‌شده

```
198 بلوک سند
 40 بلوک انتخاب‌شده        (20.2٪)
 70 claim استخراج‌شده
  6 ارجاع در evidence packs
 12 ارجاع در سناریوی نهایی  ← 17.1٪ از claimهای استخراج‌شده
```

`Measured finding`: **۸۲.۹٪ از claimهای استخراج‌شده هرگز وارد اپیزود نمی‌شوند.** با این حال، بخشی از این ذاتی است (coverage audit و prioritization به مجموعه‌ی بزرگ‌تر نیاز دارند تا انتخاب کنند)، پس این به‌تنهایی اتلاف نیست — ولی نسبت ۶:۱ توجیه تجربی ندارد.

### 6.6 coverage audit

با پوشش ۲۱.۶٪ از کتاب و ۷۰ claim عمدتاً از فصل‌های آغازین، coverage audit اعلام کرد: `central_question_status: "well_covered"`، `material_gaps: []`، `max_supported_minutes: 10`، `recommendation: "continue"`.

`Unverified hypothesis`: coverage audit تمایز کافی ندارد و یک «continue» تقریباً همیشگی تولید می‌کند. **`Insufficient evidence`** — برای اثبات به موارد منفی (corpus عمداً ناکافی) نیاز است.

### 6.7 پایداری و tail risk

`Insufficient evidence`. تنها یک اجرا. اما دم latency اندازه‌گیری‌شده (p95/p50 = ۴.۲ برای document_map_part، max ۱۱۹ ثانیه) و ۵ نوع خطای گوناگون provider در یک اجرا نشان می‌دهد variance واقعی است.

---

## 7. Stage Value Assessment

| Stage | حکم | دلیل (شاهد) |
|---|---|---|
| Research Brief | `Keep as-is` | ارزان، دروازه‌ی انسانی، ورودی همه چیز |
| Query Planning | `Insufficient evidence` | هیچ اجرای واقعی |
| Source Discovery | `Insufficient evidence` | ۵۶ فراخوانی همه با `gemini-test` |
| Source Triage | `Insufficient evidence` | prompt نسخه‌دار ندارد |
| Source Capture | `Insufficient evidence` | هیچ اجرای واقعی |
| Document Ingestion | `Keep as-is` | deterministic، cache محتوا-محور |
| Parse Quality Audit | `Insufficient evidence` | فقط روی EPUB سالم اجرا شده |
| **Document Map (part)** | **`Keep but optimize`** | ۶۰.۳٪ توکن، ۲۸.۳٪ latency، سریالی، بدون checkpoint |
| **Document Map (merge)** | **`Redesign`** | no-op اثبات‌شده؛ ابتدا اصلاح، سپس ارزیابی مجدد |
| **Evidence Extraction** | **`Keep but optimize`** | هسته‌ی ارزش، اما ۵۵.۳٪ سربار ورودی و ۲۴٪ نرخ hallucination |
| Claim Prioritization | `Keep as-is` | deterministic، ارزان |
| Claim Reconciliation | `Make conditional` | ۱۵٪ کل latency، p95 = ۵۰s؛ روی corpus تک‌منبعی ارزش نامعلوم |
| Disagreement Graph | `Keep as-is` | deterministic، ارزان |
| Coverage Audit | `Insufficient evidence` | یک نمونه، همه‌چیز «well_covered» |
| Glossary | `Keep but optimize` | بالاترین نرخ retry (۱.۷۸)، ۳۹:۱ ورودی به خروجی؛ اما اصطلاحات در سناریو واقعاً منسجم بودند |
| Episode Plan | `Keep as-is` | دروازه‌ی انسانی G7، خروجی مصرف‌شده |
| Persian Script Generation | `Keep as-is` | کیفیت خروجی واقعاً خوب |
| Script Checks | `Keep as-is` | deterministic، ارزان، word count/duration |
| **Script Verifier** | **`Redesign`** | خودارزیابی اثبات‌شده؛ ۱۸۹۵:۱؛ باید مدل متفاوت اجباری شود |
| Script Reviser | `Insufficient evidence` | در اجرای واقعی هرگز فعال نشد (verdict = pass) |
| TTS Segmentation | `Keep as-is` | deterministic، chunkها با content_hash reuse می‌شوند |
| TTS Generation | `Keep but optimize` | سریالی (`for chunk in chunks`) |
| Audio Assembly | `Keep as-is` | ffmpeg loudnorm، خروجی معتبر |
| **Audio QA / ASR** | **`Redesign`** | ۲۵٪ false positive اثبات‌شده؛ در مسیر خودکار نه مسدود می‌کند نه اصلاح |
| Artifact Persistence | `Keep as-is` | اتمی، content-addressed |
| Workflow Revision | `Keep but optimize` | کار می‌کند، اما ۷۷.۶٪ توکن دورریز تولید کرد |
| Cache/Reuse | `Keep but optimize` | طراحی خوب؛ شکاف: بدون reuse سطح partition |

---

## 8. Failure Propagation Analysis

| خطای بالادستی | نقطه‌ی کشف | اثر پایین‌دستی | بازیابی فعلی | ریسک باقی‌مانده |
|---|---|---|---|---|
| **merge خالی** | **هیچ‌جا** (warning ذخیره می‌شود، کسی نمی‌خواند) | صفر وابستگی بین‌پارتیشنی؛ thesis پارتیشن‌۱ به کل کتاب تعمیم می‌یابد؛ ۴۰/۴۷ section «required» → انتخاب بلوک از سیگنال بی‌اعتبار | ندارد | **بالا — خاموش، دائمی، در artifact تحویلی** |
| paraphrase شاهد توسط مدل | `_validate_claim_excerpt` | retry (۶۳٪ کل retryها) | ۳ attempt، سپس `_salvage_draft_inplace` | متوسط — claimها **بی‌صدا حذف** می‌شوند، run همچنان `succeeded` |
| شکست یک partition | استثنا در `map_document` | کل stage از نو | rerun کامل | **بالا — ۲۱۵٬۹۱۲ توکن اندازه‌گیری‌شده** |
| ۵۰۳/۵۰۰ provider | attempt | retry با backoff نمایی | ۲–۳ attempt | پایین |
| ۴۲۹ rate limit | attempt | چرخش کلید، سپس «همه‌ی کلیدها بلاک» | key pool | متوسط — glossary بالاترین نرخ |
| schema Okian | `SchemaValidationError` | شکست stage | بدون fallback | بالا اگر Okian فعال شود (۸/۸ شکست) |
| اختلاف املایی فارسی TTS/ASR | Audio QA (**غلط**) | ۶ chunk به بازبینی دستی | هیچ (auto-accept) | **بالا — false positive و false negative هر دو** |
| نقص واقعی صوت با شباهت ≥۰.۷۸ | Audio QA (**نمی‌گیرد**) | وارد فایل نهایی | فقط G12 گوش‌دادن انسانی | بالا |
| فراخوانی رهاشده در `running` | هیچ‌جا | ردیف orphan در ledger | ندارد | پایین (فقط گزارش‌گیری) |

**provenance:** برای زنجیره‌ی block → claim → evidence → turn کافی است (locator، block_id، evidence_id، claim_id همه deterministic و توسط برنامه ساخته می‌شوند). برای مسیر prompt → مدل → خروجی کافی **نیست** چون `raw_prompts_stored: false` است، پس نمی‌توان دید مدل دقیقاً چه دید — همان چیزی که تشخیص باگ merge را سخت کرد.

---

## 9. Ablation and Experiment Results

**اجرا شد (بدون هزینه‌ی provider):**

| # | آزمایش | روش | نتیجه |
|---|---|---|---|
| A1 | آیا merge داده می‌گیرد؟ | render مستقیم قالب با متغیرهای واقعی | ❌ placeholder تحت‌اللفظی؛ **قطعی** |
| A2 | آیا failureهای Audio QA واقعی‌اند؟ | اجرای مجدد `audio_qa` روی ۲۴ chunk واقعی | ❌ هر ۶ مورد false positive؛ سقف < آستانه؛ **قطعی** |
| A3 | هم‌زمانی واقعی | تصحیح باگ `started_at`، محاسبه‌ی همپوشانی | avg conc = ۱.۰۰؛ **قطعی** |
| A4 | reuse پارتیشن | مقایسه‌ی `input_hash` بین دو batch | ۴/۴ تکراری، ۲۱۵٬۹۱۲ توکن؛ **قطعی** |
| A5 | سربار prompt | توکن پرداختی ÷ توکن منبع | ۲.۲×؛ ۵۵.۳٪ غیر-منبع؛ **قطعی** |
| A6 | اجرای بودجه | مقایسه‌ی plan با profile | ۳.۱× تجاوز؛ selection == seeding؛ **قطعی** |
| A7 | پوشش prompt | اسکن هر ۶۶ فایل برای توکن‌های غیرقابل‌جایگزینی | فقط ۱ مورد (merge)؛ **قطعی** |

**اجرا نشد (نیازمند provider و مجوز هزینه).** هیچ‌کدام از ablationهای زیر بدون اجرای زنده ممکن نیست، و هیچ‌یک را بدون اجازه‌ی شما اجرا نکردم.

| ablation | چرا اکنون ممکن نیست |
|---|---|
| Document Map با/بدون | merge اکنون no-op است؛ ابتدا باید اصلاح شود وگرنه «بدون merge» را با «با merge» مقایسه می‌کنیم |
| Claim Reconciliation با/بدون | فقط corpus تک‌منبعی موجود است؛ منبع متعارض لازم |
| Coverage Audit با/بدون | ground truth «شکاف واقعی» وجود ندارد |
| Glossary با/بدون | نیازمند دو اجرای موازی + امتیازدهی انسانی انسجام اصطلاحات |
| Verifier/Reviser ۴ حالته | نیازمند مدل reviewer مستقل + قضاوت انسانی |
| Neighbor context ۰/۱/۲ | پروفایل brief مقدار ۰ می‌دهد؛ نیازمند اجرای duration بلند |
| Model tier | نیازمند اجرای کامل با هر tier و هزینه‌ی کامل |

جزئیات هرکدام در بخش ۱۲.

---

## 10. Prioritized Recommendations

| ID | Finding | Evidence | تغییر پیشنهادی | Quality | Latency | Cost | Effort | Risk | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| **R1** ⬛P0 | merge برای هر سند چندپارتیشنی no-op است | `prompt_loader.py:13`; artifact `document-map.json`; بازتولید A1 | فیلتر Jinja را از قالب بردار (`{{ partitions }}` کافی است چون `_render` غیر-رشته را JSON می‌کند)؛ **و** `_render` را طوری کن که هر `{{...}}` ناشناخته را خطا بدهد | **بالا** | ~۰ | ~۰ | خیلی کم | کم | **High** |
| **R2** ⬛P0 | تشخیص جمله‌ی افتاده ریاضاً غیرممکن است | `audio_qa.py:108-115`; جدول سقف A2 | مقایسه‌ی جمله را به بهترین پنجره‌ی هم‌اندازه محدود کن؛ أ/إ/آ/ء را در `_normalize` اضافه کن | **بالا** | ~۰ | ~۰ | کم | کم | **High** |
| **R3** ⬛P0 | شکست یک partition کل map را دوباره می‌خرد | جدول `input_hash`؛ ۲۱۵٬۹۱۲ توکن | draft هر partition را با کلید `input_hash` (که از قبل محاسبه می‌شود) persist کن و در rerun بخوان | متوسط | **بالا** | **بالا** | متوسط | کم | **High** |
| **R4** ⬛P0 | هزینه‌ی توکنی retry غیرقابل‌اندازه‌گیری است | `model_runner.py:207-217`; ۱۵۳/۴۸۱ attempt | وقتی `response is not None`، `usage=response.usage` را در `ModelAttemptRecord` شکست هم بگذار | ~۰ | ~۰ | ~۰ (فعال‌کننده) | خیلی کم | کم | **High** |
| **R5** 🟧P1 | بودجه‌ی تحلیل توسط seeding دور زده می‌شود | `analysis_profile.py:149-179`; ۵۵٬۹۱۳ در برابر ۱۸٬۰۰۰ | seeding را هم مشمول `target_tokens` کن (sectionهای required را رتبه‌بندی کن، نه اینکه همه را بی‌قید اضافه کنی) | متوسط | متوسط | **بالا** | کم | **متوسط** — ممکن است پوشش را کم کند؛ نیاز به آزمایش | **High** |
| **R6** 🟧P1 | writer و verifier یک مدل بودند | routing + رکوردهای اجرا (هر دو `gemini-3.6-flash`) | اگر `THESISOUND_MODEL_REVIEWER` تنظیم نیست، verifier را **مسدود** کن (نه warning در `doctor`) | **بالا** | ~۰ | کم | کم | کم | **High** |
| **R7** 🟧P1 | document map سریالی است و ۶۰٪ توکن را دارد | `document_mapper.py:65`; A3 | همان الگوی fan-out با circuit-breaker که در `evidence_extractor` هست را روی partitions ببر | ~۰ | **بالا** | ~۰ | متوسط | متوسط — سهمیه‌ی Gemini | **High** |
| **R8** 🟧P1 | ۵۵.۳٪ توکن ورودی evidence، سربار تکراری است | A5؛ ۲٬۸۴۰ در برابر ۱٬۳۹۸ | چند بلوک را در یک فراخوانی batch کن، یا context ثابت را در cache مدل بگذار | ~۰ | متوسط | **بالا** | متوسط | متوسط — ممکن است دقت استخراج را کم کند؛ **نیاز به آزمایش** | **High** |
| **R9** 🟨P2 | ۲۴٪ نرخ hallucination شاهد در مدل fast | ۷۷/۳۲۰ attempt | آزمایش tier: `evidence_extraction` روی مدل strong، مقایسه‌ی هزینه‌ی کل (اولیه + retry + claimهای ازدست‌رفته) | نامعلوم | نامعلوم | نامعلوم | کم (آزمایش) | کم | **Medium** |
| **R10** 🟨P2 | گوینده‌ی دوم filler است | ۱۰/۱۱ turn `editorial_only`، الگوی بازگویی سه‌گانه | prompt سناریو را طوری تغییر بده که B وظیفه‌ی مشخص داشته باشد (پرسش از محدودیت/اعتراض)، سپس blind A/B | **بالا** | ~۰ | کم | کم | متوسط | **Medium** |

**R1–R4 خطای صحت‌اند، نه بهینه‌سازی.** هر چهار مورد کم‌زحمت و کم‌ریسک‌اند و هیچ‌کدام به تصمیم معماری نیاز ندارند.

---

## 11. Proposed Target Pipeline

```text
CURRENT                                RECOMMENDED
─────────────────────────────────────  ─────────────────────────────────────
partition → part₁…partₙ (سریال)        partition → part₁…partₙ (موازی، محدود)
          → merge (no-op)                        → checkpoint هر part بر input_hash
                                                 → merge (اصلاح‌شده، واقعاً داده می‌گیرد)

evidence: ۱ بلوک/فراخوانی (سریال)      evidence: batch بلوک/فراخوانی (موازی)
          سربار ۵۵٪                              context ثابت مشترک

verifier = همان مدل writer             verifier = مدل مستقل اجباری،
                                        وگرنه مرحله مسدود می‌شود

audio QA: ۲۵٪ false positive،          audio QA: نرمال‌سازی همزه + پنجره‌ی
  auto-accept، بدون اصلاح                هم‌اندازه؛ manual_review واقعاً
                                         به G12 برود
```

**باقی می‌مانند:** brief، ingestion، blocks، document map، evidence، prioritization، coverage، plan، glossary، script، checks، TTS، assembly، ۵ دروازه‌ی انسانی.
**conditional می‌شوند:** claim reconciliation (فقط چندمنبعی)، reviser (فقط verdict ≠ pass — همین حالا هم هست)، regeneration.
**merge نمی‌شوند:** هیچ‌کدام. هیچ شاهدی برای ادغام ندارم.
**deterministic می‌شوند:** هیچ‌کدام از مراحل مدلی. اما `_render` باید سخت‌گیرانه شود (خطا روی placeholder ناشناخته).
**parallel می‌شوند:** `document_map_part`، TTS chunkها، `persian_script_segment`.
**دروازه‌ها:** بدون تغییر. ۵ دروازه‌ی انسانی برای محصولی با ادعای «قابل‌اعتماد و قابل‌ممیزی» زیاد نیست؛ اما G7 در اجرای واقعی ۲۰ دقیقه انتظار تولید کرد — کاندید نمایش نتیجه‌ی جزئی زودتر.
**cache:** سطح partition (جدید، R3)، سطح بلوک (موجود)، سطح سند مشترک (موجود و خوب)، سطح stage (موجود).

---

## 12. Experiment Backlog

**E1 — اثر merge (پس از R1)**
```
Hypothesis  merge سالم وابستگی بین‌پارتیشنی > ۰ و مجموعه‌ی required کوچک‌تر می‌دهد
Dataset     همان EPUB آرنت (۱۹۸ بلوک، ۶ پارتیشن) + یک PDF فارسی بلند
Variants    merge فعلی (no-op) | merge اصلاح‌شده
Metrics     تعداد وابستگی بین‌پارتیشنی؛ |required sections|؛ توکن انتخابی؛ must-cover recall
Threshold   وابستگی بین‌پارتیشنی > ۰ و required < ۸۰٪ کل sectionها
Cost        ~۲ اجرای map ≈ ۷۶۰k توکن ورودی
Decision    اگر required کاهش یابد، R5 را با آستانه‌ی جدید تنظیم کن
```

**E2 — batch کردن evidence (R8)**
```
Hypothesis  batch ۴ بلوکی ≥۳۵٪ توکن ورودی کم می‌کند بدون افت claim yield یا افزایش hallucination
Dataset     ۴۰ بلوک انتخاب‌شده‌ی همان پروژه
Variants    ۱ بلوک/فراخوانی (پایه) | ۲ | ۴ | ۸
Metrics     توکن ورودی کل؛ claim/بلوک؛ نرخ خطای excerpt؛ latency؛ نرخ salvage
Threshold   ≥۳۵٪ کاهش توکن، افت claim yield ≤۵٪، عدم افزایش نرخ excerpt error
Cost        ۴ × ~۱۲۵k = ~۵۰۰k توکن ورودی
Decision    بزرگ‌ترین batch که هر سه آستانه را برآورده کند
```

**E3 — tier مدل برای evidence (R9)**
```
Hypothesis  مدل strong با وجود قیمت بالاتر، به‌خاطر حذف ۲۴٪ retry ارزان‌تر یا هم‌ارز درمی‌آید
Dataset     همان ۴۰ بلوک
Variants    gemini-3.5-flash-lite (فعلی) | gemini-3.6-flash
Metrics     final cost = اولیه + retry + salvage-loss؛ نرخ excerpt error؛ claim yield؛ latency
Threshold   اگر strong نرخ خطا را >۱۵ واحد درصد کم کند و هزینه‌ی کل ≤۱.۲× باشد، عوض کن
Cost        ~۲۵۰k توکن ورودی
Decision    بر اساس هزینه‌ی کل نه قیمت هر call — **پیش‌نیاز: R4، وگرنه توکن retry دیده نمی‌شود**
```

**E4 — Audio QA پس از R2**
```
Hypothesis  اصلاح، false positive را به ~۰ می‌رساند بدون از دست دادن نقص واقعی
Dataset     ۲۴ chunk واقعی موجود (بدون هزینه‌ی provider) + ۵ chunk با نقص تزریقی
Variants    QA فعلی | QA اصلاح‌شده
Metrics     false positive؛ recall روی نقص تزریقی
Threshold   FP = ۰ روی ۲۴ chunk سالم؛ recall = ۱۰۰٪ روی جمله‌ی حذف‌شده
Cost        صفر برای بخش سالم (داده موجود است)
Decision    اگر recall < ۱۰۰٪ آستانه را تنظیم کن، نه الگوریتم را
```

**E5 — verifier مستقل (R6)** — `Insufficient evidence` تا وقتی مدل reviewer جدا تنظیم نشود. نیازمند ۴ حالت (writer / +verifier / +reviser / هر دو) و امتیازدهی انسانی روی unsupported claim و طبیعی‌بودن فارسی. حداقل ۵ اپیزود برای معنادار بودن.

---

## 13. Instrumentation Requirements (فقط requirement — پیاده نشد)

**بحرانی (بدون این‌ها بخش بزرگی از این ممیزی تکرارپذیر نیست):**
1. **usage روی attemptهای ناموفق/ردشده** — تنها راه دیدن هزینه‌ی retry.
2. **اصلاح `ModelAttemptRecord.started_at`** — الان زمان پایان است؛ هر تحلیل هم‌زمانی را باطل می‌کند.
3. **پرکردن `workflow_run_id` / `pipeline_trace_id` / `parent_span_id` روی مدل‌کال‌ها** — کد HEAD آماده است، اجرا لازم است.
4. **ردیف‌های قیمت در `model-pricing.toml`** — ماشین‌آلات کامل است، فقط داده ندارد.
5. **ذخیره‌ی prompt رندرشده** (`raw_prompts_stored: true`، دست‌کم redacted) — باگ merge با این در دقایق پیدا می‌شد.

**زمان‌بندی:** stage timing کامل (نه فقط provider)؛ queue wait؛ زمان محاسبه‌ی deterministic (parse/OCR/normalize/block build)؛ زمان I/O فایل و کوئری DB؛ زمان end-to-end workflow؛ latency ادراک‌شده‌ی کاربر (شروع درخواست تا اولین خروجی مفید).

**reuse:** hit/miss هر cache با کلید (رویداد `cache.lookup` هست — باید در اجرای واقعی هم بیاید)؛ artifact reuse در سطح partition و بلوک؛ توکن صرفه‌جویی‌شده بابت هر hit.

**کیفیت:** زمان بازبینی دستی هر دروازه؛ verdict انسانی ذخیره‌شده و متصل به prompt/model/config آن اجرا؛ نرخ FP/FN دروازه‌های ماشینی در برابر داوری انسانی؛ شمارش claimهای حذف‌شده توسط `_salvage_draft_inplace` به‌عنوان متریک درجه‌یک.

**هزینه‌های غیرتوکنی:** ثانیه‌ی TTS، ثانیه/کاراکتر ASR، تعداد کوئری search، صفحات OCR، زمان CPU/GPU محلی، رشد فضای ذخیره‌سازی، پهنای باند.

---

## 14. Appendix

### A. کوئری‌های کلیدی SQL

```sql
SELECT name,type FROM sqlite_master WHERE type IN ('table','index','view') ORDER BY type,name;

-- ledger عملاً از داده‌ی واقعی خالی است
SELECT stage,status,COUNT(*) FROM model_calls GROUP BY 1,2;
SELECT COUNT(*) FROM model_calls WHERE stage!='test' AND requested_model!='gemini-test';  -- 14

-- همبستگی شکسته
SELECT (workflow_run_id IS NULL),COUNT(*) FROM model_calls GROUP BY 1;              -- (1,358)
SELECT (pipeline_trace_id IS NULL),(parent_span_id IS NULL),COUNT(*)
  FROM model_calls GROUP BY 1,2;                                                    -- (1,1,358)
SELECT kind,status,COUNT(*),SUM(call_count),SUM(total_tokens)
  FROM pipeline_runs GROUP BY 1,2;                                                  -- همه call_count=0

-- هزینه غیرقابل‌محاسبه
SELECT (cost_micros IS NULL),(pricing_version IS NULL),COUNT(*) FROM model_calls GROUP BY 1,2;

-- spanها از test suite‌اند
SELECT process,COUNT(*),COUNT(DISTINCT pid) FROM pipeline_spans GROUP BY 1;         -- app,6774,40
SELECT substr(started_at,1,10),COUNT(*) FROM pipeline_spans GROUP BY 1;
```

### B. اسکریپت‌های تحلیل (scratchpad، خارج از مخزن)

`analyze_runs.py` (تجمیع stage×model)، `analyze_retries.py` (اقتصاد retry، rework)، `analyze_conc.py` (هم‌زمانی تصحیح‌شده)، `analyze_detail.py` (محرک retry، بازپرداخت `input_hash`، شکاف زمان دیواری).

### C. فایل‌ها و توابع مرجع

| موضوع | مرجع |
|---|---|
| باگ merge | `src/thesisound/prompt_loader.py:13,130-146`؛ `prompts/document_map_merge/1.0.0/user.md` |
| merge سریالی/بدون checkpoint | `src/thesisound/services/document_mapper.py:64-75` |
| بازگشت working_thesis | `src/thesisound/services/document_mapper.py::_merge_part_drafts` |
| repair شاهد | `src/thesisound/services/evidence_extractor.py:357-368`؛ `services/excerpt_matching.py` |
| حذف خاموش claim | `src/thesisound/services/evidence_extractor.py:371-399` |
| usage گمشده در شکست | `src/thesisound/services/model_runner.py:207-217` |
| `started_at` = زمان پایان | `src/thesisound/modeling.py:70-72` + `model_runner.py:171-182` |
| دور زدن بودجه | `src/thesisound/services/analysis_profile.py:149-179` |
| تشخیص جمله‌ی افتاده | `src/thesisound/services/audio_qa.py:93-115` |
| auto-accept صوت | `src/thesisound/config.py:119`؛ `services/audio_pipeline_service.py:143-146,205-208` |
| هم‌زمانی evidence | `src/thesisound/services/evidence_extractor.py:48,148-197` |
| routing/self-grading | `config/model-routing.toml` |
| جدول قیمت خالی | `config/model-pricing.toml` |
| registry دروازه‌ها | `src/thesisound/services/gates.py` |
| بای‌پس تست merge | `tests/test_document_mapper_large_inputs.py::HierarchicalRunner` |

### D. فهرست فرض‌ها

1. store فایل‌سیستمی `model-runs/` منبع حقیقت رفتار اجرا است (چون ۲۶× بیشتر از ledger داده دارد).
2. رکوردهای زیر `archive/revisions/` کار دورریخته‌اند (نه اجرای فعال).
3. `stage='test'` و `requested_model='gemini-test'` داده‌ی مصنوعی‌اند.
4. spanها/eventها از test suite‌اند (بر پایه‌ی مدت، pid، و project_idهای ناموجود).
5. اجرای `f781a5c7` مقدم بر commit `4ff91d3` است، پس سریالی‌بودن مشاهده‌شده لزوماً وضعیت HEAD نیست.
6. `.wav`ها بعداً پاک شده‌اند؛ manifest و ASR/QA بازمانده‌ی یک اجرای صوتی واقعی‌اند (چون sha256، مدت، و رونویسی فارسی واقعی دارند).

### E. پرسش‌های حل‌نشده

1. آیا concurrency پس از `4ff91d3` واقعاً کار می‌کند؟ هیچ اجرایی آن را تمرین نکرده.
2. چرا ledger فقط ۱۴ فراخوانی واقعی دارد در حالی که filesystem ۳۶۵ دارد؟ (نصب دیرتر ledger؟ مسیر متفاوت؟)
3. آیا Okian هرگز کار کرده؟ ۸/۸ شکست، عمدتاً «Internal Server Error» در ~۴۰۰ms.
4. آیا `config/model-routing copy.toml` عمدی است یا باقی‌مانده؟
5. سناریوی صوتی archive شده با سناریوی live فرق دارد — کدام revision صوت را باطل کرد و چرا؟
6. `evidence_extraction` چهار نسخه‌ی prompt دارد (۱.۰.۰–۱.۳.۰)؛ ۱.۱.۰ و ۱.۳.۰ هر دو در اجراهای واقعی دیده شدند. آیا نسخه‌های قدیمی dead code‌اند؟

---

## پاسخ به پرسش نهایی

> اگر هدف Thesisound تولید اپیزودهای فارسی دقیق، قابل‌اعتماد و شنیدنی با کمترین زمان، هزینه و دخالت دستی باشد، کدام بخش‌ها واقعاً ارزش ایجاد می‌کنند، کدام اثبات نشده‌اند و کدام باید تغییر کنند؟

**واقعاً ارزش ایجاد می‌کنند (شاهد مستقیم).**
زنجیره‌ی block → evidence → claim → turn با ID و locator دترمینیستیک، هسته‌ی محصول است و کار می‌کند: در اجرای واقعی هر turn محتوایی به شاهد واقعی وصل بود و متن فارسی حاصل، دقیق و شنیداری و منسجم از نظر اصطلاحات بود. repair لایه‌ای شاهد (تطبیق متساهل → verbatim → بازبررسی سخت) طراحی درستی است و واقعاً hallucination را می‌گیرد. cache محتوا-محور اسناد، gate registry، و امتناع سنجیده از حدس‌زدن قیمت، نشانه‌ی مهندسی بالغ‌اند. ingestion، block building، prioritization و assembly دترمینیستیک، ارزان و بی‌دردسرند.

**هنوز اثبات نشده‌اند.**
تقریباً هر ادعای کیفی. یک اجرا، یک زبان مبدأ، یک نوع فایل، یک duration، یک mode. coverage audit، claim reconciliation، glossary، verifier و reviser هیچ‌کدام شاهدی از ارزش افزوده ندارند — نه رد شده‌اند، فقط سنجیده نشده‌اند. کل مسیر OCR/فارسی اسکن‌شده، مسیر web/URL، و سناریوهای چندمنبعی و متعارض هیچ داده‌ی واقعی ندارند. tail risk، پایداری بین اجراها، و زمان بازبینی دستی اندازه‌گیری نشده‌اند. **و تا وقتی R4 و جدول قیمت اصلاح نشوند، هیچ بحث هزینه‌ای قابل حل‌وفصل نیست.**

**باید تغییر کنند.**
سه چیز خراب‌اند و باید قبل از هر بهینه‌سازی درست شوند: `document_map_merge` که برای هر کتاب no-op است و بی‌صدا thesis پارتیشن اول را به کل اثر تعمیم می‌دهد؛ تشخیص جمله‌ی افتاده در Audio QA که ریاضاً محکوم به false positive است و دروازه را بی‌اعتبار کرده؛ و نبود checkpoint پارتیشنی که یک شکست را به بازپرداخت ۲۱۵ هزار توکن تبدیل کرد. سپس سه چیز باید سخت‌تر شوند: verifier باید مدل مستقل را اجبار کند نه اینکه هشدار بدهد، بودجه‌ی تحلیل باید واقعاً بودجه باشد، و `_render` باید هر placeholder ناشناخته را خطا بدهد.

و یک نکته‌ی راهبردی: **بهینه‌سازی توکن، زمان انتظار کاربر را کم نمی‌کند.** در تنها اجرای واقعی، ۹۲٪ زمان دیواری صرف انتظار انسانی و بازیابی از شکست شد و فقط ۸٪ صرف provider. اگر «کمترین زمان» هدف است، R3 (حذف rerun) و کوتاه‌کردن دروازه‌ها بسیار بیشتر از هر بهینه‌سازی prompt اثر دارد.
