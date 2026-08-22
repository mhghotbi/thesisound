# 10x — Runbook اجرایی برای ایجنت پیاده‌ساز (موقت)

این فایل برای یک ایجنت کدنویس (Sonnet) نوشته شده که طرح [`10`](10-personal-learning-companion-development-plan.md) را **گام‌به‌گام** پیاده می‌کند. مالک هر بار فقط می‌گوید «گام N» — هیچ دستور دیگری لازم نیست. مرجع طراحی [`10b`](10b-personal-learning-companion-design.md) و مرجع فازها [`10c`](10c-personal-learning-companion-implementation.md) است؛ این فایل فقط ترتیب، مرزها، تست‌ها و نحوهٔ گزارش را تعیین می‌کند. پس از پایان همهٔ گام‌ها این فایل حذف یا آرشیو می‌شود.

---

## ۰. قواعد ثابت هر گام (ایجنت: این بخش را در هر گام دوباره بخوان)

**پیش از شروع هر گام**
1. [`07-junior-guide.md`](07-junior-guide.md) بخش «کار از روی 10x»، و در `10c` بخش `C-P` (پروتکل) را بخوان.
2. بخش‌هایی از `10b`/`10c` که در همان گام نام برده شده را بخوان — نه بیشتر.
3. **پیش‌بررسی گام قبلی** را اجرا کن (دستورش در هر گام نوشته شده). اگر قرمز بود، اول آن را گزارش کن و بدون تأیید مالک جلو نرو.
4. به مالک، **به زبان ساده و محصولی**، در ۳ تا ۶ خط بگو در این گام چه چیزی ساخته می‌شود، چه چیزی عوض نمی‌شود، و چه ریسکی دارد. سپس بپرس: «شروع کنم؟» و **تا تأیید نگرفتی کد نزن.**

**حین کار**
- فقط محدودهٔ همان گام. اگر چیزی بیرون گام لازم شد، بنویس «خارج از گام — در گزارش پایانی می‌آید» و ادامه بده.
- تغییرها افزایشی‌اند؛ کد/prompt/تست موجود را حذف نکن مگر گام صریحاً بگوید.
- هر prompt جدید = پوشهٔ نسخهٔ جدید زیر `prompts/<id>/<version>/`؛ **نسخهٔ قبلی دست نمی‌خورد**.
- validator قطعی قبل از هر خروجی مدل؛ هیچ مدل‌فراخوانی بدون `ModelRunner.run(..., validator=...)`.
- هیچ تستی را برای سبز شدن ضعیف نکن؛ اگر تست کهنه است، تغییرش را با دلیل در گزارش بنویس.
- به هیچ فایل زیر `research/` دست نزن و هیچ واژهٔ موضوعی (coloniality، dependency، …) در prompt ننویس.
- هیچ commit بدون اجازهٔ مالک.

**در پایان هر گام**
1. `uv run pytest -q` کامل (یا زیرمجموعهٔ گفته‌شده) سبز، به‌علاوهٔ تست‌های همان گام.
2. **گزارش پایانی به مالک** با این ساختار ثابت، به زبان محصولی و دقیق:
   - «چه ساختم» (۳–۶ خط، بدون اصطلاح فنی غیرضروری؛ اسم فایل‌ها در یک خط جدا)
   - «چه چیزی *عوض نشد*» (یک خط)
   - «چطور مطمئن شدم» (تست‌ها: تعداد/نام، و اگر تست قبلاً قرمزی بوده چه شد)
   - «خارج از گام دیدم» (اگر بود)
   - «آمادهٔ commit هستم؛ بگویید commit کنم یا نه.»
3. وضعیت گام را در همین فایل در جدول §۱ به «انجام‌شده» تغییر بده و تاریخ بزن.

**چک‌پوینت‌ها (گام‌های C-A … C-F)** گام‌های ویژه‌ای هستند که چیزی نمی‌سازند: کل مسیر تا آن‌جا را اجرا/تست می‌کنند، وضعیت را می‌سنجند و اگر اشکال ساختاری دیدند **پیشنهاد اصلاح** می‌دهند (نه اصلاح خودسرانه). مالک تصمیم می‌گیرد.

---

## ۱. جدول گام‌ها

