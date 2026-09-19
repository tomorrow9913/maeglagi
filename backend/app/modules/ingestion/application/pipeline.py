from typing import NamedTuple
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.core.credentials import CredentialUnavailableError, resolve_credential_secret
from app.modules.context_engine.application.model_roles import (
    ROLE_CAPABILITY,
    ModelRole,
    selection_of,
)
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
from app.modules.ingestion.domain.models import DocumentSection, TranscriptSegment
from app.modules.workspaces.infrastructure.models import ProviderCredential, Source, Workspace


class IngestionError(RuntimeError):
    pass


class ResolvedProvider(NamedTuple):
    """An API key that can do a job, and the model the workspace chose to do it with."""

    adapter: ProviderAdapter
    api_key: str
    model: str


def embedding_dimensions_argument(model: str, dimensions: int) -> int | None:
    """Only the text-embedding-3 family accepts `dimensions`; older models are fixed-size."""
    return dimensions if model.startswith("text-embedding-3") else None


class IngestionPipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.normalizer = NormalizationService()
        self.chunker = CharacterOverlapChunker(
            self.settings.chunk_size_chars, self.settings.chunk_overlap_chars
        )

    def _default_model(self, provider_id: str, role: ModelRole) -> str:
        """For a job nobody chose a model for: this provider's fallback, never another's."""
        configured = self.settings.provider_fallback_models.get(provider_id, {})
        return configured.get(role.value) or self._fallback_model(role)

    def _fallback_model(self, role: ModelRole) -> str:
        """Only for workspaces that never chose: the deployment's configured default."""
        return {
            ModelRole.ANSWER: self.settings.answer_model,
            ModelRole.EXTRACTION: self.settings.extraction_model,
            ModelRole.EMBEDDING: self.settings.embedding_model,
            ModelRole.TRANSCRIPTION: self.settings.transcription_model,
        }[role]

    async def provider_with_model(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        role: ModelRole,
    ) -> ResolvedProvider:
        """The key and model for `role`: what the owner chose, else the first key that can."""
        capability = ROLE_CAPABILITY[role]
        workspace = await session.get(Workspace, workspace_id)
        chosen = selection_of(workspace.model_settings if workspace else None, role)
        result = await session.exec(
            select(ProviderCredential)
            .where(
                ProviderCredential.workspace_id == workspace_id,
                ProviderCredential.owner_id == owner_id,
                ProviderCredential.status == "active",
            )
            .order_by(ProviderCredential.is_default.desc(), ProviderCredential.created_at)
        )
        credentials = list(result.all())
        if chosen is not None:  # the key of the chosen model's provider goes first
            credentials.sort(key=lambda credential: credential.provider != chosen.provider)
        for credential in credentials:
            adapter = provider_registry.get(credential.provider)
            if adapter is None or capability not in adapter.capabilities:
                continue
            try:
                api_key = await resolve_credential_secret(session, credential)
            except CredentialUnavailableError:
                continue
            uses_choice = chosen is not None and chosen.provider == credential.provider
            model = (
                chosen.model
                if uses_choice and chosen
                else self._default_model(credential.provider, role)
            )
            return ResolvedProvider(adapter, api_key, model)
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
        provider = await self.provider_with_model(
            session,
            workspace_id=source.workspace_id,
            owner_id=source.owner_id,
            role=ModelRole.TRANSCRIPTION,
        )
        try:
            return await provider.adapter.transcribe(
                TranscriptionRequest(
                    audio=audio,
                    filename=filename,
                    content_type=content_type,
                    model=provider.model,
                ),
                provider.api_key,
            )
        except ProviderError as exc:
            raise IngestionError(str(exc)) from exc

    async def index_source(
        self,
        session: AsyncSession,
        *,
        source: Source,
        segments: list[TranscriptSegment] | list[DocumentSection],
        language: str | None = None,
    ) -> int:
        normalized = self.normalizer.normalize(
            source.kind,
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
        provider = await self.provider_with_model(
            session,
            workspace_id=source.workspace_id,
            owner_id=source.owner_id,
            role=ModelRole.EMBEDDING,
        )
        try:
            response = await provider.adapter.embedding(
                EmbeddingRequest(
                    input=[chunk.content for chunk in chunks],
                    model=provider.model,
                    dimensions=embedding_dimensions_argument(
                        provider.model, self.settings.embedding_dimensions
                    ),
                ),
                provider.api_key,
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
        session.add(source)
        return len(chunks)

    async def index_transcript(
        self,
        session: AsyncSession,
        *,
        source: Source,
        segments: list[TranscriptSegment],
        language: str | None = None,
    ) -> int:
        return await self.index_source(session, source=source, segments=segments, language=language)

    async def embed_query(
        self, session: AsyncSession, *, workspace_id: UUID, owner_id: UUID, query: str
    ) -> list[float]:
        """Embed a question once with the workspace's chosen embedding model."""
        provider = await self.provider_with_model(
            session, workspace_id=workspace_id, owner_id=owner_id, role=ModelRole.EMBEDDING
        )
        try:
            response = await provider.adapter.embedding(
                EmbeddingRequest(
                    input=query,
                    model=provider.model,
                    dimensions=embedding_dimensions_argument(
                        provider.model, self.settings.embedding_dimensions
                    ),
                ),
                provider.api_key,
            )
        except ProviderError as exc:
            raise IngestionError(str(exc)) from exc
        embedding = response.embeddings[0]
        if len(embedding) != self.settings.embedding_dimensions:
            raise IngestionError("임베딩 차원이 Vector Store schema와 다릅니다.")
        return embedding

    async def search_by_embedding(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        embedding: list[float],
        limit: int,
        source_ids: list[UUID] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Nearest chunks to an already-computed embedding, optionally within `source_ids`."""
        distance = Chunk.embedding.cosine_distance(embedding).label("distance")
        statement = select(Chunk, distance).where(
            Chunk.workspace_id == workspace_id, Chunk.owner_id == owner_id
        )
        if source_ids is not None:
            statement = statement.where(Chunk.source_id.in_(source_ids))  # type: ignore[attr-defined]
        result = await session.exec(statement.order_by(distance).limit(limit))
        return [(chunk, float(score)) for chunk, score in result.all()]

    async def search(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        query: str,
        limit: int,
        source_ids: list[UUID] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Nearest chunks to `query`, optionally only within `source_ids`."""
        embedding = await self.embed_query(
            session, workspace_id=workspace_id, owner_id=owner_id, query=query
        )
        return await self.search_by_embedding(
            session,
            workspace_id=workspace_id,
            owner_id=owner_id,
            embedding=embedding,
            limit=limit,
            source_ids=source_ids,
        )
