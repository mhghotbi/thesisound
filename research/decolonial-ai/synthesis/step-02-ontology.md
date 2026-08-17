# Step 02 — Ontology and Taxonomy Resolution

Date: 2026-08-17
Status: completed — provisional pending Step 03 verification
Inputs:
- `research/decolonial-ai/RESEARCH_WORKFLOW.md`
- `research/decolonial-ai/synthesis/step-01-source-audit.md`
- `research/decolonial-ai/deep-research/inputs/2026-08-17-batch-01.md`
- `research/decolonial-ai/deep-research/inputs/2026-08-17-batch-02.md`
- `research/decolonial-ai/deep-research/inputs/2026-08-17-batch-03.md`

Method constraint: no external web/source verification in this step. Decisions below are structural syntheses of the stored inputs and therefore remain provisional where canonicality is at issue.

## 1. Core decision: do not build one taxonomy tree

The three research agents repeatedly mixed objects of different ontological types. A single tree therefore creates false sibling relations: e.g. `Political Economy`, `labor`, `epistemic power`, and `public compute` cannot all be peer nodes because one is a literature, one is an empirical site, one is a mechanism of power, and one is a response family.

### Decision
The canonical field map will use **one primary map plus four orthogonal overlays**.

1. **L — Literature / intellectual-tradition map**: which bodies of scholarship explain the problem?
2. **S — AI stack / empirical-site map**: where in the AI production system does the relation occur?
3. **P — Power-mechanism map**: through what mechanism is power produced or exercised?
4. **R — Response / alternative map**: what type of intervention or counter-structure is proposed?
5. **C — Case-position / geopolitical-position overlay**: what role does a country/community/region occupy in the system?

### Why this choice
- It resolves most apparent disagreements without deleting substantive issues.
- It prevents `labor`, `chips`, `language`, or `standards` from being mistaken for intellectual traditions.
- It allows the same object to participate in multiple relations.
- It makes later Thesisound research composable: one can combine a literature, a site, a power mechanism, a response, and a case position.

# 2. Primary map: literature / intellectual traditions (L)

## L1. Political Economy of Digital / AI Capitalism
Core question: how ownership, accumulation, rent, IP, vertical integration, platform power, and corporate concentration structure AI.
Why first-order: distinct causal question about accumulation and ownership, not reducible to infrastructure, dependency, or sovereignty.
Includes/adjacent: Political Economy of Communication, Platform Capitalism, Intellectual Monopoly, competition/antitrust, Digital Labor where value extraction is central.

## L2. Critical AI / Critical Data Studies / STS
Core question: how sociotechnical systems classify, normalize, materialize, and distribute power; how technical systems embed institutions, histories, practices, labor, and categories.
Why first-order: distinct sociotechnical explanatory tradition and methodology.
Boundary: Critical Data Studies is represented as a major subfamily here until Step 03 tests whether it should be split.

## L3. Infrastructure Studies / Material AI / Political Ecology of AI
Core question: how AI depends on material and organizational infrastructures: minerals, energy, chips, data centers, compute, cloud, logistics, software stacks, and maintenance.
Why separate from L1: ownership/value capture and material/organizational dependence are different causal questions. Dependency can remain severe even with multiple nominal suppliers.
Boundary: political ecology/environmental work remains nested provisionally.

## L4. Postcolonial / Decolonial Technology Studies & Computing
Core question: how histories and structures of coloniality, hierarchy, development, knowledge, language, and externally imposed technological systems persist or are reproduced through technology.
Includes/interfaces: Postcolonial Computing, Decolonial AI, coloniality of data / algorithmic coloniality, epistemic and linguistic coloniality.
Why first-order: distinct genealogy and explanatory vocabulary.
Boundary: not the parent of the whole field; it does not by itself explain market structure, semiconductor bottlenecks, or public-infrastructure financing.

## L5. Dependency / Development / Technological Capability
Core question: how asymmetric productive/technological capabilities are reproduced such that actors can access or consume technology without controlling critical capabilities.
Decision: elevate to first-order.
Reason: fills a causal gap not covered by Political Economy, Infrastructure, or Sovereignty. It explains persistence of capability asymmetry.
Key working distinctions: concentration ≠ dependency ≠ vulnerability ≠ coercibility ≠ sovereignty/autonomy. These distinctions need Step 03 verification.

## L6. International Political Economy / Geoeconomics / Security of Technology
Core question: how states and network-central actors use supply chains, bottlenecks, standards, finance, export controls, infrastructure, and alliances as strategic power or coercion.
Includes/interfaces: Weaponized Interdependence, semiconductor geopolitics, techno-nationalism/techno-blocs, technology-security studies, military innovation as adjacent bodies.
Why first-order: coercion through network position is different from corporate monopoly or generic dependency.

## L7. Digital / Technological / Data / AI Sovereignty & Strategic Autonomy
Core question: what meaningful control or capacity over data, infrastructure, technological capabilities, or AI systems should exist, and for whom.
Decision: first-order response-oriented literature family, separate from Dependency.
Reason: dependency is diagnostic/explanatory; sovereignty concerns agency/control/response.
Required later decomposition: object (data/cloud/compute/technology/AI stack), subject (state/region/public institution/individual/community/Indigenous nation/commons), mode (jurisdiction/ownership/capability/resilience/exit capacity).