| گام | فاز | عنوان | وضعیت |
|---|---|---|---|
| 0 | — | آشنایی و baseline | انجام‌شده 2026-08-19 |
| 1 | P0.5 | نویسندهٔ `persian_script_segment/1.3.0` | انجام‌شده 2026-08-19 |
| 2 | P0.5 | `ClaimRecord` در evidence pack + verifier 1.2.0 + reviser 1.1.0 | انجام‌شده 2026-08-19 |
| 3 | P0.5 | چک قطعی `unsupported_specifics` | انجام‌شده 2026-08-19 |
| 4 | P0.5 | صفحهٔ must-not-be-lost | انجام‌شده 2026-08-19 |
| C-A | ✔ | **چک‌پوینت A** — مسیر `focused_question` سالم؟ | انجام‌شده 2026-08-19 |
| 5 | P1 | مدل‌های `concepts.py` | انجام‌شده 2026-08-19 |
| 6 | P1 | Pass 0 — تشخیص فصل (دو تشخیص‌دهنده) | انجام‌شده 2026-08-19 |
| 7 | P1 | Pass 1 — document map فصل‌به‌فصل | انجام‌شده 2026-08-19 |
| 8 | P1 | Pass 2/2.5 — سلول‌های مفهومی + نرمال‌سازی | انجام‌شده 2026-08-19 |
| 9 | P1 | Pass 3 — consolidate | انجام‌شده 2026-08-19 |
| 10 | P1 | Pass 4/4.5/5 — یال‌ها، ارتقای tier، آمار | انجام‌شده 2026-08-19 |
| 11 | P1 | orchestration + کش + overlay + resume | انجام‌شده 2026-08-19 |
| 12 | P1 | CLI `concept-map` + صفحهٔ نقشه | انجام‌شده 2026-08-19 |
| C-B | ✔ | **چک‌پوینت B** — نقشهٔ یک منبع واقعی | انجام‌شده 2026-08-19 |
| 13 | P2 | استخراج ۲.۰ (+ batch، گذر دوم، پوشش، batch سلولی) | انجام‌شده 2026-08-19 |
| 14 | P2 | reconciliation 1.1.0 + merge 1.1.0 | انجام‌شده 2026-08-19 |
| 15 | P2 | planner 1.3.0 + plumbing verifier | انجام‌شده 2026-08-19 |
| 16 | P2 | glossary 1.1.0 + document_map 1.1.0 + web capture | انجام‌شده 2026-08-19 |
| 17 | P2 | re-baseline golden + CHANGELOG + docs | انجام‌شده 2026-08-19 |
| C-C | ✔ | **چک‌پوینت C** — استخراج کامل و بدون اتلاف؟ | انجام‌شده 2026-08-19 |
| 18 | P3 | میدان‌های پروژه + brief مشتق + انتخاب با بستار + برآورد هزینه | انجام‌شده 2026-08-19 |
| 19 | P3 | seeding استخراج + linkage + سطوح پوشش | انجام‌شده 2026-08-20 |
| 20 | P3 | `part_packer` | انجام‌شده 2026-08-20 |
| 21 | P3 | `segment_skeleton` + حلقهٔ plan per-part + ۵ نقطهٔ شرطی | انجام‌شده 2026-08-20 |
| 22 | P3 | script/audio per-part + گزارش + UI | انجام‌شده 2026-08-20 |
| C-D | ✔ | **چک‌پوینت D** — `source_coverage` سرتاسری روی منبع واقعی | انجام‌شده 2026-08-22 (کامل، در STATUS.md) |
| 23 | P4 | تحویل متنی | انجام‌شده 2026-08-20 |
| 24 | P5 | یکپارچه‌سازی UI (نمای گراف، overview) | انجام‌شده 2026-08-20 (نکات در STATUS.md) |
| C-E | ✔ | **چک‌پوینت E** — UI و تجربهٔ مالک | انجام‌شده 2026-08-20 (نکات در STATUS.md) |
| 25 | P6 | ارزیابی روی یک منبع کامل + cleanup | جزئی 2026-08-22 (cleanup ایمن انجام شد؛ مانع اجرای واقعی رفع شد؛ اجرای دو-فشردگی هنوز زمان‌بندی نشده، در STATUS.md) |
| C-F | ✔ | **چک‌پوینت نهایی** — Definition of Done | |

---

## ۲. گام‌ها

### گام 0 — آشنایی و baseline

**بخوان:** `10`, `10a` کامل، `10c` بخش‌های `C-P` و `C-F`، `07-junior-guide.md`.
**پیش‌بررسی:** —
**انجام بده:** هیچ کدی ننویس. `uv run pytest -q` را کامل اجرا کن و فهرست تست‌های قرمز را ثبت کن (انتظار: `tests/test_script_speaker_balance.py::test_latest_script_prompt_is_1_2_0_and_renders_position` قرمز است — این یک باگ شناخته‌شده است، `STATUS.md` «Known gaps»). `uv run thesisound doctor` را اجرا کن و نتیجه را ثبت کن.
**تست پایان:** —
**گزارش:** baseline تست‌ها (تعداد سبز/قرمز با نام)، وضعیت doctor، و یک جملهٔ تأیید که `10a A4` (قواعد) را خوانده‌ای.

---

### گام 1 — نویسندهٔ `persian_script_segment/1.3.0` (P0.5 قدم ۱)

**بخوان:** `10c` P0.5 Step 1؛ `10b` ضمیمهٔ A.1 کامل؛ `10b` B5.1 ردیف F1.
**پیش‌بررسی:** `uv run pytest tests/test_prompt_rendering.py tests/test_script_speaker_balance.py -q` (یکی قرمز است — همان که می‌خواهیم سبز شود).
**انجام بده:**
1. پوشهٔ `prompts/persian_script_segment/1.3.0/` با `contract.json`, `system.md`, `user.md` دقیقاً طبق A.1؛ بخش «Tone and dialogue style» را **عیناً** از `1.2.0/system.md` کپی کن.
2. در `services/persian_script_writer.py` متغیرهای جدید را به `variables` اضافه کن: `claims` (فعلاً `[]` — گام ۲ پرش می‌کند)، `known_concepts` (`[]`)، `part_index=1`, `part_count=1`. نسخهٔ ۱.۲.۰ و قبل نباید بشکنند (متغیر اضافه در render آن‌ها بی‌اثر است؛ تست کن).
3. تست `tests/test_script_speaker_balance.py::test_latest_script_prompt_is_1_2_0_and_renders_position` را به 1.3.0 pin کن و اسمش را به `..._is_1_3_0_...` تغییر بده؛ تست جدید `tests/prompts/test_grounding_sentences.py` که وجود این جمله‌ها را در system prompt فعال نویسنده assert می‌کند: «Never add outside knowledge», «editorial_only», «analogy», «support_status», «KNOWN_CONCEPTS».
**تست پایان:** `uv run pytest tests/test_prompt_rendering.py tests/test_script_speaker_balance.py tests/prompts -q` سبز؛ سپس `uv run pytest -q` کامل.
**گزارش:** به مالک بگو «مسیر ورود محتوای ساختگی به سناریو که در ممیزی F1 پیدا شد بسته شد؛ تست قرمز قدیمی سبز شد»، و این که لحن تغییری نکرده.

---

### گام 2 — `ClaimRecord` در evidence pack + verifier 1.2.0 + reviser 1.1.0 (P0.5 قدم ۲)

