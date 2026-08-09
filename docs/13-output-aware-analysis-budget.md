# 13 — بودجه تحلیل وابسته به خروجی

## مسئله

تحلیل یک منبع برای پادکست ۵ دقیقه‌ای نباید همان هزینه و همان عمق تحلیل پادکست ۶۰ دقیقه‌ای را داشته باشد. بااین‌حال، اگر block‌بندی و locatorها نیز وابسته به مدت خروجی ساخته شوند، قابلیت استفاده مجدد، ممیزی و تغییر مدت در ادامه از بین می‌رود.

تصمیم معماری Thesisound این است:

> substrate سند یک‌بار و مستقل از خروجی ساخته می‌شود؛ breadth و depth استخراج شواهد بر اساس خروجی درخواستی تعیین می‌شود.

بنابراین پاسخ «یک بار همه‌چیز را کامل استخراج کنیم و بعد انتخاب کنیم» نیست. فقط لایه‌های کم‌هزینه و lossless تا حد ممکن کامل ساخته می‌شوند. deep evidence extraction به‌اندازه نیاز خروجی انجام می‌شود.

---

## سه لایه تحلیل

### ۱. Source substrate مستقل از خروجی

این بخش برای پادکست ۵ و ۶۰ دقیقه‌ای یکسان است:

- parse و normalization؛
- heading و reading order؛
- semantic blockها؛
- locator؛
- source block key؛
- hash و provenance.

این لایه نباید به مدت، لحن یا mode وابسته باشد. تغییر خروجی نباید باعث تغییر block ID یا locator شود.

### ۲. Document Map سبک روی کل محدوده

Document Map باید تصویری کلی از کل منبع یا محدوده انتخاب‌شده بسازد:

- sectionها؛
- function هر section؛
- key conceptها؛
- dependencyها؛
- بخش‌های ضروری برای فهم کلی؛
- objection و response؛
- working thesis.

این مرحله نسبت به استخراج claim برای تک‌تک blockها ارزان‌تر است و برای تصمیم‌گیری درباره اینکه کجا باید توکن بیشتری مصرف شود لازم است.

برای کتاب کامل، این map در آینده باید سلسله‌مراتبی باشد:

```text
book map
  -> chapter map
  -> section map
```

نسخه فعلی برای یک فصل یا سند محدود طراحی شده است.

### ۳. Evidence extraction وابسته به خروجی

پس از Document Map، از `ResearchBrief` یک `AnalysisProfile` ساخته می‌شود. این profile تعیین می‌کند:

- چه درصدی از tokenهای محتوای قابل‌تحلیل منبع (بدون یادداشت‌ها، پانویس‌ها و بخش‌های note-like) وارد evidence extraction شود؛
- سقف token ورودی extraction چقدر باشد؛
- حداکثر چند claim از هر block استخراج شود؛
- چند block همسایه برای فهم context فرستاده شود؛
- exampleها استخراج شوند یا نه؛
- objection و response در budget قرار بگیرند یا نه.

عوامل تعیین‌کننده فقط مدت نیستند:

1. `target_duration_minutes`؛
2. `prior_knowledge` مخاطب؛
3. modeهای explanatory، critical، comparative و debate؛
4. اندازه و پیچیدگی corpus؛
5. sectionهای ضروری مشخص‌شده در Document Map؛
6. هم‌پوشانی section با سؤال مرکزی و scope.

مدت عامل اصلی است، اما تنها عامل نیست.

---

## profileهای اولیه

این اعداد default مهندسی‌اند، نه حقیقت نهایی محصول. پس از benchmark روی منابع واقعی باید تنظیم شوند.

| مدت | tier | هدف پوشش tokenهای محتوای قابل‌تحلیل | سقف claim در block | context همسایه |
|---|---|---:|---:|---:|
| ۵ تا ۱۰ دقیقه | `brief` | ۳۵٪ | ۲ | ۰ |
| ۱۱ تا ۲۵ دقیقه | `standard` | ۶۰٪ | ۳ | ۰ |
| ۲۶ تا ۴۵ دقیقه | `deep` | ۸۵٪ | ۵ | ۱ |
| ۴۶ تا ۱۲۰ دقیقه | `extended` | ۱۰۰٪ تا سقف بودجه | ۷ | ۲ |

بودجه اولیه input برای evidence extraction:

```text
max(12,000, min(180,000, duration_minutes * 1,800))
```

Critical یا debate mode پوشش را تا ۱۰ واحد درصد افزایش می‌دهد و objection/response را در اولویت می‌گذارد. مخاطب advanced نیز سقف claim و context را افزایش می‌دهد.

---

## مثال: «وضع بشر» در ۵ دقیقه و ۶۰ دقیقه

### خروجی ۵ دقیقه‌ای

هدف، ارائه یک thesis روشن و چند تمایز بنیادی است، نه پوشش کتاب.

Pipeline:

