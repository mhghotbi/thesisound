<TARGET_TURNS_JSON>
{{ target_turns }}
</TARGET_TURNS_JSON>

<DETERMINISTIC_ISSUES_JSON>
{{ deterministic_issues }}
</DETERMINISTIC_ISSUES_JSON>

<VERIFICATION_ISSUES_JSON>
{{ verification_issues }}
</VERIFICATION_ISSUES_JSON>

<EVIDENCE_PACKS_JSON>
{{ evidence_packs }}
</EVIDENCE_PACKS_JSON>

<GLOSSARY_JSON>
{{ glossary }}
</GLOSSARY_JSON>

Revise every target turn exactly once. Keep its turn ID and speaker. Use only a subset of the original claim IDs and evidence IDs; never introduce new IDs. Remove or narrow unsupported content rather than compensating with outside knowledge.
