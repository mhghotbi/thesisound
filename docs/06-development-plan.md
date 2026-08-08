# 06 — برنامه توسعه

## راهبرد

ترتیب توسعه بر اساس ریسک است، نه جذابیت UI:

```text
input fidelity
→ evidence fidelity
→ episode sufficiency
→ script fidelity
→ audio fidelity
→ operator control and observability
→ discovery and multi-source breadth
→ end-user UI and deployment
```

Operator UI و End-user UI دو milestone متفاوت‌اند. اولی ابزار محلی برای اجرای pipeline، مشاهده artifact و recovery است؛ دومی تجربه ساده‌شده و polished برای کاربر غیرمتخصص.

قواعد سراسری:

- parse، block ID و locator مستقل از duration هستند؛
- breadth/depth evidence و episode به duration وابسته‌اند؛
- مدل هیچ ID یا locator معتبری نمی‌سازد؛
- متن اصلی source of truth است؛
- corpus ناکافی با padding جبران نمی‌شود؛
- writer تنها verifier خروجی خودش نیست؛
- هر stage artifact، gate و failure state مستقل دارد؛
- UI منطق orchestration یا state machine دوم نمی‌سازد.

---

## Milestone 0 — Scaffold و قراردادها

**وضعیت: انجام‌شده**

- domain models؛
- state machine؛
- workspace store؛
- prompt loader؛
- CLI؛
- CI، Ruff و pytest.

---

## Milestone 1 — Document Ingestion

**وضعیت کد: انجام‌شده**

- inspection فایل و PDF؛
- Docling adapter؛
- MinerU CLI adapter؛
- parser router و fallback؛
- normalization؛
- parse quality gate؛
- parser benchmark harness؛
- artifact persistence.

**کار تجربی باقی‌مانده:** اجرای benchmark روی corpus واقعی فارسی، اسکن، چندستونه، کتاب و مقاله و ثبت ADR انتخاب parser.

---

## Milestone 2 — Structured Model Execution

**وضعیت کد: انجام‌شده**

- provider-neutral model port؛
- Gemini Structured Output؛
- prompt versioning؛
- schema repair و transient retry؛
- run metadata و redacted persistence؛
- Research Brief؛
- opt-in live Gemini smoke test.

**کار تجربی باقی‌مانده:** اجرای `pytest -m live` بعد از افزودن API key.

---

## Milestone 3 — One-source Evidence Pipeline

**وضعیت: انجام‌شده**

```text
ParsedDocument
→ stable semantic blocks
→ Document Map
→ AnalysisProfile
→ output-aware extraction plan
→ block-scoped evidence
→ deterministic validation
→ Claim Ledger
```

Gateها:

- supporting excerpt در target block وجود دارد؛
- locator معتبر است؛
- claim بدون evidence ساخته نمی‌شود؛
- selected/deferred blockها ثبت می‌شوند؛
- durationهای مختلف block identity را تغییر نمی‌دهند.

---

## Milestone 4 — Episode Preparation

**وضعیت: انجام‌شده**

```text
Claim Ledger
→ Coverage Audit
→ Claim Priorities
→ Deterministic Budget Report
→ Disagreement Graph
→ Episode Plan with prerequisites
→ direct evidence mapping
→ SQLite FTS5 context retrieval
→ Segment Evidence Packs
```

Gateها:

- corpus حداقل ۸۰٪ مدت هدف را پشتیبانی می‌کند؛
- must-include حذف نمی‌شود؛
- prerequisite پیش از claim وابسته می‌آید و در domain نهایی باقی می‌ماند؛
- claim تکراری و omission بی‌دلیل رد می‌شوند؛
- FTS context evidence جدید ایجاد نمی‌کند؛
- project فقط پس از ساخت همه packها `episode_planned` می‌شود.

Calibration:

- `budget-report.json` فرض‌ها را ثبت می‌کند؛
- `record-budget-calibration` نتایج واقعی script را جمع می‌کند؛
- حداقل سه نمونه pass‌شده برای بازبینی defaultها لازم است؛
- defaultها خودکار تغییر نمی‌کنند.

---

## Milestone 5 — Verified Persian Script

**وضعیت: انجام‌شده**

```text
Episode Plan + Evidence Packs
→ Bilingual Glossary
→ Persian Script per Segment
→ Deterministic Checks
→ Adversarial Verifier
→ one Targeted Revision at most
→ Checks + Verification again
→ script_verified
```

Gateها:

- turn محتوایی claim ID و evidence ID دارد؛
- claim فقط از همان segment است؛
- evidence فقط از همان pack است؛
- glossary consistency، repetition، prompt leakage و duration کنترل می‌شوند؛
- verifier pass فقط با zero issues و unsupported ratio صفر معتبر است؛
- reviser speaker یا ID جدید وارد نمی‌کند؛
- turn سالم تغییر نمی‌کند؛
- شکست بعد از یک revision pipeline را متوقف می‌کند.

مستند: [`15-persian-script-pipeline.md`](15-persian-script-pipeline.md)

---

## Milestone 6 — TTS Vertical Slice

**وضعیت: گام بعدی**

هدف: `script_verified` را به صوت فارسی verified تبدیل کن.

کد موردنیاز:

```text
src/thesisound/ports/tts.py
src/thesisound/ports/asr.py
src/thesisound/adapters/gemini/tts.py
src/thesisound/adapters/gemini/asr.py
src/thesisound/services/tts_segmenter.py
src/thesisound/services/audio_artifact_store.py
src/thesisound/services/audio_validator.py
src/thesisound/services/audio_qa.py
src/thesisound/services/audio_assembler.py
src/thesisound/audio_cli.py
```

