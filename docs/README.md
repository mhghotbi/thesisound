# Thesisound Docs — Index

نقشهٔ اسناد پروژه. هر پوشه یک حوزه است و شماره‌گذاری داخل هر پوشه ترتیب خواندن است — از ۰۱ شروع می‌شود و بدون جهش ادامه پیدا می‌کند. عنوان داخل هر فایل با شمارهٔ فایل یکی است.

قبل از تغییرنام یا جابه‌جایی هر سند، ارجاعات آن را پیدا و اصلاح کنید:

```bash
grep -rn "docs/<old-path>" --include="*.py" --include="*.md" .
```

## شروع کنید از اینجا

| سند | چرا |
| --- | --- |
| [`01-foundations/01-product-scope.md`](01-foundations/01-product-scope.md) | چه می‌سازیم، برای که، و چه چیزی جزو محصول نیست |
| [`01-foundations/02-architecture.md`](01-foundations/02-architecture.md) | معماری فعلی، لایه‌ها و pipeline |
| [`01-foundations/03-agent-workflow.md`](01-foundations/03-agent-workflow.md) | قرارداد اجرای هر stage — مرجع اصلی خط تولید |
| [`06-operations/03-production-sop.md`](06-operations/03-production-sop.md) | رویهٔ عملیاتی تولید یک اپیزود و گیت‌های انسانی |
| [`05-ui-redesign/02-ui-redesign-spec.md`](05-ui-redesign/02-ui-redesign-spec.md) | هدف فعلی رابط کاربری |
| [`05-ui-redesign/03-product-language.md`](05-ui-redesign/03-product-language.md) | واژگان مصوب محصول — مرجع هر متن کاربرپسند |

## `01-foundations/` — بنیان محصول و معماری

| سند | موضوع |
| --- | --- |
| [`01-product-scope.md`](01-foundations/01-product-scope.md) | محدودهٔ محصول، مخاطب، ارزش‌ها، non-goals |
| [`02-architecture.md`](01-foundations/02-architecture.md) | لایه‌ها، portها، pipeline، state machine |
| [`03-agent-workflow.md`](01-foundations/03-agent-workflow.md) | قرارداد هر stage: ورودی، gate، budget، retry |
| [`04-document-and-source-strategy.md`](01-foundations/04-document-and-source-strategy.md) | انتخاب parser، فرمت سند نرمال‌شده، کشف منبع |
| [`05-quality-evaluation.md`](01-foundations/05-quality-evaluation.md) | ابعاد کیفیت، golden corpus، مقایسه با NotebookLM، metricها |
| [`06-development-plan.md`](01-foundations/06-development-plan.md) | ترتیب milestoneها و دلیل آن — وضعیت زنده در `STATUS.md` |
| [`07-junior-guide.md`](01-foundations/07-junior-guide.md) | نقشهٔ کد، ترتیب افزودن feature و قواعدی که زیاد نقض می‌شوند |
| [`08-security-privacy-copyright.md`](01-foundations/08-security-privacy-copyright.md) | کلاس‌های داده، حق نشر، SSRF، prompt injection |
| [`09-open-questions.md`](01-foundations/09-open-questions.md) | تصمیم‌های باز OQ-001…OQ-010 (سند زنده) |

## `02-pipeline/` — خط لولهٔ شواهد و تولید محتوا

زنجیرهٔ خطی؛ خروجی هر سند ورودی سند بعدی است.

| سند | موضوع |
| --- | --- |
| [`01-document-ingestion.md`](02-pipeline/01-document-ingestion.md) | فایل خام → `ParsedDocument` قابل‌ممیزی |
| [`02-structured-model-execution.md`](02-pipeline/02-structured-model-execution.md) | قرارداد مشترک فراخوانی مدل که همهٔ stageها روی آن سوارند |
| [`03-one-source-evidence-pipeline.md`](02-pipeline/03-one-source-evidence-pipeline.md) | بلاک‌ها → Document Map → شواهد → Claim Ledger |
| [`04-output-aware-analysis-budget.md`](02-pipeline/04-output-aware-analysis-budget.md) | تعیین عمق و بودجهٔ استخراج بر اساس مدت خروجی |
| [`05-episode-preparation.md`](02-pipeline/05-episode-preparation.md) | ارزیابی پوشش، اولویت‌بندی و Episode Plan |
| [`06-persian-script-pipeline.md`](02-pipeline/06-persian-script-pipeline.md) | نگارش و راستی‌آزمایی متن فارسی |

