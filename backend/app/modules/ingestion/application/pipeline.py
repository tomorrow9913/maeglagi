from datetime import date
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.core.credentials import CredentialUnavailableError, resolve_credential_secret
from app.modules.context_engine.application.model_catalog import has_indexed_chunks
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
from app.modules.context_engine.infrastructure.provider_registry import (
    adapter_for_credential,
    provider_registry,
)
from app.modules.ingestion.application.chunking import CharacterOverlapChunker
from app.modules.ingestion.application.normalization import NormalizationService
from app.modules.ingestion.domain.models import DocumentSection, TranscriptSegment
from app.modules.workspaces.infrastructure.models import ProviderCredential, Source, Workspace


class IngestionError(RuntimeError):
    pass


class MissingCapabilityCredentialError(IngestionError):
    """No usable account credential can perform a workspace model role."""

    code = "missing_capability_credential"

    def __init__(
        self,
        message: str,
        *,
        capability: str,
        providers: tuple[str, ...] | None = None,
        selected: bool = False,
    ) -> None:
        super().__init__(message)
        self.capability = capability
        self.providers = providers
        self.selected = selected


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
        """Use the legacy embedding setting, otherwise this provider's configured fallback."""
        if role == ModelRole.EMBEDDING:
            # Workspaces without a stored choice have always used this deployment setting.
            # Changing the default for new indexing would mix vector spaces in old workspaces.
            return self.settings.embedding_model
        override = self.settings.provider_fallback_models.get(provider_id, {})
        configured = self.settings.provider_default_models.get(provider_id, {})
        return override.get(role.value) or configured.get(role.value) or self._fallback_model(role)

    def _fallback_model(self, role: ModelRole) -> str:
        """Last resort when a provider has no configured default: the deployment's flat setting."""
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
        """The account connection and model selected by this workspace's owner."""
        capability = ROLE_CAPABILITY[role]
        workspace = await session.get(Workspace, workspace_id)
        chosen = selection_of(workspace.model_settings if workspace else None, role)
        result = await session.exec(
            select(ProviderCredential)
            .where(
                ProviderCredential.owner_id == owner_id,
                ProviderCredential.status == "active",
            )
            .order_by(
                (ProviderCredential.workspace_id == workspace_id).desc(),
                ProviderCredential.is_default.desc(),
                ProviderCredential.created_at,
            )
        )
        credentials = list(result.all())
        if chosen is not None:
            credentials = [
                c
                for c in credentials
                if c.provider == chosen.provider
                and (chosen.credential_id is None or c.id == chosen.credential_id)
            ]
        needs_key_match = (
            chosen is not None and chosen.credential_id is None and len(credentials) > 1
        )
        for credential in credentials:
            adapter = (
                adapter_for_credential(credential)
                if credential.provider == "ollama"
                else provider_registry.get(credential.provider)
            )
            if adapter is None or capability not in adapter.capabilities:
                continue
            try:
                api_key = await resolve_credential_secret(session, credential)
            except CredentialUnavailableError:
                continue
            if chosen is not None:
                if needs_key_match:
                    try:
                        offered = await adapter.list_model_infos(api_key)
                    except ProviderError:
                        continue
                    if not any(
                        info.id == chosen.model
                        and (info.shutdown_date is None or info.shutdown_date > date.today())
                        for info in offered
                    ):
                        continue
                model = chosen.model
            else:
                model = self._default_model(credential.provider, role)
            return ResolvedProvider(adapter, api_key, model)
        if chosen is not None:
            raise MissingCapabilityCredentialError(
                "선택한 모델을 제공하는 API key가 없습니다.",
                capability=capability,
                providers=(chosen.provider,),
                selected=True,
            )
        raise MissingCapabilityCredentialError(
            f"{capability}을 지원하는 API key가 없습니다.", capability=capability
        )

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
        try:
            provider = await self.provider_with_model(
                session,
                workspace_id=source.workspace_id,
                owner_id=source.owner_id,
                role=ModelRole.EMBEDDING,
            )
        except MissingCapabilityCredentialError as exc:
            # A selected model or existing vectors must not be silently replaced by
            # text-only chunks when its credential becomes unavailable.
            if exc.selected or await has_indexed_chunks(session, source.workspace_id):
                raise
            # New text remains searchable by the lexical path and available for extraction.
            embeddings: list[list[float] | None] = [None] * len(chunks)
        else:
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
            embeddings = response.embeddings

        await session.execute(delete(Chunk).where(Chunk.source_id == source.id))
        for chunk, embedding in zip(chunks, embeddings, strict=True):
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
            Chunk.workspace_id == workspace_id,
            Chunk.owner_id == owner_id,
            Chunk.embedding.is_not(None),
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
