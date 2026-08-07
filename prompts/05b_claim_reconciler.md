---
id: claim-reconciler
version: 1
model-tier: strong
output-model: list[ClaimRecord]
---

# Purpose

وصل‌کردن evidence claimهای مشابه به canonical claimها و ثبت relation میان آن‌ها، بدون حذف اختلاف و qualification.

# Before the model

Code باید ابتدا exact duplicate و near-duplicateهای روشن را با normalization خوشه‌بندی کند. مدل فقط clusterهای مبهم را می‌بیند.

# System instruction

```text
You reconcile evidence claims from one or more selected sources.

Your task is to identify semantic relationships, not to force consensus. For each candidate relation,
classify claims as one of:
- equivalent;
- narrower;
- broader;
- supports;
- contradicts;
- unrelated.

Merge claims only when their proposition, attribution, certainty and scope are materially equivalent.
Do not merge claims merely because they mention the same concept.

Preserve:
- source attribution;
- qualifications;
- temporal or contextual scope;
- interpretation versus primary-author position;
- criticism versus description;
- direct versus inferential support.

A canonical claim may reference multiple evidence IDs. Contradicting claims must remain separate and
be linked as disagreement. Do not decide which side is true unless the evidence corpus explicitly
supports such a conclusion and the task asks for it.

Use only supplied claims and evidence metadata. Do not add facts or repair missing evidence from
outside knowledge.
```

# User payload template

```text
<RESEARCH_BRIEF>
{{ research_brief_json }}
</RESEARCH_BRIEF>

<CANDIDATE_CLUSTERS>
{{ candidate_claim_clusters_json }}
</CANDIDATE_CLUSTERS>

<SOURCE_METADATA>
{{ source_metadata_json }}
</SOURCE_METADATA>
```

# Output contract

لیست `ClaimRecord` همراه با relation metadata در artifact stage.

هر canonical claim:

- claim type؛
- evidence IDs؛
- support status؛
- qualifications؛
- agreeing source IDs؛
- disagreeing source IDs.

# Validation

- evidence ID جدید ساخته نشده؛
- non-editorial claim بدون evidence نیست؛
- source IDها در input وجود دارند؛
- contradicting claimها به یک wording خنثی merge نشده‌اند؛
- primary position و interpretation merge نشده‌اند؛
- qualificationهای مشترک یا متفاوت ثبت شده‌اند.

# Failure examples

- «آرنت می‌گوید X» و «فلان پژوهشگر آرنت را چنین تفسیر می‌کند» equivalent اعلام شده‌اند؛
- دو claim با certainty متفاوت merge شده‌اند؛
- criticism به qualification تبدیل و اختلاف حذف شده؛
- canonical claim از wording مدل ساخته شده ولی evidence proposition آن را ندارد.

# Retry

یک retry برای invalid evidence/source IDs یا over-merge feedback. اگر relation همچنان مبهم است، claims جدا و relation=`uncertain` بماند.
