<SCRIPT_JSON>
{{ script }}
</SCRIPT_JSON>

<DETERMINISTIC_CHECKS_JSON>
{{ deterministic_checks }}
</DETERMINISTIC_CHECKS_JSON>

<EPISODE_PLAN_JSON>
{{ episode_plan }}
</EPISODE_PLAN_JSON>

<EVIDENCE_PACKS_JSON>
{{ evidence_packs }}
</EVIDENCE_PACKS_JSON>

<GLOSSARY_JSON>
{{ glossary }}
</GLOSSARY_JSON>

<DISAGREEMENT_GRAPH_JSON>
{{ disagreement_graph }}
</DISAGREEMENT_GRAPH_JSON>

<CLAIMS_JSON>
{{ claims }}
</CLAIMS_JSON>

<PLAN_MUST_INCLUDE_JSON>
{{ plan_must_include }}
</PLAN_MUST_INCLUDE_JSON>

<KNOWN_CONCEPTS>
{{ known_concepts }}
</KNOWN_CONCEPTS>

Audit the script turn by turn. Treat deterministic failures as evidence, not suggestions to ignore. Check whether spoken wording remains within the supplied evidence and preserves source stance. Return pass only when no issue remains and unsupported_claim_ratio is zero. Return all five 0–1 quality scores and one actionable_feedback sentence.