**بخوان:** `10c` P0.5 Step 2؛ `10b` B5.1 F5، B5.2 C5؛ ضمیمهٔ A.5 و A.12.
**پیش‌بررسی:** `uv run pytest tests/prompts tests/test_script_speaker_balance.py -q` سبز.
**انجام بده:**
1. `SegmentEvidencePack.claims: list[ClaimRecord] = []` در `episode.py` (پیش‌فرض خالی تا packهای قدیمی load شوند)؛ `evidence_pack_builder._build_segment` آن را از `claim_by_id` پر کند.
2. `CLAIMS_JSON` را در `user.md` نویسندهٔ 1.3.0 (همین حالا placeholder دارد) از `pack.claims` پر کن.
3. `prompts/script_verifier/1.2.0/` طبق A.5؛ `prompts/script_reviser/1.1.0/` = 1.0.0 + بلوک `<CLAIMS_JSON>` در user؛ سرویس‌های `script_verifier.py` و `script_reviser.py` متغیر `claims` (و برای verifier `plan_must_include=[]`, `known_concepts=[]` فعلاً) را بفرستند.
**تست پایان:** تست pack (claims پر می‌شود و با `claim_ids` هم‌خوان است)؛ render سه prompt؛ `uv run pytest -q` کامل.
**گزارش:** «نویسنده و بازبین حالا وضعیت پشتوانهٔ هر ادعا (قطعی/مورد اختلاف/نامطمئن) و قیدهایش را می‌بینند؛ پیش از این فقط شناسهٔ ادعا را می‌دیدند.»

---

### گام 3 — چک قطعی `unsupported_specifics` (P0.5 قدم ۳)

**بخوان:** `10c` P0.5 Step 3؛ `10b` B5.2 C1 (بند deterministic).
**پیش‌بررسی:** `uv run pytest tests/test_script_checks*.py -q` سبز (نام فایل را با `ls tests | grep script_check` پیدا کن).
**انجام بده:** در `services/script_checks.py` issue type جدید `unsupported_specifics` (به `script.py` Literal اضافه کن)، severity `medium`؛ الگوریتم طبق 10c (اعداد ≥ ۲ رقم، سال چهاررقمی، واژهٔ لاتین با حرف بزرگ، span داخل «…» یا "…")؛ ارقام فارسی به ASCII نرمال شوند؛ مقایسه با اجتماع excerptهای استنادشدهٔ همان turn + بلاک‌های original/context همان pack، پس از همان نرمال‌سازی موجود. turnهای `editorial_only` معاف.
**تست پایان:** فیکسچر مثبت (سالی که در pack نیست → issue) و منفی (عددی که در excerpt هست → بدون issue، عدد فارسی هم)؛ `uv run pytest -q`.
**گزارش:** «اگر سناریو عدد/تاریخ/نامی بگوید که در منبع نیست، حالا به‌صورت خودکار علامت می‌خورد و برای اصلاح می‌رود.»

---

### گام 4 — صفحهٔ must-not-be-lost (P0.5 قدم ۴)

**بخوان:** `10c` P0.5 Step 4؛ `10b` B5.1 F2.
**پیش‌بررسی:** `uv run pytest -q -k "episode and (route or page or template)"` سبز (هرچه هست).
**انجام بده:** در صفحهٔ episode (`web/templates/projects/episode.html` + read model مربوط) بخش «نکاتی که نباید گم شوند» از `episode/must-not-be-lost-review.json`: متن نکته، claimهای نامزد، `used_in_plan`؛ `unused_count` در سربرگ. فقط نمایش؛ هیچ منطق جدید.
**تست پایان:** تست route/template با review فیکسچر؛ `uv run pytest -q`.
**گزارش:** «نکات must-not-be-lost که سیستم از قبل محاسبه می‌کرد ولی جایی نشان نمی‌داد، حالا روی صفحهٔ اپیزود دیده می‌شوند.»

---

### گام C-A — چک‌پوینت A: مسیر `focused_question` هنوز سالم است؟

**انجام بده:** (۱) `uv run pytest -q` کامل؛ (۲) `uv run thesisound readiness` و `uv run thesisound eval` (benchmarks/eval) را اجرا کن و با baseline گام ۰ مقایسه کن؛ (۳) فهرست فایل‌های تغییرکرده از گام ۱ تا ۴ (`git diff --stat <baseline>`) را بررسی کن که فقط در محدودهٔ P0.5 باشند؛ (۴) `prompts/README.md` نسخه‌های جدید را فهرست کرده باشد و `STATUS.md` «Known gaps» اصلاح شده باشد (مورد F1 و F5 حذف/به‌روز).
**گزارش:** یک جدول ساده: چه چیزی بهتر شد (به زبان محصول)، آیا چیزی بدتر شد، آیا اصلاحی پیشنهاد می‌دهی. اگر اصلاح لازم است، پیشنهاد بده و منتظر تصمیم مالک بمان.

---

### گام 5 — مدل‌های `concepts.py` (P1 قدم ۱)

**بخوان:** `10c` P1 Step 1؛ `10b` B1.2، B1.3 (همهٔ فیلدها)، B1.5 (`LessonPart` را هنوز نساز).
**پیش‌بررسی:** `uv run pytest -q` سبز (به‌جز آنچه در C-A پذیرفته شد).
**انجام بده:** `src/thesisound/concepts.py` با Pydantic v2: `SourceChapter`, `ConceptCell`, `ConceptEdge`, `ConceptMapStatistics`, `SourceConceptMap`, `ConceptMapOverlay` و مدل‌های draft. validatorهای مدل: `cell_key` الگوی `ch\d{2}-c\d{3}`، tier ∈ {1,2,3}، `block_ids` ≥ ۱، weight/confidence در [0,1]. هیچ سرویس/prompt در این گام.
**تست پایان:** `tests/concepts/test_models.py` (round-trip JSON، خطای validation برای هر قید)؛ `uv run pytest -q`.
**گزارش:** «ساختار داده‌ای «نقشهٔ مفهومی» (فصل، سلول، یال، آمار، اصلاحات مالک) تعریف شد؛ هنوز چیزی ساخته نمی‌شود.»

