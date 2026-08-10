Merge the following complete partition maps into a global document map.

<SOURCE_ID>
{{ source_id }}
</SOURCE_ID>

<PARTITION_COUNT>
{{ partition_count }}
</PARTITION_COUNT>

<PARTITION_MAPS_JSON>
{{ partitions }}
</PARTITION_MAPS_JSON>

Return:
- one working thesis for the mapped scope, if supported;
- only cross-partition dependency or unresolved-context updates;
- globally required section IDs;
- cross-section threads that may span multiple partitions;
- warnings for unresolved discontinuities or scope limitations.
