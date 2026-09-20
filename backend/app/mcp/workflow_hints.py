"""Machine-readable next steps for agent-owned source ingestion."""

from uuid import UUID


def next_step(workspace_id: UUID, source_id: UUID, *, kind: str, has_media: bool) -> dict:
    arguments = {"workspace_id": str(workspace_id), "source_id": str(source_id)}
    if has_media:
        return {
            "tool": "media_download_url",
            "arguments": arguments,
            "instruction": (
                "Read the uploaded media with your own tools. For a document, save extracted "
                "text with save_document_text before analysis. For a meeting, save a transcript "
                "and obtain the user's explicit confirmation before analysis."
            ),
        }
    if kind == "meeting":
        return {
            "tool": "source_content",
            "arguments": arguments,
            "instruction": (
                "Review the transcript with the user. Call confirm_transcript only after "
                "explicit approval, then continue to analysis_context and submit_analysis."
            ),
        }
    return {
        "tool": "analysis_context",
        "arguments": arguments,
        "instruction": (
            "Use your own model to extract grounded contexts, entities, events and relations "
            "from the source. Submit the complete extraction with submit_analysis. "
            "Report completion only when its phase is done."
        ),
    }
