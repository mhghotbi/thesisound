from thesisound.services.model_runner import grounding_policy_for_stage


def test_grounding_policy_enables_only_research_and_discovery_stages() -> None:
    assert grounding_policy_for_stage("research_brief") == "google_search_and_url_context"
    assert grounding_policy_for_stage("query_planner") == "google_search"
    assert grounding_policy_for_stage("source_discovery") == "google_search_and_url_context"
    assert grounding_policy_for_stage("source_triage") == "url_context"


def test_grounding_policy_keeps_evidence_and_script_stages_source_bound() -> None:
    assert grounding_policy_for_stage("document_map") == "none"
    assert grounding_policy_for_stage("evidence_extraction") == "none"
    assert grounding_policy_for_stage("claim_reconciliation") == "none"
    assert grounding_policy_for_stage("glossary") == "none"
    assert grounding_policy_for_stage("episode_plan") == "none"
    assert grounding_policy_for_stage("persian_script_segment") == "none"
    assert grounding_policy_for_stage("script_verifier") == "none"
