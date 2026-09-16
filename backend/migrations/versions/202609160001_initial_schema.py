"""Initial Supabase schema managed by Alembic.

Revision ID: 202609160001
Revises: None
"""

# ruff: noqa: E501 -- SQL policy statements are intentionally kept intact.

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "202609160001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create extension if not exists pgcrypto")
    op.execute("create extension if not exists vector with schema extensions")

    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("char_length(trim(name)) > 0", name="ck_workspaces_name_not_blank"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
    )
    op.create_index("workspaces_owner_id_idx", "workspaces", ["owner_id"])

    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("object_path", sa.Text(), nullable=False, unique=True),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind in ('document', 'meeting')", name="ck_sources_kind"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_sources_size_bytes"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
    )
    op.create_index("sources_workspace_id_idx", "sources", ["workspace_id"])
    op.create_index("sources_owner_id_idx", "sources", ["owner_id"])

    op.create_table(
        "provider_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("label", sa.String(80), nullable=False, server_default="기본"),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "workspace_id", "provider", "label", name="uq_provider_credential_label"
        ),
    )
    op.create_index(
        "provider_credentials_workspace_id_idx", "provider_credentials", ["workspace_id"]
    )
    op.create_index(
        "provider_credentials_one_default_idx",
        "provider_credentials",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=True),
        sa.Column("end_seconds", sa.Float(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("position >= 0", name="ck_chunks_position"),
        sa.CheckConstraint("char_length(content) > 0", name="ck_chunks_content"),
        sa.CheckConstraint(
            "start_seconds is null or start_seconds >= 0", name="ck_chunks_start_seconds"
        ),
        sa.CheckConstraint(
            "end_seconds is null or end_seconds >= coalesce(start_seconds, 0)",
            name="ck_chunks_end_seconds",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "position", name="uq_chunks_source_position"),
    )
    op.create_index("chunks_workspace_id_idx", "chunks", ["workspace_id"])
    op.create_index("chunks_source_id_idx", "chunks", ["source_id"])
    op.create_index("chunks_owner_id_idx", "chunks", ["owner_id"])
    op.execute(
        "create index chunks_embedding_hnsw_idx on public.chunks "
        "using hnsw (embedding extensions.vector_cosine_ops) where embedding is not null"
    )

    op.create_table(
        "contexts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind in ('event', 'decision', 'task', 'fact', 'summary')", name="ck_contexts_kind"
        ),
        sa.CheckConstraint("char_length(trim(title)) > 0", name="ck_contexts_title"),
        sa.CheckConstraint("char_length(body) > 0", name="ck_contexts_body"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
    )
    op.create_index("contexts_workspace_id_idx", "contexts", ["workspace_id"])
    op.create_index("contexts_source_id_idx", "contexts", ["source_id"])
    op.create_index("contexts_chunk_id_idx", "contexts", ["chunk_id"])
    op.create_index("contexts_occurred_at_idx", "contexts", [sa.text("occurred_at desc")])

    for table in ("workspaces", "sources", "provider_credentials", "chunks", "contexts"):
        op.execute(f"alter table public.{table} enable row level security")

    op.execute(
        "insert into storage.buckets (id, name, public) values ('sources', 'sources', false) on conflict (id) do update set public = false"
    )
    _create_policies()


def _create_policies() -> None:
    statements = [
        'create policy "owners manage workspaces" on public.workspaces for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id)',
        'create policy "owners manage sources" on public.sources for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id and exists (select 1 from public.workspaces where workspaces.id = workspace_id and workspaces.owner_id = (select auth.uid())))',
        'create policy "owners manage provider credentials" on public.provider_credentials for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id)',
        'create policy "owners manage chunks" on public.chunks for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id and exists (select 1 from public.sources where sources.id = source_id and sources.workspace_id = workspace_id and sources.owner_id = (select auth.uid())))',
        'create policy "owners manage contexts" on public.contexts for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id and exists (select 1 from public.sources where sources.id = source_id and sources.workspace_id = workspace_id and sources.owner_id = (select auth.uid())) and (chunk_id is null or exists (select 1 from public.chunks where chunks.id = chunk_id and chunks.source_id = source_id and chunks.workspace_id = workspace_id and chunks.owner_id = (select auth.uid()))))',
        "create policy \"users upload own sources\" on storage.objects for insert to authenticated with check (bucket_id = 'sources' and (storage.foldername(name))[1] = (select auth.uid())::text)",
        "create policy \"users read own sources\" on storage.objects for select to authenticated using (bucket_id = 'sources' and owner_id = (select auth.uid())::text)",
        "create policy \"users delete own sources\" on storage.objects for delete to authenticated using (bucket_id = 'sources' and owner_id = (select auth.uid())::text)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for policy, table in (
        ("users delete own sources", "storage.objects"),
        ("users read own sources", "storage.objects"),
        ("users upload own sources", "storage.objects"),
    ):
        op.execute(f'drop policy if exists "{policy}" on {table}')
    for table in ("contexts", "chunks", "provider_credentials", "sources", "workspaces"):
        op.drop_table(table)
