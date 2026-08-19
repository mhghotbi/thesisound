<SOURCE_ID>
{{ source_id }}
</SOURCE_ID>

<WORKING_THESIS>
{{ working_thesis }}
</WORKING_THESIS>

<ANALYSIS_PROFILE_JSON>
{{ analysis_profile }}
</ANALYSIS_PROFILE_JSON>

<TARGET_BLOCKS_JSON>
{{ blocks }}
</TARGET_BLOCKS_JSON>

Extract evidence for every target block at the depth allowed by the analysis profile.
Return exactly {{ block_count }} entries, one per block, each carrying that block's
`index` value as its block_index. Every claim — including definitions, distinctions,
examples, objections and responses — must be grounded only in the block it is
attributed to, with a verbatim excerpt. If a block does not support a substantive
claim, return its entry with an empty claims list rather than fabricating one. If the
budget cut off distinct claims a block supports, set that entry's more_claims_available
to true.
