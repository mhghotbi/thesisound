# مرجع بصری بازطراحی — نقشهٔ صفحه‌ها

خروجی تولیدشدهٔ ابزار طراحی (`Thesisound UI v2.dc.html`، `support.js`، `.thumbnail`). دستی ویرایش نمی‌شود.

مبنا: `src/thesisound/web` روی `main`، sync در ۲۰۲۶-۰۸-۰۹. اسناد متناظر: [`../05-ui-redesign/01-ui-ux-audit.md`](../05-ui-redesign/01-ui-ux-audit.md) (یافته‌های F-01…F-20) و [`../05-ui-redesign/02-ui-redesign-spec.md`](../05-ui-redesign/02-ui-redesign-spec.md) (قرارداد طراحی مقصد).

دو مجموعه صفحه در فایل طراحی هست: **Current UI** (بازسازی رابط موجود به‌عنوان مبنای ممیزی، ۸ صفحه) و **Flow** (مسیر کامل بازطراحی‌شده، ۱۰ صفحه).

| صفحهٔ طراحی | فایل‌های repo |
| --- | --- |
| Current 01 · Flow 01/02 — ورود و کد | `templates/auth/login.html`، `templates/auth/verify.html`، `templates/base.html`، `static/app.css` |
| Current 02/03 · Flow 09/10 — فهرست پروژه‌ها و حالت خالی | `templates/projects/index.html`، `web/read_models.py` |
| Flow 03 — پرسش | `templates/projects/new.html`، `templates/projects/brief.html` |
| Current 04 · Flow 04 — منابع | `templates/projects/sources.html`، `web/source_routes.py` |
| Current 05 · Flow 05 — پردازش و انتظار | `templates/projects/processing.html`، `web/corpus_runtime.py` |
| Current 06 · Flow 06 — طرح/ساختار اپیزود | `templates/projects/episode.html`، `web/episode_routes.py` |
| Current 07 · Flow 07 — سناریو و متن اپیزود | `templates/projects/script.html`، `web/script_routes.py` |
| Flow 08 — فایل نهایی | `templates/projects/audio.html` |
| Current 08 — آمادگی اجرا | `templates/system-check.html` |

قواعد صنعتگری اعمال‌شده در طراحی: بدون eyebrow kicker، بدون نوار کناری ضخیم، آیکون SVG نوشته‌شده به‌جای glyph، ارقام tabular، حالت focus-visible واقعی.
