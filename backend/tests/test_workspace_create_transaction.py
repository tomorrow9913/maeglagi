from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.workspaces.schemas import CreateWorkspaceRequest
from app.auth.models import AuthUser
from app.modules.workspaces.infrastructure.models import (
    ProviderCredential,
    Workspace,
    WorkspaceAuditEvent,
    WorkspaceMember,
)

routes = import_module("app.api.workspaces.router")


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type: JSONB, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: object) -> None:
        self.session.add(obj)

    async def exec(self, statement: object):
        return self.session.execute(statement).scalars()

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def refresh(self, obj: object) -> None:
        self.session.refresh(obj)


@pytest.fixture
def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Workspace.metadata.create_all(
        engine,
        tables=[
            Workspace.__table__,
            WorkspaceMember.__table__,
            WorkspaceAuditEvent.__table__,
            ProviderCredential.__table__,
        ],
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def valid_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def validate(_provider: str, _key: str) -> tuple[bool, str]:
        return True, "ok"

    async def options(_provider: str, _key: str) -> dict:
        return {}

    monkeypatch.setattr(routes, "validate_provider_credential", validate)
    monkeypatch.setattr(routes, "options_for_key", options)


def request() -> CreateWorkspaceRequest:
    return CreateWorkspaceRequest(name="Test", llmProvider="openai", llmApiKey="test-key")


@pytest.mark.asyncio
async def test_create_workspace_flushes_before_storing_account_credential(
    database: Session, valid_provider: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def store_secret(*_args: object, **kwargs: object):
        present = database.execute(
            text("select count(*) from workspaces where id = :id"),
            {"id": kwargs["workspace_id"].hex},
        ).scalar_one()
        assert present == 1
        return uuid4()

    monkeypatch.setattr(routes, "store_credential_secret", store_secret)
    owner = uuid4()
    result = await routes.create_workspace(
        request(), AuthUser(id=str(owner), metadata={}), AsyncSessionAdapter(database)
    )

    workspace = database.get(Workspace, result.id)
    credential = database.query(ProviderCredential).one()
    assert workspace is not None
    assert credential.workspace_id is None
    assert credential.owner_id == owner
    assert database.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.asyncio
async def test_vault_failure_rolls_back_flushed_workspace(
    database: Session, valid_provider: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_to_store(*_args: object, **kwargs: object) -> None:
        assert (
            database.execute(
                text("select count(*) from workspaces where id = :id"),
                {"id": kwargs["workspace_id"].hex},
            ).scalar_one()
            == 1
        )
        raise RuntimeError("vault unavailable")

    monkeypatch.setattr(routes, "store_credential_secret", fail_to_store)
    with pytest.raises(RuntimeError, match="vault unavailable"):
        await routes.create_workspace(
            request(), AuthUser(id=str(uuid4()), metadata={}), AsyncSessionAdapter(database)
        )
    database.rollback()

    assert database.query(Workspace).count() == 0
    assert database.query(ProviderCredential).count() == 0
