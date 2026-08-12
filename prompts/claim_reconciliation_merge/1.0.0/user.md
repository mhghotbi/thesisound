Merge the following already-reconciled claim batches for one source. Group only claim
IDs that are the same proposition across batches.

<SOURCE_ID>
{{ source_id }}
</SOURCE_ID>

<BATCH_COUNT>
{{ batch_count }}
</BATCH_COUNT>

<CLAIMS_JSON>
{{ claims }}
</CLAIMS_JSON>

Return merge_groups of claim IDs that should become one claim, and any warnings.
