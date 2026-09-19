"""Add the project context store and allow issue contexts.

Revision ID: 202609190001
Revises: 202609180001
"""

# ruff: noqa: E501 -- SQL policy statements are intentionally kept intact.

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609190001"
down_revision = "202609180001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_stores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("current_state", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "open_issues", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "decisions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "next_actions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workspace_id", name="uq_context_stores_workspace"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
    )
    op.create_index("context_stores_owner_id_idx", "context_stores", ["owner_id"])
    op.execute("alter table public.context_stores enable row level security")
    op.execute(
        'create policy "owners manage context stores" on public.context_stores for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id and exists (select 1 from public.workspaces where workspaces.id = workspace_id and workspaces.owner_id = (select auth.uid())))'
    )

    # The timeline shows issues too, and the ontology has an Issue entity.
    op.drop_constraint("ck_contexts_kind", "contexts", type_="check")
    op.create_check_constraint(
        "ck_contexts_kind",
        "contexts",
        "kind in ('event', 'decision', 'task', 'issue', 'fact', 'summary')",
    )


def downgrade() -> None:
    op.execute("delete from public.contexts where kind = 'issue'")
    op.drop_constraint("ck_contexts_kind", "contexts", type_="check")
    op.create_check_constraint(
        "ck_contexts_kind",
        "contexts",
        "kind in ('event', 'decision', 'task', 'fact', 'summary')",
    )
    op.execute('drop policy if exists "owners manage context stores" on public.context_stores')
    op.drop_table("context_stores")
