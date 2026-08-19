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

Extract evidence at the depth allowed by the analysis profile. Every claim — including definitions, distinctions, examples, objections and responses — must be grounded only in TARGET_SEMANTIC_BLOCK_JSON with a verbatim excerpt. If the target block does not support a substantive claim, return an empty claims list rather than fabricating one. If the budget cut off distinct claims the block supports, set more_claims_available to true.
