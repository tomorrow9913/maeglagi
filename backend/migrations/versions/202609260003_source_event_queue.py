"""Transactionally publish every Source job-state change to PGMQ.

Revision ID: 202609260003
Revises: 202609260002
"""

from alembic import op

revision = "202609260003"
down_revision = "202609260002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fail the migration explicitly if pgmq is unavailable; Source writes must
    # never silently skip an event after this trigger is installed.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgmq")
    op.execute("SELECT pgmq.create('source_events')")
    # Restrict only this queue so an on-prem installation's other pgmq queues
    # retain their existing grants. PGMQ 1.5.1 functions are SECURITY INVOKER.
    op.execute("REVOKE ALL ON pgmq.q_source_events FROM PUBLIC")
    op.execute("REVOKE ALL ON pgmq.a_source_events FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE queue_sequence text;
        BEGIN
            queue_sequence := pg_get_serial_sequence('pgmq.q_source_events', 'msg_id');
            IF queue_sequence IS NOT NULL THEN
                EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC', queue_sequence);
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON pgmq.q_source_events FROM anon;
                REVOKE ALL ON pgmq.a_source_events FROM anon;
                IF queue_sequence IS NOT NULL THEN
                    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM anon', queue_sequence);
                END IF;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON pgmq.q_source_events FROM authenticated;
                REVOKE ALL ON pgmq.a_source_events FROM authenticated;
                IF queue_sequence IS NOT NULL THEN
                    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM authenticated', queue_sequence);
                END IF;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.publish_source_event() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pgmq AS $$
        DECLARE event_id bigint;
        BEGIN
            event_id := pgmq.send(
                'source_events',
                jsonb_build_object(
                    'owner_id', NEW.owner_id,
                    'workspace_id', NEW.workspace_id,
                    'source_id', NEW.id
                )
            );
            PERFORM pg_notify('maeglagi_source_events', event_id::text);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.publish_source_event() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER sources_pgmq_events_insert
        AFTER INSERT ON sources
        FOR EACH ROW EXECUTE FUNCTION public.publish_source_event()
        """
    )
    op.execute(
        """
        CREATE TRIGGER sources_pgmq_events_update
        AFTER UPDATE OF kind, transcript_source, status, analysis_mode,
                        progress, processing_stage, error_message ON sources
        FOR EACH ROW WHEN (
            ROW(OLD.kind, OLD.transcript_source, OLD.status, OLD.analysis_mode,
                OLD.progress, OLD.processing_stage, OLD.error_message)
            IS DISTINCT FROM
            ROW(NEW.kind, NEW.transcript_source, NEW.status, NEW.analysis_mode,
                NEW.progress, NEW.processing_stage, NEW.error_message)
        )
        EXECUTE FUNCTION public.publish_source_event()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER sources_pgmq_events_update ON sources")
    op.execute("DROP TRIGGER sources_pgmq_events_insert ON sources")
    op.execute("DROP FUNCTION public.publish_source_event()")
    # Preserve the queue and its durable events. Operators can remove it explicitly.
