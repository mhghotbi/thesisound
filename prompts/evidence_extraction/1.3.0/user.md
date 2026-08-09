<SOURCE_ID>
{{ source_id }}
</SOURCE_ID>

<WORKING_THESIS>
{{ working_thesis }}
</WORKING_THESIS>

<ANALYSIS_PROFILE_JSON>
{{ analysis_profile }}
</ANALYSIS_PROFILE_JSON>

<SECTION_CONTEXT_JSON>
{{ section_context }}
</SECTION_CONTEXT_JSON>

<NEIGHBOR_CONTEXT_JSON>
{{ neighbor_context }}
</NEIGHBOR_CONTEXT_JSON>

<TARGET_SEMANTIC_BLOCK_JSON>
{{ block }}
</TARGET_SEMANTIC_BLOCK_JSON>

Extract evidence at the depth allowed by the analysis profile. Claims and supporting excerpts must be grounded only in TARGET_SEMANTIC_BLOCK_JSON. If the target block does not support a substantive claim, return an empty claims list and preserve useful unresolved context within the allocated budget.
