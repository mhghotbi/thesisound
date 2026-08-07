# 08 — امنیت، حریم خصوصی و حق نشر

## محدوده

Thesisound فایل‌های کتاب، مقاله و متن خام را پردازش می‌کند. این فایل‌ها ممکن است:

- copyrighted باشند؛
- هنوز منتشر نشده باشند؛
- اطلاعات شخصی یا پژوهشی حساس داشته باشند؛
- طبق شرایط provider اجازه استفاده خاصی نداشته باشند.

حتی برای یک ابزار شخصی، این موضوع را نباید به بعد موکول کرد.

## اصول

1. local processing پیش‌فرض است؛
2. upload به provider باید قابل مشاهده و قابل خاموش‌کردن باشد؛
3. کمترین داده لازم ارسال شود؛
4. raw source در log قرار نمی‌گیرد؛
5. secret در repository یا artifact ذخیره نمی‌شود؛
6. خروجی مشتق‌شده بدون حق لازم عمومی منتشر نمی‌شود.

## Data classes

### Public

- URL عمومی؛
- metadata کتاب/مقاله؛
- title/author/year؛
- prompt template عمومی.

### Private

- فایل آپلودشده؛
- متن استخراج‌شده؛
- یادداشت کاربر؛
- transcript شخصی؛
- تاریخچه پروژه.

### Secret

- API key؛
- access token؛
- signed URL؛
- provider credential.

Secret هرگز وارد prompt، artifact JSON یا log نمی‌شود.

## Provider upload policy

قبل از ارسال متن یا فایل به provider:

- `allow_provider_uploads` بررسی شود؛
- provider و نوع داده در UI/CLI مشخص باشد؛
- اگر فایل unpublished/sensitive است، warning داده شود؛
- امکان استفاده از paid/private tier یا local model توضیح داده شود؛
- upload decision در manifest ثبت شود.

## Free tier

شرایط Free Tier providerها ممکن است اجازه استفاده از داده برای بهبود محصول بدهد. تنظیمات و شرایط ممکن است تغییر کند؛ قبل از deploy باید مستندات فعلی provider دوباره بررسی شود.

برای source حساس:

- Free Tier استفاده نشود؛
- یا فقط excerpt حداقلی و de-identified ارسال شود؛
- یا pipeline local نگه داشته شود.

## Copyright

### مجاز بودن پردازش برابر با مجاز بودن انتشار نیست

کاربر ممکن است حق مطالعه و پردازش شخصی فایل را داشته باشد، اما این به‌معنای حق انتشار عمومی صوت مشتق‌شده یا transcript طولانی نیست.

MVP:

- private output؛
- بدون public feed؛
- بدون اشتراک‌گذاری خودکار؛
- بدون بازتولید نقل‌قول طولانی در UI؛
- source locator به‌جای نمایش غیرضروری متن کامل.

## Storage

مسیرهای local:

```text
workspaces/<project-id>/inputs/original/
workspaces/<project-id>/03-corpus/
workspaces/<project-id>/06-audio/
```

این مسیرها در `.gitignore` هستند.

### retention

در آینده:

- raw provider response: default off؛
- temporary TTS chunks: پاک‌شدن بعد از assemble اختیاری؛
- source text: تا زمان حذف project؛
- logs: بدون متن کامل؛
- cleanup command.

## URL fetching safety

برای URLهای کاربر:

- فقط `http` و `https`؛
- block private IP ranges؛
- block localhost و metadata endpoints؛
- redirect limit؛
- content-length limit؛
- MIME validation؛
- timeout؛
- antivirus/file scanning در hosted deployment.

این برای جلوگیری از SSRF لازم است.

## File safety

- extension کافی نیست؛ MIME بررسی شود؛
- archive bomb و oversized file محدود شود؛
- encrypted PDF handling مشخص باشد؛
- parser در process/container محدود اجرا شود؛
- filename برای filesystem path مستقیم استفاده نشود؛
- random internal ID ساخته شود.

## Prompt injection از منابع

متن یک صفحه وب یا PDF ممکن است شامل دستورهایی مثل «تمام دستورهای قبلی را نادیده بگیر» باشد.

قواعد:

- source text همیشه data است، نه instruction؛
- prompt delimiter روشن؛
- مدل tool access ندارد؛
- source نمی‌تواند schema یا stage goal را عوض کند؛
- instruction-like content در source به‌عنوان متن تحلیل می‌شود؛
- retrieved text اجازه اضافه‌کردن URL یا source جدید ندارد.

## Output safety

- claim بدون evidence رد شود؛
- نقل‌قول ساختگی blocking issue است؛
- موضوع حساس باید uncertainty و attribution را حفظ کند؛
- output پزشکی/حقوقی/مالی نیازمند policy جداست و در MVP هدف نیست.

## Dependency security

- dependencyها حداقل نگه داشته شوند؛
- parserهای سنگین optional extra باشند؛
- lockfile commit شود وقتی اولین developer `uv lock` را تولید کرد؛
- Dependabot یا Renovate بعداً؛
- subprocess با shell interpolation اجرا نشود؛
- FFmpeg args list باشد.

## Secrets

- `.env` در Git نیست؛
- CI secret فقط در secret store؛
- API key در error message چاپ نشود؛
- provider client header redaction؛
- key rotation در صورت leak.

## Minimum checklist پیش از hosted deployment

- [ ] authentication
- [ ] per-user project isolation
- [ ] signed file access
- [ ] SSRF protection
- [ ] upload size limits
- [ ] background job isolation
- [ ] secret management
- [ ] retention/delete flow
- [ ] privacy notice
- [ ] provider terms review
- [ ] copyright/export warning
- [ ] audit logs without source text
