from app.api.workspaces.schemas import WorkspaceResponse
from app.auth.models import AuthUser
from app.decorators import require_roles
from app.main import app


def test_public_paths_are_preserved_after_api_package_refactor() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/auth/me" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert "/api/v1/workspaces/{workspace_id}/ai/providers" in paths
    assert "/api/v1/workspaces/{workspace_id}/provider-credentials" in paths
    assert "/api/v1/workspaces/{workspace_id}/sources/transcripts" in paths
    assert "/api/v1/workspaces/{workspace_id}/search" in paths
    assert "/api/v1/workspaces/{workspace_id}/context" in paths
    assert "/api/v1/workspaces/{workspace_id}/context-store" in paths
    assert "/api/v1/workspaces/{workspace_id}/graph" in paths


def test_workspace_schema_is_colocated_with_router() -> None:
    assert WorkspaceResponse.__module__ == "app.api.workspaces.schemas"


def test_source_ingestion_endpoints_return_accepted_jobs() -> None:
    paths = app.openapi()["paths"]

    for endpoint in ("documents", "recordings", "transcripts"):
        operation = paths[f"/api/v1/workspaces/{{workspace_id}}/sources/{endpoint}"]["post"]
        assert "202" in operation["responses"]


def test_role_policy_can_be_injected_as_a_dependency() -> None:
    policy = require_roles("admin")
    user = AuthUser(id="00000000-0000-0000-0000-000000000001", metadata={"roles": ["admin"]})

    assert policy(user) is user