## L8. Indigenous Data Sovereignty / Community Data Governance
Core question: how collective self-determination, authority, responsibility, benefit, and governance over data can be structured outside purely corporate or state-centric models.
Decision: keep first-order despite overlap with L4/L7.
Reason: clearest counterexample in the inputs to the claim that decolonial work only diagnoses problems; combines a distinct normative genealogy with concrete governance principles and challenges state-only sovereignty.
Boundary: do not subsume Indigenous sovereignty into generic commons language.

## L9. Public / Commons / Industrial Alternative-Building Literatures
Core question: how alternative ownership, provisioning, financing, governance, interoperability, and capability institutions can be built for compute, models, data, cloud, and platforms.
Status: first-order solution-family, not one coherent discipline.
Includes: Public Compute, Public AI, relevant Digital Public Infrastructure, Data Commons/Trusts/Stewardship, Platform Cooperativism/Governable Stacks, industrial policy/public investment/capability building, regional compute pooling, interoperability/portability/exit rights.
Why top-level despite heterogeneity: the project explicitly needs to map movement from diagnosis to alternatives; burying this work would reproduce a diagnosis-heavy structure.
Warning: Step 03 must verify which names are canonical scholarly literatures versus recent policy labels.

# 3. Named interface/subfield: Data / Digital Colonialism

Decision: `Data Colonialism / Digital Colonialism / Digital Extractivism` is not a universal parent and is not yet a top-level peer literature.
Placement: named interface / second-order concept family spanning L1 Political Economy, L2 Critical Data/STS, and L4 Postcolonial/Decolonial technology studies.
Reason: all inputs recognize it, but disagree on disciplinary independence. Interface status preserves its vocabulary/canon without prematurely claiming equivalence with Political Economy, STS, or IPE.
Step-03 question: does citation/genealogy evidence justify promotion to first-order?

# 4. AI stack / empirical-site overlay (S)

S1 Minerals/raw materials
S2 Energy/water/physical resources
S3 Semiconductor design, fabrication, equipment, packaging
S4 Accelerators/compute hardware
S5 Data centers/HPC/compute capacity
S6 Cloud infrastructure/services
S7 Software stack/frameworks/proprietary interfaces
S8 Foundation models/model layer
S9 Data/datasets/data pipelines
S10 Human labor — annotation, moderation, verification, RLHF-related work, operations
S11 Language/knowledge/evaluation — language coverage, tokenization, benchmarks, categories/taxonomies
S12 Applications/platforms/distribution
S13 Standards/protocols/certification/governance interfaces

Labor decision: S10 central empirical site; Digital Labor/Sociology remains a neighboring literature linked mainly to L1/L2/L4, not a top-level field node here.
Language/epistemic decision: S11 major empirical site/domain, interpreted through L2/L4 and neighboring NLP/sociolinguistics, not a peer field cluster.
Standards decision: explicit S13 because rule-setting can generate dependency/lock-in without ownership; Standardization Studies remains a neighboring literature pending verification.

# 5. Power-mechanism overlay (P)

## P1. Economic / ownership / appropriative power
Possible mechanisms: monopoly/oligopoly, rent extraction, IP control, vertical integration, enclosure/appropriation, labor exploitation, data extraction.

## P2. Infrastructural / dependency power
Possible mechanisms: bottlenecks, lock-in, switching costs, supplier dependence, software-stack dependence, lack of endogenous capability, standards dependence.

## P3. Coercive / security power
Possible mechanisms: denial of access, export restrictions, surveillance/policing/censorship where coercive capacity is relevant, military integration, strategic use of network centrality.

## P4. Epistemic / constitutive power
Possible mechanisms: classification, normalization, linguistic hierarchy, benchmark/default-setting, representation/legibility, privileging particular knowledge systems/categories.

Decision on four vs five: use four mechanisms, not a fifth `labor/material` category.
Reason: P1–P4 are forms/mechanisms of power; labor, minerals, energy, and other material components are sites/resources through which mechanisms operate. Making them siblings would recreate the original ontology error.
Unresolved edge: domestic surveillance/disciplinary control is provisionally nested in P3; Step 03 should test whether a distinct administrative/disciplinary submechanism or P5 is necessary.

# 6. Response / alternative overlay (R)

R1 Regulation / competition / anti-lock-in — antitrust, interoperability, portability, procurement rules, exit rights.
R2 Public provision / public infrastructure — Public Compute, Public AI, public/regional cloud, shared compute facilities.
R3 Capability building / industrial policy — skills, R&D, procurement, hardware/software/model capability.
R4 Open ecosystems — open source, open weights, open standards, open hardware. Warning: openness ≠ sovereignty/public control.
R5 Commons / cooperative / stewardship governance — data commons, trusts/stewardship, platform cooperatives, governable stacks.
R6 Community / Indigenous governance — collective authority, community-defined use, CARE-type principles. Warning: do not collapse into generic commons.
R7 Privacy-preserving / distributed technical architectures — federated learning, PPML, P2P/local architectures where relevant. Warning: technical decentralization ≠ democratic governance or anti-monopoly.
R8 Resilience / diversification / managed interdependence — supplier diversification, regional pooling, redundancy, substitutability, reduced single-point dependence, local/offline continuity where it genuinely affects dependency.

