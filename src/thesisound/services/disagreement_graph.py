from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from thesisound import tracing
from thesisound.domain import ClaimRecord, EvidenceItem, SupportStatus
from thesisound.episode import (
    DisagreementGraph,
    DisagreementNode,
    DisagreementSourcePosition,
)


class DisagreementGraphBuilder:
    """Materialize explicit source stances without inventing semantic relations."""

    def build(
        self,
        *,
        project_id: UUID,
        claims: list[ClaimRecord],
        evidence_items: list[EvidenceItem],
    ) -> DisagreementGraph:
        with tracing.span(
            "episode.build_disagreement_graph", component="episode", project_id=project_id
        ) as span:
            source_by_evidence = {item.evidence_id: item.source_id for item in evidence_items}
            nodes: list[DisagreementNode] = []
            warnings: list[str] = []

            for claim in claims:
                positions: dict[UUID, str] = {}
                supporting_sources = {
                    source_by_evidence[evidence_id]
                    for evidence_id in claim.evidence_ids
                    if evidence_id in source_by_evidence
                }
                supporting_sources.update(claim.agreeing_source_ids)
                for source_id in supporting_sources:
                    positions[source_id] = "supports"
                for source_id in claim.disagreeing_source_ids:
                    positions[source_id] = "disputes"

                contested_without_sources = (
                    claim.support_status == SupportStatus.CONTESTED
                    and not claim.disagreeing_source_ids
                )
                if contested_without_sources:
                    warnings.append(
                        f"Claim {claim.claim_id} is contested but has no explicit "
                        "disagreeing source IDs."
                    )
                if len(positions) <= 1 and claim.support_status != SupportStatus.CONTESTED:
                    continue

                evidence_by_source: dict[UUID, list[str]] = defaultdict(list)
                for evidence_id in claim.evidence_ids:
                    source_id = source_by_evidence.get(evidence_id)
                    if source_id is not None:
                        evidence_by_source[source_id].append(evidence_id)
                nodes.append(
                    DisagreementNode(
                        claim_id=claim.claim_id,
                        statement=claim.claim,
                        positions=[
                            DisagreementSourcePosition(
                                source_id=source_id,
                                stance=stance,
                                evidence_ids=evidence_by_source.get(source_id, []),
                            )
                            for source_id, stance in sorted(
                                positions.items(), key=lambda item: str(item[0])
                            )
                        ],
                        qualifications=claim.qualifications,
                    )
                )

            span.measure(claim_count=len(claims), disagreement_node_count=len(nodes))
            return DisagreementGraph(
                project_id=project_id,
                nodes=nodes,
                edges=[],
                warnings=warnings,
            )
