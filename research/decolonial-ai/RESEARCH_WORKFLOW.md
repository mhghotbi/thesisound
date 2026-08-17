# Decolonial AI Research Workflow

Status: active
Last updated: 2026-08-17
Purpose: persistent working memory for the Thesisound research project on AI power, coloniality, dependency, sovereignty, and alternative infrastructure.

## Operating rule

This file is the source of truth for process and progress. Do not rely on chat memory for project state. Before starting any new step:
1. Read this file.
2. Read the output file from the immediately preceding step.
3. Execute only the current step.
4. Save the step output as a separate file under `research/decolonial-ai/synthesis/`.
5. Update this file with status, decisions, rationale, unresolved questions, and the next step.

Do not silently promote claims from agent outputs into the canonical map. External-agent batches are research inputs, not verified evidence.

## Persistent source inputs

- `research/decolonial-ai/deep-research/inputs/2026-08-17-batch-01.md`
- `research/decolonial-ai/deep-research/inputs/2026-08-17-batch-02.md`
- `research/decolonial-ai/deep-research/inputs/2026-08-17-batch-03.md`

Existing working map:
- `research/decolonial-ai/field-map.md`

The existing `field-map.md` is provisional and must be replaced only after the synthesis and verification stages are complete.

## Project objective

Build a canonical field map suitable for subsequent Thesisound episode research. The map should answer:
- What established literatures actually constitute this field?
- Which concepts are parent traditions, subfields, mechanisms, empirical layers, or proposed responses?
- How do coloniality, political economy, infrastructure, dependency, coercion, sovereignty, and alternatives relate without being conflated?
- Which terms are established in scholarship versus emerging policy language or agent-created synthesis labels?
- Where is diagnosis strong, and where do implementable institutional/technical alternatives live?

The current goal is field mapping, not episode planning and not a reading list.

## Quality rules

1. Separate intellectual traditions/literatures, AI system layers/empirical sites, mechanisms/forms of power, responses/alternatives, and case/geopolitical positions.
2. Preserve disagreement instead of averaging agent outputs.
3. Prefer causal and conceptual precision over a visually neat taxonomy.
4. Distinguish established terminology from emerging or synthetic terminology.
5. Verify primary/authoritative sources before canonical promotion.
6. Separate descriptive diagnosis from normative proposal.
7. Separate technical mechanisms from institutional/governance mechanisms.
8. Avoid treating `Global South`, `sovereignty`, `colonialism`, `open source`, or `decentralization` as internally uniform categories.
9. Current market figures and policy programs are time-sensitive and must be verified separately from conceptual literature.
10. Record reasons for every structural decision that affects the final map.

## Step plan

### Step 1 — Source audit and disagreement extraction
Status: COMPLETE
Output: `research/decolonial-ai/synthesis/step-01-source-audit.md`
Goal: compare the three agent outputs and isolate areas of agreement, disagreement, conflation, and uncertainty.
Completion criterion: a bounded list of disputes to resolve before source verification.

Key finding:
The main disagreement is not about whether the phenomena exist. The agents mix different ontological levels: literatures, AI stack layers, mechanisms of power, and responses. Therefore taxonomy cannot be resolved by voting across the three agent outputs.

Main disputes isolated:
1. taxonomic status of Data/Digital Colonialism
2. whether Political Economy and Infrastructure should be separate
3. whether Dependency/Development deserves an independent literature node
4. whether labor is a field, layer, substrate, or cross-cutting dimension
5. whether epistemic/linguistic power is a field or mechanism/dimension
6. whether military-tech is a standalone cluster or interface
7. whether Standards/private rule-making must be represented explicitly
8. four-dimension versus five-dimension model of power

### Step 2 — Resolve ontology and taxonomy
Status: COMPLETE — PROVISIONAL PENDING VERIFICATION
Output: `research/decolonial-ai/synthesis/step-02-ontology.md`
Goal: define a clean ontology before verification and resolve the eight disputes from Step 1 provisionally.
Method constraint: only stored research inputs + Step 1 audit; no external verification.
Completion criterion: MET.

Key structural decision:
Do not use one mixed taxonomy tree. Use five linked views:
- `L` literatures / intellectual traditions
- `S` AI stack / empirical sites
- `P` mechanisms of power
- `R` responses / alternatives
- `C` case/geopolitical positions

