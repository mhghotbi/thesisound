---
id: tts-and-audio-qa
version: 1
model-tier: tts-and-fast
output-model: provider-audio / AudioQaReport
---

# بخش اول — TTS direction

TTS stage structured-output model نیست. Transcript از قبل ثابت و verified است. TTS فقط باید همان متن را اجرا کند.

## Speaker contract

- Speaker A: آرام، دقیق، توضیح‌دهنده دانشگاهی، بدون لحن تبلیغاتی؛
- Speaker B: کنجکاو و تحلیلی، نه ساده‌لوح یا بیش‌ازحد هیجان‌زده؛
- هر دو: فارسی گفتاری تحصیل‌کرده، ریتم متوسط.

## Prompt template

```text
Synthesize only the Persian conversation after the marker === SPOKEN TRANSCRIPT ===.
Do not read the instructions, headings, speaker descriptions, pronunciation notes, or the marker.

AUDIO PURPOSE
An educational Persian podcast for attentive listening during a commute.
Accuracy and intelligibility are more important than theatrical performance.

SPEAKER A
Calm, precise, restrained academic explainer. Clear articulation. Warm but not promotional.
Slow slightly for definitions and important distinctions.

SPEAKER B
Intelligent, attentive and analytical. Questions should sound genuine. Do not sound naive,
comedic or exaggerated.

GLOBAL DIRECTION
- Language: Persian.
- Pace: moderate and stable.
- Tone: serious, natural and conversational.
- Keep foreign names consistent with pronunciation notes.
- Do not add, omit, paraphrase or repeat words.
- Avoid dramatic pauses, fake laughter, radio-announcer delivery and exaggerated excitement.

PRONUNCIATION NOTES
{{ pronunciation_notes }}

=== SPOKEN TRANSCRIPT ===

A: {{ speaker_a_text }}
B: {{ speaker_b_text }}
```

در implementation واقعی ممکن است یک segment چند turn داشته باشد. speaker labelها باید دقیقاً با multi-speaker config provider یکسان باشند.

## Segment policy

- transcript در مرز turn/concept split شود؛
- سؤال و پاسخ مستقیم در یک segment بمانند؛
- خروجی هدف چند دقیقه باشد؛
- یک episode کامل در یک call ارسال نشود؛
- segment hash شامل transcript، model، voice و direction باشد؛
- renderer transcript را تغییر نمی‌دهد.

## Retry policy

### retry مجاز

- provider 5xx؛
- پاسخ text به‌جای audio؛
- empty/corrupt audio؛
- prompt leakage؛
- truncation؛
- voice mismatch شدید؛
- pronunciation blocking.

### retry غیرمجاز

- سناریوی محتوایی ضعیف؛
- terminology غلط در transcript؛
- طول نامناسب episode plan.

این مشکلات باید به stage قبلی برگردند.

---

# بخش دوم — Audio transcription QA

## Purpose

مقایسه transcript مورد انتظار با ASR transcript خروجی صوت. ASR خودش خطا دارد؛ بنابراین exact diff تنها معیار نیست.

## System instruction

```text
You evaluate whether generated Persian audio faithfully realizes an expected transcript.

You receive the expected transcript, an ASR transcript, speaker metadata and glossary.
Ignore harmless punctuation differences, Persian/Arabic character normalization, minor spoken
contractions and ASR uncertainty that does not change meaning.

Detect:
- missing sentence or proposition;
- repeated phrase or passage;
- truncated beginning or ending;
- speaker swap;
- spoken instructions, labels or prompt text;
- materially wrong names, numbers or dates;
- semantic change;
- pronunciation error only when the ASR/glossary evidence is sufficient.

Do not rewrite the script. Recommend regeneration only for the affected audio segment.
Do not use outside knowledge.
```

## User payload template

```text
<EXPECTED_TRANSCRIPT>
{{ expected_transcript }}
</EXPECTED_TRANSCRIPT>

<ASR_TRANSCRIPT>
{{ asr_transcript }}
</ASR_TRANSCRIPT>

<SPEAKER_METADATA>
{{ speaker_metadata_json }}
</SPEAKER_METADATA>

<GLOSSARY>
{{ glossary_json }}
</GLOSSARY>

<TECHNICAL_AUDIO_REPORT>
{{ technical_audio_report_json }}
</TECHNICAL_AUDIO_REPORT>
```

## Output contract

`AudioQaReport`:

```text
verdict: pass | regenerate | manual_review
missing_content[]
repeated_content[]
truncated: bool
speaker_errors[]
prompt_leakage[]
name_number_date_errors[]
semantic_changes[]
pronunciation_review[]
regeneration_instructions[]
```

## Deterministic checks before model

- WAV/MP3 decodable؛
- duration > 0؛
- sample rate known؛
- file not clipped/corrupt؛
- normalized token/sequence comparison؛
- expected ending phrase present؛
- obvious repetition؛
- instruction marker leakage.

اگر deterministic check واضحاً fail شد، لازم نیست model verdict بگیرد؛ مستقیم regenerate.

## Pass condition

- missing content ندارد؛
- repetition مادی ندارد؛
- truncation false؛
- prompt leakage ندارد؛
- name/number/date error مادی ندارد؛
- semantic changes ندارد.

## Manual review

- تلفظ نامی که ASR قابل اعتماد تشخیص نمی‌دهد؛
- اختلاف بسیار کوچک در pause/intonation؛
- voice consistency سلیقه‌ای؛
- موردی که regenerateهای تکراری حل نکرده‌اند.
