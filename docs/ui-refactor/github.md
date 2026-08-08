repo: mhghotbi/thesisound
branch: main
path: src/thesisound/web

## Last sync

date: 2026-08-09T00:00:00Z

### Updated in this project

- Full evidence-based UI/UX audit of `src/thesisound/web` against PRODUCT.md, DESIGN.md and docs/16-20: `docs/29-ui-ux-audit.md` (20 findings, P0-P2) and `docs/30-ui-redesign-spec.md` (target design contract). Repo is mounted read-only; code changes staged as spec for handoff.

- Recreated the current web UI (8 screens/states) from the Jinja templates and `app.css` as the audit baseline.
- Explored five visual directions, then rebuilt the projects screen structurally (grouped by attention state).
- Redesigned the full single-session path (10 screens) in the magazine direction: login, OTP, question, sources, waiting, episode plan, script with evidence, final audio, projects list, empty state.
- Applied the imported craft guidelines: no eyebrow kickers, no thick side stripes, authored SVG icons instead of glyphs, tabular numerals, real focus-visible states.
- No repo files were modified; all work lives in this project.

## Reference skills

- pbakaus/impeccable — `skill/SKILL.src.md`, `skill/reference/craft-floor.md`, `skill/reference/operate.md` (design method + quality floor; its own Neo Kinpaku DESIGN.md is that repo's brand, deliberately not applied here)
- vercel-labs/agent-skills — `skills/web-design-guidelines/SKILL.md` (final web audit)

## Screen map

| Project screen | Repo files |
| --- | --- |
| Thesisound Current UI — 01 ورود | `templates/auth/login.html`, `templates/base.html`, `static/app.css` |
| Thesisound Current UI — 02/03 فهرست پروژه‌ها | `templates/projects/index.html`, `web/read_models.py`, `static/app.css` |
| Thesisound Current UI — 04 منابع | `templates/projects/sources.html`, `web/source_routes.py` |
| Thesisound Current UI — 05 پردازش | `templates/projects/processing.html`, `web/corpus_runtime.py` |
| Thesisound Current UI — 06 طرح اپیزود | `templates/projects/episode.html`, `web/episode_routes.py` |
| Thesisound Current UI — 07 سناریو | `templates/projects/script.html`, `web/script_routes.py` |
| Thesisound Current UI — 08 آمادگی اجرا | `templates/system-check.html` |
| Thesisound Flow — 01/02 ورود و کد | `templates/auth/login.html`, `templates/auth/verify.html` |
| Thesisound Flow — 03 پرسش | `templates/projects/new.html`, `templates/projects/brief.html` |
| Thesisound Flow — 04 منابع | `templates/projects/sources.html`, `web/source_routes.py` |
| Thesisound Flow — 05 انتظار | `templates/projects/processing.html`, `web/corpus_runtime.py` |
| Thesisound Flow — 06 ساختار اپیزود | `templates/projects/episode.html`, `web/episode_routes.py` |
| Thesisound Flow — 07 متن اپیزود | `templates/projects/script.html`, `web/script_routes.py` |
| Thesisound Flow — 08 فایل نهایی | `templates/projects/audio.html` |
| Thesisound Flow — 09/10 پروژه‌ها و حالت خالی | `templates/projects/index.html`, `web/read_models.py` |