---

### Step 6 — Pass 0: chapter detection (P1 step 2)

**Read:** `10c` P1 Step 2; `10b` B2 Pass 0, B1.2.
**Pre-check:** `uv run pytest tests/concepts -q` green.
**Do:** In `services/concept_map_builder.py` (only this, for now), add a pure function `detect_chapters(blocks, parsed_document) -> list[SourceChapter]` with two detectors (H from `heading_path`, T from the document's TOC — check what `ParsedDocument` exposes about heading/TOC; if there's no explicit TOC, fall back to the parsed document's top-level headings and note this in the docstring) plus the reconcile rule (20% / 40% / 2%) and `detection_agreement`. Provisional minutes = Σ tokens / 300.
**Final test:** `tests/concepts/test_detect_chapters.py` with the 5 fixtures from `10c` (agreed, toc_only, EPUB nav, disagreed, single); `uv run pytest -q`.
**Report:** "The book is split into chapters using two independent methods; if the two methods disagree, it gets flagged and the table of contents is used as the source of truth — without asking you to confirm."

---

### گام 7 — Pass 1: document map فصل‌به‌فصل (P1 قدم ۳)

**بخوان:** `10c` P1 Step 3؛ `services/document_mapper.py` (`_partition_blocks`, `map_document`).
**پیش‌بررسی:** `uv run pytest tests/test_document_mapper_large_inputs.py tests/test_document_map_part_cache.py tests/test_conditional_document_map.py -q` سبز.
**انجام بده:** آرگومان اختیاری `partitions: list[list[SourceDocumentBlock]] | None` به `map_document`؛ وقتی داده شد `_partition_blocks` دور زده می‌شود، هر partition اگر از `maximum_input_characters` بزرگ‌تر بود با منطق موجود زیرتقسیم می‌شود؛ merge بدون تغییر. مسیر فعلی (بدون آرگومان) **بایت‌به‌بایت** همان رفتار.
**تست پایان:** golden: یک منبع با partition حجمی و partition فصلی → پوشش بلاک یکسان؛ تست‌های قبلی mapper سبز؛ `uv run pytest -q`.
**گزارش:** «نقشهٔ ساختاری هر فصل جدا ساخته می‌شود (به‌جای تکه‌های حجمی)؛ برای پروژه‌های فعلی هیچ تغییری.»

---

### گام 8 — Pass 2/2.5: سلول‌های مفهومی + نرمال‌سازی (P1 قدم ۴ و ۵)

**بخوان:** `10c` P1 Step 4 و 5؛ `10b` ضمیمهٔ A.8 کامل؛ B1.3 تعریف سلول؛ B1.4 قید توزیع.
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** `prompts/concept_cells/1.0.0/` طبق A.8؛ در `concept_map_builder.py`: `build_chapter_awareness(...)`, `chapter_budget(sections)`, `_validate_cells_draft(...)` با همهٔ قواعد 10c (ID ناشناخته، سلول بی‌بلاک، پوشش section، برچسب ممنوع/بودار — فهرست فارسی و انگلیسی در `concepts.py`، Jaccard ≥ ۰٫۸۵، سقف `budget × 1.5`، توزیع tier)، تخصیص `cell_key`، و `normalise_cells(...)` (Pass 2.5). فراخوانی مدل از طریق `ModelRunner.run` با `validator`. رفتار «آخرین attempt»: auto-merge تکراری‌ها و پذیرش توزیع با پرچم.
**تست پایان:** `tests/concepts/test_cells_validator.py` (هر قاعده یک تست)، `test_normalise_cells.py`، `tests/concepts/test_prompt_render.py` (render با فیکسچر؛ placeholder گم‌شده → خطا)؛ `uv run pytest -q`.
**گزارش:** «هر فصل به «سلول‌های مفهومی» شکسته می‌شود: تعریف، تمایز، استدلال، موضع، اعتراض/پاسخ، مثال — هر کدام با سطح اهمیت ۱ تا ۳ و پیوند به متن منبع؛ قواعد سخت‌گیرانه جلوی برچسب‌های بی‌معنا و تکرار را می‌گیرند.»

---

### گام 9 — Pass 3: consolidate (P1 قدم ۶)

**بخوان:** `10c` P1 Step 6؛ ضمیمهٔ A.9.
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** `prompts/concept_cells_consolidate/1.0.0/`؛ `consolidate_chapter(cells, budget)` فقط وقتی تعداد > بودجه؛ validator (کلیدها موجود، merge_into یک keep، هیچ section بدون سلول، تعداد ≤ بودجه)؛ اعمال قطعی actionها (اجتماع بلاک‌ها/sectionها، tier کمتر).
**تست پایان:** `test_consolidate_validator.py`؛ `uv run pytest -q`.
**گزارش:** «اگر فصلی بیش از حد سلول داشت، سلول‌های هم‌پوشان ادغام می‌شوند بدون این‌که بخشی از کتاب بی‌پوشش بماند.»

---

### گام 10 — Pass 4/4.5/5: یال‌ها، ارتقای tier، آمار (P1 قدم ۷–۹)

**بخوان:** `10c` P1 Step 7, 8, 9؛ ضمیمهٔ A.10؛ `10b` B1.3 (ارتقای tier).
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** `prompts/concept_edges/1.0.0/`؛ `build_edges_for_chapter(...)`, `build_cross_chapter_edges(a, b, cap)` (پنجرهٔ ۲، **همیشه** اجرا می‌شود)؛ `_validate_edges(...)` با تشخیص دور (DFS روی prerequisite/depends_on/extends؛ attempt ۱–۲ خطا، attempt آخر حذف کم‌وزن‌ترین یال هر دور + هشدار)، dedup، clamp، سقف با نگه‌داشتن پروزن‌ترها؛ `promote_tiers(cells, edges, sections)`؛ `compute_statistics(map)` با `needs_review` و شرایط critical.
**تست پایان:** `test_edges_validator.py` (دور → تعمیر + هشدار؛ سقف؛ dedup)، `test_tier_promotion.py`، `test_statistics.py`؛ `uv run pytest -q`.
**گزارش:** «روابط بین مفاهیم (پیش‌نیاز، تمایز، اعتراض/پاسخ، …) ساخته و از نظر منطقی چک می‌شوند (بدون حلقهٔ پیش‌نیازی)؛ مفاهیمی که بقیه به آن‌ها وابسته‌اند خودکار «مهم‌تر» می‌شوند.»

---

### گام 11 — orchestration + کش + overlay + resume (P1 قدم ۱۰)

**بخوان:** `10c` P1 Step 10؛ `10b` B1.3 (کش و overlay)؛ `services/document_map_cache.py` به‌عنوان الگو.
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** `ConceptMapBuilder.build(...)` حلقهٔ فصل‌ها با checkpoint (`sources/<sid>/concept-map.partial.json`)؛ `services/concept_map_cache.py` (source-level + per-chapter sub-entries؛ `CONCEPT_MAP_BUILDER_VERSION`؛ `emit_cache_lookup`)؛ `services/concept_map_overlay.py` (`apply`, `record_edit`)؛ hook در `source_analysis_service` پشت یک setting (پیش‌فرض خاموش تا گام ۱۸).
**تست پایان:** `test_cache_overlay.py` (round-trip، invalidation نسخه، sub-entry فصل)، `test_builder_resume.py` (قطع بعد از فصل ۲ و ادامه)؛ `uv run pytest -q`.
**گزارش:** «نقشهٔ هر کتاب یک‌بار ساخته و ذخیره می‌شود؛ اگر وسط کار قطع شود از همان فصل ادامه می‌دهد؛ اصلاحات شما روی نقشه هیچ‌وقت با بازسازی پاک نمی‌شود.»

---

### گام 12 — CLI `concept-map` + صفحهٔ نقشه (P1 قدم ۱۱ و ۱۲)

**بخوان:** `10c` P1 Step 11, 12؛ `10b` B1.8 (فقط برآورد توکن، نه قیمت).
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** فرمان `thesisound concept-map <path> [--chapters] [--rebuild] [--json]` (در `cli.py` یا ماژول CLI جدید کنار بقیه)؛ `services/cost_estimate.py` فعلاً فقط `estimate_tokens(...)`؛ route `GET /projects/{pid}/sources/{sid}/concept-map` + template (جدول‌ها؛ بدون کتابخانهٔ گراف) + فرم‌های overlay (افزودن/حذف سلول و یال، override tier).
**تست پایان:** CLI smoke (با مدل fake موجود در تست‌ها)، تست route؛ `uv run pytest -q`.
**گزارش:** «می‌توانید نقشهٔ مفهومی یک فایل را از خط فرمان بسازید و در صفحهٔ پروژه ببینید و اصلاح کنید.»

---

### گام C-B — چک‌پوینت B: نقشهٔ یک منبع واقعی

**انجام بده:** از مالک یک فایل منبع واقعی (PDF/EPUB علوم انسانی) بخواه؛ با کلید واقعی `thesisound concept-map <file>` را اجرا کن؛ آمار (تعداد فصل و `detection_agreement`، سلول در هر tier، ارتقاها، یال‌ها در هر نوع، یتیم‌ها، `needs_review`) و هزینهٔ هر گذر از `thesisound observability <project>` را گزارش کن؛ ۱۰ سلول تصادفی را با متن منبع مقایسه کن (برچسب درست؟ بلاک درست؟ tier منطقی؟). `uv run pytest -q` کامل.
**گزارش:** کیفیت نقشه به زبان ساده + عدد هزینه + اگر الگوی خطایی دیدی (مثلاً برچسب‌های بودار، فصل‌بندی غلط) پیشنهاد اصلاح بده و منتظر تصمیم مالک بمان. **ادامه به گام ۱۳ فقط با تأیید مالک.**

---

### گام 13 — استخراج ۲.۰ (P2 قدم ۱ و ۲)

**بخوان:** `10c` P2 (مقدمه + Step 1, 2)؛ `10b` B5.2 C2؛ ضمیمهٔ A.2 کامل؛ `10b` B2 (batch سلولی).
**پیش‌بررسی:** `uv run pytest -q` سبز؛ تأیید C-B.
**انجام بده:** مدل‌ها طبق 10c Step 1 (aux lists حذف؛ `ClaimType` گسترش؛ فیلدهای جدید)؛ `prompts/evidence_extraction/2.0.0/` و `evidence_extraction_batch/2.0.0/`؛ validator `_validate_claim_type_fields`؛ `_second_pass_for_block` (پسوند user طبق A.2)؛ `excerpt_char_coverage`؛ سقف ۱۲ برای `source_coverage`؛ batch سلولی در `plan_evidence_extraction` (فعلاً تابع آماده، فعال‌سازی در گام ۱۹)؛ مسیرهای aux در `claim_reconciler`/planner/`MustNotBeLostReview` را به claim-level ببر (صفحهٔ گام ۴ حالا claimهای `must_not_be_lost` را نشان می‌دهد). **بدون migration:** بارگذاری artifact پیش از ۲.۰ خطای روشن «regenerate» بدهد.
**تست پایان:** تست‌های validator ۲.۰، گذر دوم، متریک پوشش، batch سلولی + fallback؛ تست‌های استخراج قبلی به‌روز (فیکسچرها را به ۲.۰ ببر و در `tests/golden/CHANGELOG.md` بنویس)؛ `uv run pytest -q`.
**گزارش:** «از این پس هر تعریف، تمایز، مثال، اعتراض و پاسخ هم مثل هر ادعای دیگر با نقل‌قول دقیق از منبع ذخیره و ممیزی می‌شود؛ هیچ نکتهٔ «نباید گم شود» دیگر بدون حساب نمی‌ماند؛ بلاک‌های پرمحتوا دو بار خوانده می‌شوند تا چیزی جا نماند.»

---

### گام 14 — reconciliation 1.1.0 + merge 1.1.0 (P2 قدم ۳)

**بخوان:** `10c` P2 Step 3؛ ضمیمهٔ A.3.
**پیش‌بررسی:** `uv run pytest -q -k "reconcil"` سبز.
**انجام بده:** دو prompt نسخهٔ جدید؛ pre-filter قطعی ضد merge بین `claim_type`ها؛ `ClaimMergeGroup.canonical_claim_id`؛ انتقال `must_not_be_lost`/`term`/`contrast` در ledger.
**تست پایان:** تست نگهبان نوع، تست canonical؛ `uv run pytest -q`.
**گزارش:** «هنگام یکی‌کردن ادعاهای مشابه، تعریف با موضع یا اعتراض با پاسخ قاطی نمی‌شود و قیدها از دست نمی‌روند.»

---

### گام 15 — planner 1.3.0 + plumbing verifier (P2 قدم ۴ و ۵)

**بخوان:** `10c` P2 Step 4, 5؛ ضمیمهٔ A.4 (با `SEGMENT_SKELETON_JSON`)؛ `10b` B1.6 فقط برای فهم — اسکلت در گام ۲۱ ساخته می‌شود.
**پیش‌بررسی:** `uv run pytest -q -k "episode_plan or planner"` سبز.
**انجام بده:** `prompts/episode_plan/1.3.0/`؛ متغیرهای `part` (پیش‌فرض `{"part_index":1,"part_count":1,"part_target_minutes":<target>,"cell_labels":[]}`)، `segment_skeleton` (`[]`)، `known_concepts` (`[]`)؛ validator: یکپارچگی must_not_be_lost (همهٔ claimهای پرچم‌دار یا در segment یا در omitted با دلیل → وگرنه `integrity_breach`)، و **بررسی هویت اسکلت** وقتی غیرخالی است (ترتیب، claim_ids، speaker_dynamic، دقیقه)؛ `part_index` روی `EpisodeSegment` (پیش‌فرض ۱). verifier: `plan_must_include` از plan پر شود.
**تست پایان:** فیکسچر must_not_be_lost حذف‌شدهٔ بی‌دلیل → رد؛ فیکسچر اسکلت با انحراف → رد؛ `uv run pytest -q`.
**گزارش:** «طرح اپیزود دیگر نمی‌تواند نکتهٔ حیاتی را بی‌صدا حذف کند؛ و زیرساخت «طرح با اسکلت ثابت» آماده شد (در گام ۲۱ فعال می‌شود).»

---

### گام 16 — glossary 1.1.0 + document_map 1.1.0 + web capture (P2 قدم ۶ و ۷)

**بخوان:** `10c` P2 Step 6, 7؛ ضمیمهٔ A.6، A.7؛ `10b` B5.2 C6، C8، C9.
**پیش‌بررسی:** `uv run pytest -q -k "glossary or document_map or capture"` سبز.
**انجام بده:** seed قطعی glossary از سلول‌ها (وقتی نقشه هست) و claimهای `definition`؛ `needs_model` جدید؛ `prompts/glossary/1.1.0/`؛ `prompts/document_map/1.1.0/` + validator `key_concepts` (حذف موارد غایب در attempt آخر + هشدار)؛ در web capture ذخیرهٔ fetch خام trafilatura کنار خروجی مدل + `capture_divergence` (> ۲۰٪).
**تست پایان:** glossary روی فیکسچر فارسی غیرخالی؛ validator key_concepts؛ divergence؛ `uv run pytest -q`.
**گزارش:** «واژه‌نامه برای منابع فارسی هم ساخته می‌شود؛ مفاهیم کلیدی نقشه باید عیناً در متن باشند؛ برای منابع وب، اگر متن گرفته‌شده با صفحهٔ اصلی خیلی فرق داشت علامت می‌خورد.»

---

### گام 17 — re-baseline golden + CHANGELOG + docs (P2 قدم ۸)

**بخوان:** `10c` P2 Step 8 و «Tests»؛ `prompts/README.md`؛ یادداشت‌های «بازنگری ۲۰۲۶-۰۸-۱۹» در `docs/02-pipeline/03,05,06`.
**پیش‌بررسی:** `uv run pytest -q` سبز.
**انجام بده:** golden فیکسچرهای `focused_question` را با استخراج ۲.۰ دوباره تولید کن؛ هر تفاوت را در `tests/golden/CHANGELOG.md` یک خط توضیح بده (چرا تغییر، آیا بهتر/بدتر/خنثی)؛ `prompts/README.md` نسخه‌های جدید؛ یادداشت‌های docs را از «برنامه‌ریزی‌شده» به «پیاده‌شده در گام ۱۳–۱۶» ببر؛ `STATUS.md` فاز P2 → done.
**تست پایان:** `uv run pytest -q`؛ `uv run thesisound eval`.
**گزارش:** خلاصهٔ CHANGELOG به زبان ساده: چند ادعا بیشتر/کمتر، چه نوع‌هایی اضافه شد، آیا جایی افت دیده شد.

---

### گام C-C — چک‌پوینت C: استخراج کامل و بدون اتلاف؟

**انجام بده:** روی همان منبع C-B، استخراج ۲.۰ را برای **دو فصل** اجرا کن (با کلید واقعی)؛ گزارش: تعداد claim در هر نوع، نسبت `must_not_be_lost`، میانگین `excerpt_char_coverage`، تعداد گذر دوم، بلاک‌های `thin_extraction`؛ ۱۵ claim تصادفی (از جمله ۵ تعریف/تمایز/اعتراض) را با منبع مقایسه کن (excerpt درست؟ نوع درست؟ قید حفظ شده؟). هزینهٔ دو فصل از ledger. `uv run pytest -q`.
**گزارش:** کیفیت استخراج به زبان ساده + هزینه + پیشنهاد اصلاح اگر الگویی دیدی. **ادامه فقط با تأیید مالک.**

---

### گام 18 — میدان‌های پروژه + brief مشتق + انتخاب با بستار + برآورد هزینه (P3 قدم ۱–۳)

**بخوان:** `10c` P3 Step 1, 2, 3؛ `10b` B1.1، B1.4، B1.8.
**پیش‌بررسی:** `uv run pytest -q` سبز؛ تأیید C-C.
**انجام بده:** میدان‌های اختیاری `Project` و `ResearchBrief.cell_keys`؛ `build_source_coverage_brief(...)` (بدون مدل)؛ `select_cells(...)` با فیلتر tier + **بستار پیش‌نیاز** (BFS معکوس روی `prerequisite`، سقف ۲۵، cycle-safe، `in_scope_reason`)؛ `cost_estimate.estimate(...)` با ضرایب اولیهٔ B1.8 و قیمت از `config/model-pricing.toml` اگر بود وگرنه «unknown — tokens only». فرم ساخت پروژه فعلاً دست نخورده (گام ۲۲).
**تست پایان:** تست brief مشتق؛ تست بستار (cycle، سقف، برچسب دلیل)؛ تست برآورد؛ `uv run pytest -q`.
**گزارش:** «پروژه می‌تواند «این منبع را کامل یاد بده» را با دامنه، فشردگی و طول اپیزود بگیرد؛ در حالت فشرده، پیش‌نیازهای مفاهیم اصلی هم خودکار می‌آیند تا درس ناقص نماند؛ هزینهٔ تقریبی پیش از اجرا محاسبه می‌شود.»

---

### گام 19 — seeding استخراج + linkage + سطوح پوشش (P3 قدم ۴ و ۵)

**بخوان:** `10c` P3 Step 4, 5؛ `10b` B2 (استخراج تنبل، batch سلولی).
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** `plan_evidence_extraction` با `seed_cells` و `force_depth="extended"`؛ فعال‌سازی batch سلولی (گام ۱۳)؛ `link_claims_to_cells(...)`؛ محاسبهٔ سطوح `extracted / planned / spoken` (تابع خالص روی ledger + plan + script).
**تست پایان:** تست seeding و گروه‌بندی؛ تست linkage (claim با چند سلول → اولین در ترتیب کتاب)؛ تست سطوح؛ `uv run pytest -q`.
**گزارش:** «شواهد فقط برای مفاهیمِ در دامنه استخراج می‌شوند (مفهوم‌به‌مفهوم)، و برای هر مفهوم معلوم است آیا شاهد دارد، در طرح آمده، و در درس گفته شده.»

---

### گام 20 — `part_packer` (P3 قدم ۶)

**بخوان:** `10c` P3 Step 6 (ثابت‌ها و الگوریتم)؛ `10b` B1.5.
**پیش‌بررسی:** `uv run pytest tests/concepts -q` سبز.
**انجام بده:** `services/part_packer.py` دقیقاً طبق شبه‌کد؛ ثابت‌ها در یک جا با یادداشت تنظیم KMS؛ `LessonPart` در `concepts.py`؛ `graph_backed` و پرچم‌ها.
**تست پایان:** `test_part_packer.py`: قاعدهٔ پرکردن [۰٫۸، ۱٫۰]، ترجیح مرز، استثنای بخش آخر، آمادگی، سلول oversize، `graph_backed`، قطعی بودن (دو بار اجرا = یک خروجی)، «بخش غیرآخر کوتاه‌تر از ۰٫۸ هرگز»؛ `uv run pytest -q`.
**گزارش:** «مفاهیم به اپیزودهایی به طول خواسته‌شده چیده می‌شوند — نزدیک به سقف، منسجم، با رعایت پیش‌نیازها و ترتیب کتاب؛ فقط اپیزود آخر می‌تواند کوتاه باشد.»

---

### گام 21 — `segment_skeleton` + حلقهٔ plan per-part + ۵ نقطهٔ شرطی (P3 قدم ۷، ۸، ۱۰)

**بخوان:** `10c` P3 Step 7, 8, 10؛ `10b` B1.6، B2 جدول نقاط شرطی.
**پیش‌بررسی:** `uv run pytest -q -k "packer or planner"` سبز.
**انجام بده:** `services/segment_skeleton.py` (یک سلول = یک segment، dynamic از kind، recap برای ≥ ۳ segment، prerequisite_claim_ids)؛ `EpisodePlan.parts`؛ حلقهٔ `EpisodePlanningRunService` روی بخش‌ها با planner 1.3.0 + اسکلت + re-pack هنگام سرریز ۱٫۲۵×؛ پنج `if lesson_intent == "source_coverage"` در جاهای نام‌برده — **بدون بازسازی کد اطراف**.
**تست پایان:** تست اسکلت؛ تست حلقه با re-pack؛ پنج جفت تست intent-off/on؛ `uv run pytest -q`.
**گزارش:** «ساختار هر اپیزود (کدام مفهوم، کدام ادعا، چه ترتیبی) قطعی و از روی نقشه ساخته می‌شود؛ مدل فقط روایت را می‌نویسد و نمی‌تواند ساختار را عوض کند؛ مسیر «پرسش مشخص» بدون تغییر.»

---

### گام 22 — script/audio per-part + گزارش + UI (P3 قدم ۹، ۱۱، ۱۲)

**بخوان:** `10c` P3 Step 9, 11, 12؛ `10b` B1.7.
**پیش‌بررسی:** `uv run pytest -q` سبز.
**انجام بده:** حلقهٔ بخش‌ها در `ScriptBuildRun` و `AudioBuildRun` (artifactها زیر `script/parts/<n>/`، `audio/parts/<n>/`)؛ `services/lesson_report.py` + `episode/report.json` + صفحه؛ فرم ساخت پروژه با میدان‌های جدید و برآورد هزینه؛ فهرست بخش‌ها در صفحات script/audio.
**تست پایان:** فیکسچر دو بخشی تا verification؛ تست گزارش؛ تست route فرم؛ `uv run pytest -q`.
**گزارش:** «هر اپیزود جدا نوشته، بازبینی و صداگذاری می‌شود؛ در پایان گزارشی می‌گیرید: کدام مفاهیم گفته شد، کدام با فشردگی کنار رفت، کدام پوشش نگرفت، و هزینهٔ تخمینی در برابر واقعی.»

---

### گام C-D — چک‌پوینت D: `source_coverage` سرتاسری روی منبع واقعی

**انجام بده:** روی منبع C-B، یک پروژهٔ `source_coverage` با `standard` / ۲۰ دقیقه / `audio` اجرا کن (با کلید واقعی؛ اگر TTS پرهزینه است با تأیید مالک فقط script)؛ گزارش: تعداد بخش‌ها و دقیقهٔ هر کدام در برابر هدف، `graph_backed`، سلول‌های پوشش‌نگرفته و دلایل، claimهای `must_not_be_lost` گفته‌شده، نتایج verifier، هزینهٔ تخمینی در برابر ledger؛ دو بخش را با منبع مقایسه کن (کامل؟ دقیق؟ چیزی ساختگی؟). `uv run pytest -q`.
**گزارش:** کیفیت درس‌ها به زبان ساده، عددها، پیشنهاد اصلاح ثابت‌ها (FILL_MIN، توزیع tier، ضرایب هزینه) اگر لازم بود. **ادامه فقط با تأیید مالک.**

---

### گام 23 — تحویل متنی (P4)

**بخوان:** `10c` P4؛ `10b` B4؛ ضمیمهٔ A.11.
**پیش‌بررسی:** `uv run pytest -q` سبز؛ تأیید C-D.
**انجام بده:** `ProseLessonDraft` + validator؛ `prompts/persian_lesson_prose/1.0.0/`؛ سوئیچ speaker-checks؛ گذار `SCRIPT_VERIFIED → COMPLETE` برای `delivery == text`؛ صفحهٔ `/projects/{id}/lesson/{part}` + export Markdown با پانوشت شاهد؛ `both`.
**تست پایان:** validator؛ render؛ گذار؛ export؛ پروژهٔ `text` بدون artifact صوتی کامل می‌شود؛ `uv run pytest -q`.
**گزارش:** «هر اپیزود را می‌توان به‌جای صوت، به‌صورت یک درس نوشتاری خواند — با همان سخت‌گیری روی شواهد.»

---

### گام 24 — یکپارچه‌سازی UI (P5)

**بخوان:** `10c` P5؛ `docs/05-ui-redesign/02`, `03` (زبان محصول)؛ `DESIGN.md`.
**پیش‌بررسی:** `uv run pytest -q` سبز.
**انجام بده:** نمای گراف 2D روی صفحهٔ نقشه (Cytoscape + dagre **vendored** در `static/`، بدون CDN) با overlay پوشش؛ overview پروژه با نیت/دامنه/فشردگی/هدف/بخش‌ها/هزینه؛ یک حالت UI؛ جزئیات اپراتور پشت «جزئیات فنی».
**تست پایان:** تست route/templateها؛ بررسی دستی در مرورگر (screenshot در گزارش)؛ `uv run pytest -q`.
**گزارش:** «از بارگذاری منبع تا گزارش پایانی همه در صفحات پروژه است؛ نقشهٔ مفاهیم با رنگ پوشش دیده می‌شود.»

---

### گام C-E — چک‌پوینت E: UI و تجربهٔ مالک

**انجام بده:** مسیر کامل را در مرورگر با مالک مرور کن (یا screenshotهای هر صفحه)؛ فهرست اصطکاک‌ها و ناهماهنگی با واژگان `05-ui-redesign/03`؛ `uv run pytest -q`.
**گزارش:** پیشنهادهای UI (کوچک/بزرگ) و منتظر تصمیم مالک.

---

### گام 25 — ارزیابی روی یک منبع کامل + cleanup (P6)

**بخوان:** `10c` P6 و `C-D` (Definition of Done)؛ `10c` C-R.
**پیش‌بررسی:** `uv run pytest -q` سبز.
**انجام بده:** اجرای کامل یک منبع در دو فشردگی؛ جدول اندازه‌ها طبق P6 (هزینه در برابر برآورد و بازتنظیم ضرایب، دقیقهٔ بخش‌ها، `graph_backed`، پوشش‌نگرفته، thin_extraction، ارتقاها، بستار، نرخ توافق فصل‌بندی، نتایج verifier)؛ سپس cleanup طبق P6 (حذف `subquestions` مرده، جمع کردن کران‌های مدت، به‌روزرسانی `README.md`/`STATUS.md`/SOP، ساده‌سازی Simple/Operator فقط با شواهد).
**تست پایان:** `uv run pytest -q`؛ `uv run thesisound eval`؛ `uv run thesisound readiness`.
**گزارش:** جدول اندازه‌ها + آنچه تمیز شد + چه چیزی به OQ-011/012 برمی‌گردد.

---

### گام C-F — چک‌پوینت نهایی: Definition of Done

**انجام بده:** هر ۸ بند `10c` C-D را یکی‌یکی با شاهد (فایل/تست/اجرا) تیک بزن؛ هفت ریسک C-R را با وضعیت واقعی به‌روز کن؛ `STATUS.md` را نهایی کن؛ پیشنهاد بده این فایل 10x آرشیو شود.
**گزارش:** چک‌لیست DoD + ریسک‌های باقی‌مانده به زبان ساده.
