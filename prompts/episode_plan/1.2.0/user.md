<RESEARCH_BRIEF_JSON>
{{ research_brief }}
</RESEARCH_BRIEF_JSON>

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

<EXTRACTION_PLANS_JSON>
{{ extraction_plans }}
</EXTRACTION_PLANS_JSON>

<DEFINITIONS_JSON>
{{ definitions }}
</DEFINITIONS_JSON>

<DISTINCTIONS_JSON>
{{ distinctions }}
</DISTINCTIONS_JSON>

<EXAMPLES_JSON>
{{ examples }}
</EXAMPLES_JSON>

<OBJECTIONS_JSON>
{{ objections }}
</OBJECTIONS_JSON>

<RESPONSES_JSON>
{{ responses }}
</RESPONSES_JSON>

Create a coherent episode plan for the requested duration. Use claim IDs exactly as supplied. Every selected claim must be included or deliberately omitted with a reason. Preserve explicit disagreement and qualification instead of collapsing them into consensus. Do not plan beyond the effective supported duration in the budget report. Draw on DEFINITIONS_JSON, DISTINCTIONS_JSON, EXAMPLES_JSON, OBJECTIONS_JSON, and RESPONSES_JSON for grounded texture; do not invent material in these categories beyond what is supplied.
