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

Audit the script turn by turn. Treat deterministic failures as evidence, not suggestions to ignore. Check whether spoken wording remains within the supplied evidence and preserves source stance. Return pass only when no issue remains and unsupported_claim_ratio is zero.