## `03-web-ui/` — رابط عملیاتی

۰۱، ۰۲ و ۰۴ مرجع اصول‌اند؛ ۰۳ فقط برای شناسه‌های صفحه نگه داشته شده و routeهایش با کد یکی نیست؛ ۰۵–۰۹ ثبت as-built پیاده‌سازی واقعی‌اند. برای هدف فعلی رابط به [`05-ui-redesign/`](05-ui-redesign/) بروید.

| سند | موضوع | وضعیت |
| --- | --- | --- |
| [`01-operator-user-workflow.md`](03-web-ui/01-operator-user-workflow.md) | ۷ اصل UX، مرز Operator/End-user، معیار پذیرش | مرجع |
| [`02-interface-state-model.md`](03-web-ui/02-interface-state-model.md) | سه محور state: lifecycle / execution / attention | مرجع |
| [`03-operator-screen-inventory.md`](03-web-ui/03-operator-screen-inventory.md) | شناسه‌های S-01…S-12 و نیت طراحی — routeها با کد یکی نیستند | تاریخی |
| [`04-error-and-recovery-ux.md`](03-web-ui/04-error-and-recovery-ux.md) | تاکسونومی خطا E1–E12 و ماتریس بازیابی | مرجع |
| [`05-web-ui-auth-and-first-slice.md`](03-web-ui/05-web-ui-auth-and-first-slice.md) | OTP، session، RTL و اولین برش | as-built |
| [`06-web-corpus-building.md`](03-web-ui/06-web-corpus-building.md) | ساخت مجموعه شواهد چندمنبعی | as-built |
| [`07-web-episode-planning.md`](03-web-ui/07-web-episode-planning.md) | ارزیابی پوشش و طرح اپیزود | as-built |
| [`08-web-script-review.md`](03-web-ui/08-web-script-review.md) | تأیید طرح، ساخت و بازبینی سناریو | as-built |
| [`09-audio-vertical-slice.md`](03-web-ui/09-audio-vertical-slice.md) | TTS، ASR و Audio QA | as-built |
| [`10-local-live-e2e-runbook.md`](03-web-ui/10-local-live-e2e-runbook.md) | رویهٔ پذیرش دستی با providerهای واقعی | runbook |

## `04-integrations/` — منابع بیرونی، مدل‌ها و مشاهده‌پذیری

| سند | موضوع |
| --- | --- |
| [`01-gemini-grounding.md`](04-integrations/01-gemini-grounding.md) | Google Search و URL Context، سیاست هر stage، مرز شواهد |
| [`02-source-discovery-large-docs-and-revision.md`](04-integrations/02-source-discovery-large-docs-and-revision.md) | جریان جست‌وجو→corpus، پارتیشن اسناد بزرگ، معناشناسی rewind |
| [`03-epub-ingestion.md`](04-integrations/03-epub-ingestion.md) | خواندن EPUB، locator و امنیت آرشیو |
| [`04-self-hosted-ocr.md`](04-integrations/04-self-hosted-ocr.md) | مسیریابی OCR صفحه‌محور و اجرای offline |
| [`05-model-observability.md`](04-integrations/05-model-observability.md) | ledger واحد فراخوانی مدل — مرجع مشترک Gemini و Okian |
| [`06-okian-provider-and-model-routing.md`](04-integrations/06-okian-provider-and-model-routing.md) | provider دوم و مسیریابی مدل بر اساس stage |

## `05-ui-redesign/` — بازطراحی فعلی رابط

زنجیرهٔ خطی: ممیزی ⟶ spec هدف ⟶ واژگان.

| سند | موضوع |
| --- | --- |
| [`01-ui-ux-audit.md`](05-ui-redesign/01-ui-ux-audit.md) | ممیزی رابط موجود، یافته‌های F-01…F-20 با اولویت P0–P2 |
| [`02-ui-redesign-spec.md`](05-ui-redesign/02-ui-redesign-spec.md) | قرارداد طراحی مقصد و ترتیب پیاده‌سازی |
| [`03-product-language.md`](05-ui-redesign/03-product-language.md) | واژگان مصوب فارسی و قواعد نام‌گذاری |

