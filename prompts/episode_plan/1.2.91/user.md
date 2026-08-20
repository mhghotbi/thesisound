<RESEARCH_BRIEF_JSON>
{{ research_brief }}
</RESEARCH_BRIEF_JSON>

<PART_JSON>
{{ part }}
</PART_JSON>

<SEGMENT_SKELETON_JSON>
{{ segment_skeleton }}
</SEGMENT_SKELETON_JSON>

<COVERAGE_REPORT_JSON>
{{ coverage_report }}
</COVERAGE_REPORT_JSON>

<BUDGET_REPORT_JSON>
{{ budget_report }}
</BUDGET_REPORT_JSON>

<DISAGREEMENT_GRAPH_JSON>
{{ disagreement_graph }}
</DISAGREEMENT_GRAPH_JSON>

<CLAIM_PRIORITIES_JSON>
{{ claim_priorities }}
</CLAIM_PRIORITIES_JSON>

<CLAIMS_JSON>
{{ claims }}
</CLAIMS_JSON>

<KNOWN_CONCEPTS>
{{ known_concepts }}
</KNOWN_CONCEPTS>

Create a coherent plan for this part. If a segment skeleton is supplied, keep it exactly and write only the narrative fields. Use claim IDs exactly as supplied. Every selected claim must be included or deliberately omitted with a reason; every must_not_be_lost claim must be included or explicitly omitted with a reason. Preserve explicit disagreement and qualification instead of collapsing them into consensus.