Working hypothesis preserved for Step 03: a useful practical target may often be `exit capacity / substitutability / resilience` rather than full autarkic sovereignty.

# 7. Case-position / geopolitical-position overlay (C)

`Global South` is not a top-level actor or homogeneous category.
A case may occupy multiple positions simultaneously:
C1 data-source/extraction site
C2 outsourced labor site
C3 mineral/energy/ecological extraction site
C4 linguistic/epistemic periphery
C5 cloud/model/compute dependent market
C6 standards/regulatory rule-taker
C7 geopolitically coercible/vulnerable actor
C8 regional/sub-hegemonic technology power
C9 capability-building middle power
C10 site of community/Indigenous/public alternatives

Reason: enables layer-by-layer comparison without forcing a West-vs-Global-South binary.

# 8. Resolution of Step-01 disputes

D1 Data/Digital Colonialism — second-order named interface pending verification. Reason: important recognizable vocabulary, independence disputed.
D2 Political Economy vs Infrastructure — separate L1/L3. Reason: accumulation/ownership and material/organizational dependence are distinct causal questions.
D3 Dependency/Development/Capability — first-order L5. Reason: explains reproduced capability asymmetry and prevents collapsing diagnosis into sovereignty rhetoric.
D4 Labor — S10 site + neighboring literature; not top-level field node. Reason: centrality does not determine ontological type.
D5 Epistemic/Linguistic power — P4 mechanism + S11 site/domain; mainly interpreted through L2/L4 and neighboring sociolinguistics/NLP.
D6 Military-tech nexus — cross-cutting interface connecting L1/L3/L6 and P3; not peer top-level literature.
D7 Standards/private rule-making — explicit S13 layer/interface + links to L3/L6/L7; Standardization Studies to verify.
D8 Four vs five power dimensions — four mechanism categories P1–P4; material/labor/ecological components belong in S overlay.

# 9. Provisional primary literature map

1. L1 Political Economy of Digital / AI Capitalism
2. L2 Critical AI / Critical Data Studies / STS
3. L3 Infrastructure Studies / Material AI / Political Ecology
4. L4 Postcolonial / Decolonial Technology Studies & Computing
5. L5 Dependency / Development / Technological Capability
6. L6 IPE / Geoeconomics / Security of Technology
7. L7 Digital / Technological / Data / AI Sovereignty & Strategic Autonomy
8. L8 Indigenous Data Sovereignty / Community Data Governance
9. L9 Public / Commons / Industrial Alternative-Building Literatures

Named second-order interface:
- Data / Digital Colonialism / Digital Extractivism across L1 + L2 + L4

Cross-cutting neighboring literatures to verify rather than promote prematurely:
- Digital Labor / Sociology of Work
- Standardization Studies / private rule-making
- Competition / antitrust
- sociolinguistics / low-resource NLP
- military innovation / national-security technology studies
- environmental humanities / political ecology where not already nested in L3

# 10. Why the canonical artifact should contain multiple linked views

For Thesisound, a useful research question can later be represented as:
`Literature (L) × Site (S) × Power mechanism (P) × Response (R) × Case position (C)`

This is more precise than a generic topic such as `postcolonial AI` and allows future source gathering and episode design without mixing levels.

# 11. Decisions deferred to Step 03

1. whether Data/Digital Colonialism should be promoted from interface to first-order literature;
2. how independent Critical Data Studies should be from STS/Critical AI;
3. whether Infrastructure Studies / Material AI has a sufficiently coherent canon to remain first-order exactly as named;
4. strength/direct applicability of classical Dependency Theory to contemporary AI capability;
5. whether AI sovereignty, compute sovereignty, Public AI, and Public Compute are stable scholarly literatures or mainly emerging policy vocabularies;
6. whether Standardization Studies deserves literature-map promotion;
7. whether the military-tech nexus has matured into a coherent subfield;
8. whether domestic surveillance/disciplinary power requires a distinct P5 mechanism;
9. exact boundaries among data sovereignty, Indigenous data sovereignty, commons, trusts, stewardship, and open-data regimes;
10. which recent market/policy facts are reliable/current enough for final use.

# 12. Step-02 conclusion

The field should not be represented as an eight- or nine-branch tree mixing heterogeneous objects.
Working ontology:
- L: literatures/traditions
- S: AI stack/empirical sites
- P: mechanisms of power
- R: responses/alternatives
- C: case positions

This resolves the structural disagreements among the three agent reports while preserving their substantive insights. Step 03 must verify the intellectual/bibliographic status of proposed L nodes, named interfaces, and high-risk concepts before any rewrite of `field-map.md`.
