# 09 — TTS، ASR و Audio QA vertical slice

as-built؛ ادامهٔ مستقیم [`08-web-script-review.md`](08-web-script-review.md)، آخرین slice پیش از runbook پذیرش در [`10-local-live-e2e-runbook.md`](10-local-live-e2e-runbook.md).

## هدف

این slice سناریوی `SCRIPT_VERIFIED` را به فایل صوتی قابل شنیدن و قابل‌ممیزی تبدیل می‌کند:

```text
SCRIPT_VERIFIED
→ TTS-safe chunks
→ speech synthesis
→ WAV validation
→ ASR transcription
→ expected-vs-ASR comparison
→ targeted regeneration, at most once
→ FFmpeg loudness normalization and assembly
→ COMPLETE
```

رسیدن به `COMPLETE` صرفاً به معنای ساخته‌شدن یک فایل نیست. تمام chunkها باید QA را pass کرده باشند و checksum فایل نهایی با manifest یکسان باشد.

## Provider boundary

دو port مستقل وجود دارد:

```text
TextToSpeechPort
SpeechToTextPort
```

adapter اولیه Gemini است. model ID و voiceها فقط در config قرار دارند. مسیر domain، artifact و run به provider خاص وابسته نیست.

## Chunking

هر chunk:

- فقط یک speaker دارد؛
- از یک turn مشخص مشتق می‌شود؛
- تا حد ممکن روی مرز جمله قطع می‌شود؛
- `content_hash` آن به script hash، segment، turn، speaker، voice، model، style prompt و متن وابسته است؛
- مدت مورد انتظار آن برای structural validation تخمین زده می‌شود.

تغییر script، voice، model یا style باعث reuse صوت قبلی نمی‌شود.

## Artifactها

```text
workspaces/<project-id>/
  audio-build-run.json
  runs/audio/<run-id>.json
  audio/
    verified-script-hash.txt
    chunks.json
    manifest.json
    segments/<chunk-id>.wav
    segments/<chunk-id>.json
    asr/<chunk-id>.json
    qa/<chunk-id>.json
    final.wav
```

هر WAV segment checksum مستقل دارد. خواندن artifact با checksum نادرست fail می‌شود.

## WAV gate

برای هر segment کنترل می‌شود:

- WAV container معتبر؛
- mono؛
- PCM 16-bit؛
- sample rate مورد انتظار؛
- frame و duration غیرصفر؛
- اختلاف مادی با مدت تخمینی؛
- clipping در full scale.

## ASR و مقایسه

ASR باید متن شنیده‌شده را بدون خلاصه‌سازی برگرداند. مقایسه deterministic موارد زیر را بررسی می‌کند:

- similarity ratio پس از normalization فارسی؛
- جمله افتاده؛
- عبارت تکراری؛
- پایان truncate‌شده؛
- speaker mismatch در صورت گزارش ASR.

نتیجه هر chunk:

```text
pass | regenerate | manual_review
```

در اجرای خودکار فقط `pass` پذیرفته است. chunk غیرقابل‌قبول حداکثر یک بار با instruction هدفمند بازتولید می‌شود. شکست دوباره پروژه را `FAILED_RETRYABLE` می‌کند؛ خروجی ناقص به `COMPLETE` نمی‌رسد.

## Assembly

پس از pass همه chunkها:

1. WAVهای هم‌پارامتر با سکوت کوتاه به هم متصل می‌شوند؛
2. FFmpeg loudness normalization اجرا می‌شود؛
3. خروجی به mono 24 kHz WAV تبدیل می‌شود؛
4. structural validation نهایی اجرا می‌شود؛
5. checksum، duration و normalization method در manifest ثبت می‌شوند.

FFmpeg dependency سیستم است و باید روی `PATH` باشد.

## Resume و retry

- segment، ASR و QA سالم reuse می‌شوند؛
- فقط chunk مفقود، stale یا checksum-failed دوباره ساخته می‌شود؛
- هر retry یک `run_id` جدید با `previous_run_id` دارد؛
- attempt قبلی overwrite نمی‌شود؛
- restart در `queued` یا `running` به failure قابل retry تبدیل می‌شود؛
- `COMPLETE` با artifact ناقص یا stale دوباره به `FAILED_RETRYABLE` باز می‌شود؛
- اگر project و artifactها کامل باشند ولی آخرین write run شکست خورده باشد، startup آن را به success reconcile می‌کند.

## UI

صفحه زیر اضافه شده است:

```text
/projects/<project-id>/audio
```

نمایش می‌دهد:

- stage واقعی run؛
- player و دانلود فایل نهایی؛
- player هر chunk؛
- متن مورد انتظار؛
- ASR transcript؛
- similarity ratio؛
- افتادگی‌های احتمالی؛
- تعداد regenerationها.

فایل صوتی stale یا متعلق به script دیگر serve نمی‌شود.

## CLI

```bash
uv run thesisound prepare-audio <project-id>
uv run thesisound audio-status <project-id>
```

## مرز این milestone

این slice مکانیزم و gateهای صوت را پیاده می‌کند. تصمیم نهایی درباره اندازه بهینه chunk، voiceها، سبک تک‌گوینده/دوگوینده و thresholdها باید با corpus واقعی و blind listening calibration شود؛ اما تغییر این مقادیر بدون بازتولید artifactهای وابسته ممکن نیست.
