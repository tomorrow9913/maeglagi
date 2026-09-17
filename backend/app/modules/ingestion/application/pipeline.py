from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.core.credentials import CredentialUnavailableError, resolve_credential_secret
from app.modules.context_engine.application.provider import (
    EmbeddingRequest,
    ProviderAdapter,
    TranscriptionRequest,
    TranscriptionResponse,
)
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError
from app.modules.context_engine.infrastructure.provider_registry import provider_registry
from app.modules.ingestion.application.chunking import CharacterOverlapChunker
from app.modules.ingestion.application.normalization import NormalizationService
from app.modules.ingestion.domain.models import TranscriptSegment
from app.modules.workspaces.infrastructure.models import ProviderCredential, Source


class IngestionError(RuntimeError):
    pass


class IngestionPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.normalizer = NormalizationService()
        self.chunker = CharacterOverlapChunker(
            self.settings.chunk_size_chars, self.settings.chunk_overlap_chars
        )

    async def _provider(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        capability: str,
    ) -> tuple[ProviderAdapter, str]:
        result = await session.exec(
            select(ProviderCredential)
            .where(
                ProviderCredential.workspace_id == workspace_id,
                ProviderCredential.owner_id == owner_id,
                ProviderCredential.status == "active",
            )
            .order_by(ProviderCredential.is_default.desc(), ProviderCredential.created_at)
        )
        for credential in result.all():
            adapter = provider_registry.get(credential.provider)
            if adapter is None or capability not in adapter.capabilities:
                continue
            try:
                return adapter, await resolve_credential_secret(session, credential)
            except CredentialUnavailableError:
                continue
        raise IngestionError(f"{capability}을 지원하는 API key가 없습니다.")

    async def transcribe(
        self,
        session: AsyncSession,
        *,
        source: Source,
        audio: bytes,
        filename: str,
        content_type: str,
    ) -> TranscriptionResponse:
        adapter, api_key = await self._provider(
            session,
            workspace_id=source.workspace_id,
            owner_id=source.owner_id,
            capability="transcription",
        )
        try:
            return await adapter.transcribe(
                TranscriptionRequest(
                    audio=audio,
                    filename=filename,
                    content_type=content_type,
                    model=self.settings.transcription_model,
                ),
                api_key,
            )
        except ProviderError as exc:
            raise IngestionError(str(exc)) from exc

    async def index_transcript(
        self,
        session: AsyncSession,
        *,
        source: Source,
        segments: list[TranscriptSegment],
        language: str | None = None,
    ) -> int:
        normalized = self.normalizer.normalize(
            "meeting",
            source_id=source.id,
            workspace_id=source.workspace_id,
            title=source.title,
            segments=segments,
            language=language,
            metadata={"transcriptSource": source.transcript_source},
        )
        chunks = self.chunker.chunk(normalized)
        if not chunks:
            raise IngestionError("처리할 transcript 내용이 없습니다.")
        adapter, api_key = await self._provider(
            session,
            workspace_id=source.workspace_id,
            owner_id=source.owner_id,
            capability="embedding",
        )
        try:
            response = await adapter.embedding(
                EmbeddingRequest(
                    input=[chunk.content for chunk in chunks],
                    model=self.settings.embedding_model,
                    dimensions=self.settings.embedding_dimensions,
                ),
                api_key,
            )
        except ProviderError as exc:
            raise IngestionError(str(exc)) from exc
        if len(response.embeddings) != len(chunks):
            raise IngestionError("임베딩 응답 개수가 chunk 개수와 다릅니다.")
        if any(
            len(embedding) != self.settings.embedding_dimensions
            for embedding in response.embeddings
        ):
            raise IngestionError("임베딩 차원이 Vector Store schema와 다릅니다.")

        await session.execute(delete(Chunk).where(Chunk.source_id == source.id))
        for chunk, embedding in zip(chunks, response.embeddings, strict=True):
            session.add(
                Chunk(
                    workspace_id=source.workspace_id,
                    source_id=source.id,
                    owner_id=source.owner_id,
                    position=chunk.position,
                    content=chunk.content,
                    start_seconds=chunk.start_seconds,
                    end_seconds=chunk.end_seconds,
                    embedding=embedding,
                )
            )
        source.status = "succeeded"
        session.add(source)
        return len(chunks)

    async def search(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        query: str,
        limit: int,
    ) -> list[tuple[Chunk, float]]:
        adapter, api_key = await self._provider(
            session,
            workspace_id=workspace_id,
            owner_id=owner_id,
            capability="embedding",
        )
        try:
            response = await adapter.embedding(
                EmbeddingRequest(
                    input=query,
                    model=self.settings.embedding_model,
                    dimensions=self.settings.embedding_dimensions,
                ),
                api_key,
            )
        except ProviderError as exc:
            raise IngestionError(str(exc)) from exc
        embedding = response.embeddings[0]
        distance = Chunk.embedding.cosine_distance(embedding).label("distance")
        result = await session.exec(
            select(Chunk, distance)
            .where(Chunk.workspace_id == workspace_id, Chunk.owner_id == owner_id)
            .order_by(distance)
            .limit(limit)
        )
        return [(chunk, float(score)) for chunk, score in result.all()]