Provisional literature families:
1. Political Economy of Digital / AI Capitalism
2. Critical AI / Critical Data Studies / STS
3. Infrastructure Studies / Material AI / Political Ecology
4. Postcolonial / Decolonial Technology Studies & Computing
5. Dependency / Development / Technological Capability
6. IPE / Geoeconomics / Security of Technology
7. Digital / Technological / Data / AI Sovereignty & Strategic Autonomy
8. Indigenous Data Sovereignty / Community Data Governance
9. Public / Commons / Industrial Alternative-Building Literatures

Important provisional placements:
- Data/Digital Colonialism: named second-order interface spanning Political Economy, Critical Data/STS, and Decolonial/Postcolonial technology studies; canonical status to verify.
- Political Economy and Infrastructure: separate.
- Dependency/Development/Capability: first-order.
- Labor: central empirical site + neighboring literature, not a top-level peer field.
- Language/epistemic domain: empirical site + epistemic mechanism, not a peer field.
- Military-tech: cross-cutting interface.
- Standards: explicit stack/governance interface + neighboring literature to verify.
- Power model: four mechanism families retained provisionally; material/labor/ecological components remain sites/substrates.

Full rationale: `research/decolonial-ai/synthesis/step-02-ontology.md`.

### Step 3 — Primary-source verification
Status: NEXT — NOT STARTED
Output target: `research/decolonial-ai/synthesis/step-03-verification.md`
Goal: verify conceptual anchors, bibliographic details, taxonomic claims, disputed terminology, and selected critical empirical claims.
Method:
- prioritize original papers/books, academic publishers, official policy documents, and primary technical/policy sources
- verify canonicality/status, not merely existence
- verify recent empirical claims separately from historical concepts
Completion criterion: each canonical node and contested term receives a verification status, rationale, and source trail.

Minimum verification queue:
- Data Colonialism / Digital Colonialism taxonomic status
- Political Economy vs Infrastructure distinction
- technological dependency / capability literature as an independent lineage
- Postcolonial Computing / Decolonial AI genealogy
- Standards/private rule-making literature relevance
- military-tech / national-security nexus status
- Indigenous Data Sovereignty and CARE
- Public Compute / Public AI canonicality and maturity
- AI sovereignty / compute sovereignty status
- critiques of colonialism-as-metaphor
- open weights vs open source vs public infrastructure
- named synthetic terms from agents: `Sovereignty Trap`, `Polycentric Dependency`, `Sub-hegemonic Tech Hubs`, `Cloud Empires`, `Grassroots Sovereignty`
- whether domestic surveillance/disciplinary power requires a separate power category

### Step 4 — Canonical field map
Status: NOT STARTED
Output target: replace/rewrite `research/decolonial-ai/field-map.md`
Goal: synthesize verified traditions, mechanisms, layers, relations, debates, and alternatives into one durable map.
Completion criterion:
- no mixed ontological levels in top-level taxonomy
- provenance for anchor claims
- confidence/status labels for emerging areas
- clear diagnosis/response distinction

### Step 5 — Thesisound research axes
Status: NOT STARTED
Output target: `research/decolonial-ai/thesisound-research-axes.md`
Goal: convert canonical field map into a small number of research axes that can later be decomposed into evidence-grounded episodes.
Constraint: define research axes, not final episode titles or a production schedule.
Completion criterion: each axis has scope, exclusions, central questions, likely source families, and dependencies on other axes.

## Progress log

### 2026-08-17 — Workflow formalized
Decision: persist process state in this file and step outputs in separate files.
Reason: multiple long external-agent inputs and nontrivial taxonomic disputes make chat-memory-based continuation too drift-prone and hard to audit.

### 2026-08-17 — Step 1 completed
See `synthesis/step-01-source-audit.md`.
Reason for next step: ontology had to be resolved before verification or external research would reinforce inconsistent categories.

### 2026-08-17 — Step 2 completed
See `synthesis/step-02-ontology.md`.
Decision: use a five-view ontology (`L/S/P/R/C`) rather than a single tree.
Reason: agent outputs mixed intellectual traditions, empirical sites, power mechanisms, response families, and geopolitical positions. Separating these dimensions resolves most apparent contradictions while keeping substantive differences visible.

Decision reasons recorded in Step 2 include:
- ownership/accumulation differs causally from infrastructural dependence;
- dependency/capability must be separated from sovereignty so the map does not jump from concentration directly to policy response;
- labor/language/standards can be central without being the same ontological type as an intellectual tradition;
- military-tech is better treated as an interface among political economy, infrastructure, and security/IPE unless Step 3 proves a coherent independent canon;
- material/labor/ecological components are sites/substrates, not a fifth mechanism of power merely because they are important.

## Current step

STEP 3 — Primary-source verification.

Do not start Step 4 until Step 3 is saved and this file is updated to mark it complete.
