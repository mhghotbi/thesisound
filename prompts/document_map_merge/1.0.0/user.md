Merge the following complete partition maps into a global document map.

Source ID: {{ source_id }}
Partition count: {{ partition_count }}

Partition maps:
{{ partitions | tojson }}

Return:
- one working thesis for the mapped scope, if supported;
- only cross-partition dependency or unresolved-context updates;
- globally required section IDs;
- cross-section threads that may span multiple partitions;
- warnings for unresolved discontinuities or scope limitations.