1. parse و block‌بندی کامل محدوده؛
2. Document Map کل محدوده؛
3. انتخاب بخش‌های required، definition، argument و conclusion؛
4. حدود ۳۵٪ token coverage؛
5. حداکثر ۲ claim در هر block؛
6. حذف exampleهای فرعی و بیشتر objectionها؛
7. ثبت blockهای کنارگذاشته‌شده به‌عنوان `deferred_block_ids`.

### خروجی ۶۰ دقیقه‌ای

هدف، پوشش استدلال، تمایزها، qualificationها، objectionها و مثال‌های مهم است.

Pipeline:

1. همان parse، block و Document Map قبلی؛
2. پوشش همه blockها تا سقف token budget؛
3. حداکثر ۷ claim در block؛
4. دو block همسایه برای context تفسیری؛
5. حفظ example، objection و response؛
6. در آینده second pass برای sectionهای مرکزی و مبهم.

بنابراین نسخه ۶۰ دقیقه‌ای نباید صرفاً نسخه کش‌آمده ۵ دقیقه‌ای باشد؛ substrate مشترک است، اما evidence breadth و depth متفاوت است.

---

## انتخاب blockها

انتخاب فعلی deterministic است. اولویت block بر اساس این عوامل محاسبه می‌شود:

1. section برای فهم کلی required باشد؛
2. function آن definition، argument یا conclusion باشد؛
3. در critical/debate mode، objection یا response باشد؛
4. title و key conceptهای section با سؤال مرکزی، subquestionها و scope هم‌پوشانی داشته باشند؛
5. مجموع tokenهای انتخاب‌شده به coverage target یا token budget برسد.

ترتیب نهایی blockهای منتخب مطابق ترتیب سند حفظ می‌شود.

مدل زبانی تصمیم نهایی درباره token budget یا block IDها را نمی‌گیرد.

---

## Grounding و context

در profileهای عمیق‌تر، blockهای همسایه برای فهم context به prompt داده می‌شوند؛ اما:

- claim باید فقط از target block استخراج شود؛
- supporting excerpt باید فقط در target block وجود داشته باشد؛
- neighbor context نمی‌تواند منبع evidence باشد؛
- validator این قاعده را enforce می‌کند.

این تفکیک اجازه می‌دهد تفسیر بهتر شود بدون اینکه provenance مبهم شود.

---

## Artifactها

برای هر source این فایل ساخته می‌شود:

```text
sources/<source-id>/evidence-extraction-plan.json
```

شامل:

- profile انتخاب‌شده؛
- target duration؛
- token budget؛
- blockهای منتخب؛
- blockهای deferred؛
- tokenهای انتخاب‌شده و کل tokenهای محتوای قابل‌تحلیل (`total_source_tokens`؛ یادداشت‌ها و endnoteها از مخرج پوشش خارج‌اند)؛
- coverage واقعی.

Source manifest نیز این مقادیر خلاصه را ثبت می‌کند:

- `analysis_depth`؛
- `selected_block_count`؛
- `deferred_block_count`؛
- `evidence_token_coverage`.

---

## پیاده‌سازی فعلی

فایل‌ها:

```text
src/thesisound/services/analysis_profile.py
src/thesisound/services/evidence_extractor.py
src/thesisound/services/source_analysis_service.py
src/thesisound/services/source_artifact_store.py
src/thesisound/source_analysis.py
prompts/evidence_extraction/1.1.0/
prompts/evidence_extraction/1.2.0/
prompts/evidence_extraction/1.3.0/
```

`extract-evidence` و `analyze-source` profile را خودکار از Research Brief پروژه می‌سازند. CLI پارامتر duration جداگانه ندارد؛ منبع حقیقت همان `target_duration_minutes` در brief است تا دو تنظیم متناقض ایجاد نشود.

---

## تغییر مدت بعد از استخراج

هدف نهایی این است:

```text
5-minute extraction
  -> change brief to 60 minutes
  -> reuse blocks, map, and valid existing evidence
  -> extract deferred blocks
  -> deepen only core sections when needed
```

نسخه فعلی plan جدید را می‌سازد و stage را دوباره اجرا می‌کند؛ reuse افزایشی block-level هنوز کامل نشده است. Artifactهای block-level زیرساخت این قابلیت را فراهم کرده‌اند.

---

## کارهای بعدی که نباید فراموش شوند

1. hierarchical Document Map برای کتاب کامل؛
2. incremental profile upgrade بدون اجرای مجدد blockهای معتبر؛
3. second-pass extraction فقط برای core sectionهای مبهم یا بسیار مهم؛
4. تقسیم token budget میان چند source بر اساس role و authority؛
5. benchmark کیفیت و هزینه برای tierهای مختلف؛
6. سنجش اینکه coverage targetها واقعاً با کیفیت اپیزود هم‌بستگی دارند یا نه؛
7. امکان نمایش deliberate omissions به کاربر؛
8. جلوگیری از اینکه خروجی ۶۰ دقیقه‌ای با padding و تکرار پر شود.