جریان:

```text
Verified Script
→ TTS-safe segments
→ speech synthesis
→ WAV structural validation
→ ASR transcription
→ expected-vs-ASR semantic comparison
→ regenerate defective segments only
→ FFmpeg normalize and concatenate
→ audio_verified
```

Definition of Done:

- هر audio segment idempotency hash دارد؛
- prompt یا direction خوانده نمی‌شود؛
- sentence مهم حذف، تکرار یا truncate نشده؛
- speaker swap رخ نداده؛
- pronunciationهای glossary audit می‌شوند؛
- فقط segment معیوب regenerate می‌شود؛
- خروجی نهایی duration و loudness قابل قبول دارد؛
- blind listening test ثبت می‌شود.

---

## Milestone 6.5 — Local Operator UI

**وضعیت: پس از اثبات TTS vertical slice و پیش از گسترش scope پژوهش**

هدف: pipeline موجود را بدون بازنویسی domain یا orchestration، از طریق یک رابط محلی قابل اجرا، مشاهده، بازبینی و recovery کن.

### stack پیشنهادی

- FastAPI؛
- Jinja2؛
- HTMX؛
- CSS محدود یا Tailwind؛
- server-rendered read model؛
- polling برای runهای فعال؛
- بدون SPA و state store سمت browser.

### scope v0.1

- project list و create project؛
- Research Brief review/confirmation؛
- upload، inspection، parse report و parser retry؛
- corpus confirmation؛
- اجرای stage بعدی یا full available slice تا human gate؛
- project/stage/run status؛
- artifact inspection؛
- error recovery و retry؛
- coverage و Episode Plan review؛
- Script، verifier issue و source trace؛
- settings/diagnostics محلی.

### scope v0.2 پس از TTS

- audio segment status؛
- player؛
- ASR diff؛
- targeted regeneration؛
- Audio QA؛
- final package export.

### non-goals

- authentication و account؛
- multi-tenancy؛
- billing؛
- collaboration؛
- public sharing؛
- mobile app؛
- end-user onboarding؛
- design system کامل؛
- منطق state مستقل از domain.

### قواعد معماری

- UI فقط application command اجرا می‌کند؛
- browser state را حدس نمی‌زند؛
- actionهای مجاز از server می‌آیند؛
- هر POST idempotency دارد؛
- project در هر لحظه حداکثر یک run mutating فعال دارد؛
- تغییر upstream impact summary و stale marking دارد؛
- retry attempt جدید می‌سازد و history را overwrite نمی‌کند؛
- human gate با `run all` دور زده نمی‌شود.

### Definition of Done

- operator بدون مراجعه به CLI یک پروژه one-source را تا خروجی صوت verified اجرا کند؛
- در هر لحظه stage، failure و action بعدی روشن باشد؛
- service restart باعث گم‌شدن run و state نشود؛
- source parse با parser جایگزین از UI retry شود؛
- corpus insufficiency راه‌حل مشخص داشته باشد؛
- trace از script turn تا source locator حداکثر سه interaction بخواهد؛
- هیچ artifact ناقص project state را جلو نبرد؛
- integration test برای state/action matrix وجود داشته باشد.

اسناد UX:

- [`16-operator-user-workflow.md`](16-operator-user-workflow.md)
- [`17-interface-state-model.md`](17-interface-state-model.md)
- [`18-operator-screen-inventory.md`](18-operator-screen-inventory.md)
- [`19-error-and-recovery-ux.md`](19-error-and-recovery-ux.md)

---

## Milestone 7 — Source Discovery

**وضعیت: پس از TTS vertical slice و Operator UI پایه**

- query planner؛
- OpenAlex و Crossref؛
- Firecrawl/web extraction؛
- Google Books/Open Library؛
- normalization و deduplication؛
- source role و authority؛
- تفکیک metadata، full text و usable evidence؛
- انتخاب صریح کاربر؛
- search round و budget محدود.

Source discovery نباید قبل از اثبات کیفیت end-to-end صوت، scope پروژه را گسترش دهد. Operator UI پایه نیز باید آماده باشد تا candidateها، selection gate و خطاهای retrieval بدون اضافه‌کردن workflow موازی مدیریت شوند.

---

## Milestone 8 — Multi-source Reconciliation

- source-role-aware claim reconciliation؛
- semantic disagreement edges؛
- attribution-aware synthesis؛
- source budget allocation؛
- gap search؛
- incremental profile upgrade؛
- reuse evidence معتبر قبلی؛
- جلوگیری از dominance یک source یا consensus جعلی.

Disagreement Graph فعلی stanceهای صریح را نگه می‌دارد؛ relationهای semantic میان claimها در این milestone ساخته می‌شوند.

---

## Milestone 9 — End-user Product UI و Deployment

فقط پس از تثبیت workflow در Operator UI و اجرای موفق چند پروژه واقعی:

- تجربه ساده‌شده ساخت پروژه؛
- upload و source selection کاربرپسند؛
- نمایش اثر duration بر هزینه، پوشش و omission پیش از اجرا؛
- progress بدون جزئیات مهندسی اضافی؛
- episode/script review متناسب با کاربر غیرمتخصص؛
- player، transcript و source/locator trace؛
- privacy و data lifecycle controls؛
- authentication و hosted private deployment در صورت نیاز؛
- onboarding و empty states محصولی؛
- accessibility و responsive design؛
- telemetry محصول با حفظ privacy.

End-user UI نباید APIهای داخلی Operator UI را بدون boundary عمومی expose کند. ابتدا use caseها و permission model مستقل تعریف شوند.
