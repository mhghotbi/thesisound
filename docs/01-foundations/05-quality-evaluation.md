# 05 — کیفیت و ارزیابی

## اصل

Thesisound نباید با معیار «خروجی روان به نظر می‌رسد» ارزیابی شود. روانی ممکن است خطای محتوایی را پنهان کند. ارزیابی باید چندبعدی و مبتنی بر منبع باشد.

## ابعاد کیفیت

### ۱. Parse fidelity

- متن افتاده یا جابه‌جا نشده؛
- heading و ترتیب خواندن حفظ شده؛
- locator قابل استفاده است؛
- scan/OCR خطای مادی ندارد.

### ۲. Evidence fidelity

- claim با excerpt و locator پشتیبانی می‌شود؛
- direct claim از inference جداست؛
- qualificationها حفظ شده‌اند؛
- metadata-only source به‌عنوان full text استفاده نشده است.

### ۳. Coverage

- objectiveهای اصلی پوشش داده شده‌اند؛
- موضوع‌های حذف‌شده ثبت شده‌اند؛
- پوشش تصادفی یا تابع جذابیت سطحی مدل نیست.

### ۴. Synthesis quality

- اختلاف‌ها به اجماع جعلی تبدیل نشده‌اند؛
- نسبت source و interpretation روشن است؛
- dependency مفاهیم رعایت شده؛
- episode مسیر فهم دارد، نه فهرست نکته‌ها.

### ۵. Persian script quality

- فارسی گفتاری طبیعی و دقیق است؛
- اصطلاح‌ها consistency دارند؛
- attribution و certainty عوض نشده؛
- filler و تکرار کم است؛
- گوینده دوم سؤال واقعی می‌پرسد.

### ۶. Audio quality

- transcript کامل خوانده شده؛
- voice drift شدید نیست؛
- نام‌ها قابل‌قبول تلفظ شده‌اند؛
- instruction یا label خوانده نشده؛
- loudness و اتصال segmentها آزاردهنده نیست.

## Quality gates

### Parse gate

```text
blocking if:
- critical page missing
- reading order materially wrong
- locator unavailable for core text
- OCR corruption changes meaning
```

### Evidence gate

```text
blocking if:
- excerpt cannot be matched to source block
- non-editorial claim has no evidence
- source access is not full text
- attribution is uncertain and unmarked
```

### Coverage gate

```text
pass if:
- central question is supported
- all must-have objectives are covered
- uncovered optional areas are disclosed
```

### Script gate

```text
pass if:
- unsupported_claim_ratio == 0
- blocking issues == 0
- high issues == 0
- every substantive turn has valid claim_ids
```

### Audio gate

```text
pass if:
- no missing sentence
- no repeated passage
- no truncated ending
- no prompt leakage
- no material name/number/date error
```

## Golden corpus

قبل از توسعه گسترده، یک corpus کوچک و ثابت تهیه شود:

1. یک مقاله سخت‌خوان که کاربر قبلاً خوانده؛
2. یک فصل کتاب نظری؛
3. یک PDF اسکن‌شده فارسی؛
4. یک EPUB انگلیسی؛
5. یک موضوع چندمنبعی با اختلاف تفسیر.

برای هر fixture:

- must-cover points؛
- must-preserve distinctions؛
- known controversial points؛
- expected locatorها؛
- pronunciation list؛
- unacceptable errors

به‌صورت دستی ثبت شود.

## مقایسه با NotebookLM

blind comparison روی همان source و scope:

| معیار | وزن پیشنهادی |
|---|---:|
| پوشش نکات ضروری | 25% |
| وفاداری به متن | 25% |
| حفظ تمایز و اختلاف | 20% |
| وضوح فارسی | 15% |
| طبیعی‌بودن صوت | 10% |
| تکرار/filler | 5% |

اگر Thesisound فقط در UI بهتر و در سه معیار اول ضعیف‌تر باشد، پروژه موفق نیست.

## روش human evaluation

ارزیاب برای هر خروجی:

- متن اصلی یا key را در اختیار دارد؛
- نام سیستم تولیدکننده را نمی‌بیند؛
- هر معیار را ۱ تا ۵ می‌دهد؛
- خطاهای blocking را جدا ثبت می‌کند؛
- نقاطی که مجبور شده برای فهم دوباره به متن برگردد علامت می‌زند.

## Prompt regression tests

هر تغییر prompt باید روی golden corpus اجرا شود و این‌ها مقایسه شوند:

- schema success rate؛
- retry count؛
- claim coverage؛
- unsupported claims؛
- output length؛
- cost/token usage؛
- human score.

prompt جدید صرفاً چون «متن قشنگ‌تری» ساخته merge نمی‌شود.

## Deterministic tests

حداقل:

- state transition؛
- source dedup؛
- access/evidence eligibility؛
- excerpt matching؛
- claim ID existence؛
- word/time budget؛
- TTS segment boundaries؛
- audio output file integrity.

## Model-assisted evaluator limitations

LLM verifier خودش خطاپذیر است. بنابراین:

- verifier verdict حقیقت نهایی نیست؛
- exact excerpt matching deterministic است؛
- نمونه‌های مهم human-reviewed می‌شوند؛
- writer و verifier prompt/context جدا دارند؛
- verifier نباید با confidence بالا نبود شواهد را جبران کند.

## Metrics پیشنهادی

```text
parse_retry_rate
parse_manual_review_rate
source_acceptance_rate
full_text_acquisition_rate
evidence_excerpt_match_rate
coverage_gap_rate
script_revision_rate
unsupported_claim_ratio
terminology_issue_rate
tts_retry_rate
audio_segment_failure_rate
human_quality_score
manual_minutes_per_episode
```

برای MVP مهم‌ترین metricها:

1. unsupported claim ratio؛
2. must-cover recall؛
3. manual minutes saved؛
4. human listenability score.

## Definition of Done برای vertical slice

- یک source واقعی پردازش شده؛
- locator درست است؛
- evidence records ساخته شده؛
- episode plan claim-bound است؛
- سناریوی فارسی gate را پاس کرده؛
- صوت segmentشده ساخته شده؛
- ASR نشان نمی‌دهد متن افتاده؛
- کاربر کیفیت را در blind comparison قابل‌قبول دانسته است.
