"""Deterministic Context Store update for externally generated extraction results."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.context_engine.application.context_store import merge_extraction
from app.modules.context_engine.domain.context_store import ContextStoreState
from app.modules.context_engine.domain.extraction import ExtractionResult
from app.modules.context_engine.domain.ontology import ContextKind


class KeylessContextUpdater:
    async def update(
        self,
        state: ContextStoreState,
        result: ExtractionResult,
        *,
        source_id: UUID,
        source_title: str,
        text: str,
    ) -> tuple[ContextStoreState, list[str]]:
        """Merge grounded facts without asking a server model to rewrite the narrative."""
        merged = merge_extraction(state, result, source_id)
        summaries = [
            context.body.strip()
            for context in result.contexts
            if context.kind is ContextKind.SUMMARY and context.body.strip()
        ]
        warnings: list[str] = []
        if summaries and summaries[0] not in state.summary:
            addition = f"{source_title}: {summaries[0]}"
            combined = f"{state.summary}\n\n{addition}" if state.summary else addition
            if len(combined) <= 20_000:
                merged.summary = combined
            else:
                # The source's facts and timeline are still persisted. Never
                # discard earlier workspace narrative to fit a newer summary.
                warnings.append("Workspace summary is full; source facts were saved")
        if not state.current_state and summaries:
            merged.current_state = summaries[0]
        merged.updated_at = datetime.now(UTC)
        return merged, warnings