مرجع بصری: [`ui-refactor/`](ui-refactor/) — خروجی تولیدشدهٔ ابزار طراحی (`Thesisound UI v2.dc.html`)، دستی ویرایش نمی‌شود. نقشهٔ «صفحهٔ طراحی ← فایل repo» در [`ui-refactor/github.md`](ui-refactor/github.md).

## `06-operations/` — عملیات

| سند | موضوع |
| --- | --- |
| [`01-server-mono-process-adoption.md`](06-operations/01-server-mono-process-adoption.md) | اقتباس روال کیفیت: بندهای ۱–۱۰ انجام‌شده، ۱۱–۱۳ باز، ۱۴ رد شد |
| [`02-server-mono-process-adoption-fa.md`](06-operations/02-server-mono-process-adoption-fa.md) | همان، روایت غیرفنی |
| [`03-production-sop.md`](06-operations/03-production-sop.md) | رویهٔ عملیاتی، ۱۲ گیت و تصمیم‌های صرفاً انسانی |

## `07-specs/` — specهای اصلاحی برخاسته از ممیزی آمادگی MVP

قرارداد پیاده‌سازی، نه پیشنهاد. ۰۴ و ۰۵ از بازطراحی رابط می‌آیند؛ ۰۱–۰۳ و ۰۶–۰۸ هر کدام یک یافتهٔ [ممیزی آمادگی MVP](thesisound-mvp-readiness-audit-fa.html) را به تغییری قابل‌پیاده‌سازی تبدیل می‌کنند: مسئلهٔ اندازه‌گیری‌شده، طراحی، معیار پذیرش و برنامهٔ تست. سه بند «Simplify / Change before MVP» در ۰۳، ۰۶ و ۰۷ جداگانه پوشش داده شده‌اند.

| سند | موضوع | وابستگی |
| --- | --- | --- |
| [`01-evidence-artifact-schema-upgrade.md`](07-specs/01-evidence-artifact-schema-upgrade.md) | خواندن دوبارهٔ artifactهای شواهد پس از schema drift؛ upgrade در read path، تخریب per-artifact، تفکیک «ناخوانا» از «بی‌کیفیت» | — |
| [`02-script-dialogue-quality-gate.md`](07-specs/02-script-dialogue-quality-gate.md) | binding کردن کف کیفیت گفت‌وگو: filler، تکرار، عدم توازن گوینده و نکات ازدست‌رفته | بند dropped-content به ۰۱ وابسته است |
| [`03-inline-research-brief.md`](07-specs/03-inline-research-brief.md) | brief درون‌صفحه و قابل‌ویرایش، بدون approval جدا — بدون حذف state | — |
| [`04-evidence-traceability.md`](07-specs/04-evidence-traceability.md) | ردیابی شاهد: از گفته تا نشانی در منبع | — |
| [`05-plan-priorities.md`](07-specs/05-plan-priorities.md) | اولویت‌های کاربر در طرح گفتار و مذاکره بر سر ظرفیت | ۰۴ §۶.۵ |
| [`06-conditional-document-map.md`](07-specs/06-conditional-document-map.md) | حذف فراخوانی map وقتی انتخاب شواهد جامع است، با map قطعیِ جایگزین | — |
| [`07-conditional-glossary-and-verification.md`](07-specs/07-conditional-glossary-and-verification.md) | glossary همیشه deterministic و مدل فقط در صورت نیاز؛ verifier unconditional (audit)؛ reviser صریح | پیاده‌شده (glossary + reviser) |
| [`08-batched-claim-reconciliation.md`](07-specs/08-batched-claim-reconciliation.md) | partition/merge برای claim reconciliation وقتی شواهد یک source از بودجهٔ prompt بیشتر است | — |

## افزودن سند جدید

1. پوشهٔ حوزهٔ مربوطه را انتخاب کنید؛ حوزهٔ جدید = پوشهٔ جدید با پیشوند دو رقمی.
2. شمارهٔ بعدی همان پوشه را بگیرید و همان شماره را در عنوان `# NN — ...` داخل فایل بنویسید.
3. همین `docs/README.md` را به‌روزرسانی کنید.
4. اگر سند جدید موضوعی را از سند موجود ادامه می‌دهد، در هر دو طرف لینک بگذارید؛ محتوای سند دیگر را دوباره ننویسید.
