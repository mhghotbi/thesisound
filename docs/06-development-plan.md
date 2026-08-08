# 06 — برنامه توسعه

## راهبرد

ترتیب توسعه بر اساس ریسک است، نه جذابیت UI:

```text
input fidelity
→ evidence fidelity
→ episode sufficiency
→ script fidelity
→ audio fidelity
→ discovery and multi-source breadth
→ UI and deployment
```

قواعد سراسری:

- parse، block ID و locator مستقل از duration هستند؛
- breadth/depth evidence و episode به duration وابسته‌اند؛
- مدل هیچ ID یا locator معتبری نمی‌سازد؛
- متن اصلی source of truth است؛
- corpus ناکافی با padding جبران نمی‌شود؛
- writer تنها verifier خروجی خودش نیست؛
- هر stage artifact، gate و failure state مستقل دارد.

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

## Milestone 7 — Source Discovery

**وضعیت: پس از TTS vertical slice**

- query planner؛
- OpenAlex و Crossref؛
- Firecrawl/web extraction؛
- Google Books/Open Library؛
- normalization و deduplication؛
- source role و authority؛
- تفکیک metadata، full text و usable evidence؛
- انتخاب صریح کاربر؛
- search round و budget محدود.

Source discovery نباید قبل از اثبات کیفیت end-to-end صوت، scope پروژه را گسترش دهد.

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

## Milestone 9 — Local Web UI

فقط بعد از استفاده موفق CLI:

- FastAPI؛
- Jinja2/HTMX؛
- create project؛
- upload و parse report؛
- source selection؛
- duration/mode settings؛
- progress و artifact inspection؛
- episode/script review؛
- player و transcript؛
- source/locator trace.

UI باید اثر duration بر هزینه، پوشش و omission را پیش از اجرا نشان دهد.

---

## Milestone 10 — Persistence، Jobs و Deployment

فقط وقتی usage واقعی نیاز را اثبات کرد:

- SQLite repository و job table؛
- resumable stage runner؛
- block/model/audio cache؛
- cleanup و delete project؛
- private deployment؛
- object storage؛
- access control؛
- PostgreSQL/Redis فقط با نیاز concurrency واقعی.

---

## کار بعدی دقیق

گام بعدی توسعه **TTS + ASR + Audio QA vertical slice** است. Source Discovery و UI تا زمانی که یک source واقعی به صوت فارسی verified تبدیل نشده، اولویت ندارند.
