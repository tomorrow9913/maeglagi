from uuid import uuid4

from app.modules.context_engine.application.directory_resolution import (
    canonicalize_directory_entities,
)
from app.modules.context_engine.application.entity_resolution import resolve_extraction
from app.modules.context_engine.domain.extraction import (
    ClassificationOutput,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
)


def result(name: str, reference: str) -> ExtractionResult:
    return ExtractionResult(
        classification=ClassificationOutput(source_type="meeting", language="ko", topics=[]),
        entities=[
            ExtractedEntity(
                name=name,
                kind="Person",
                aliases=[],
                identifiers=[],
                source_refs=[reference],
            )
        ],
        events=[],
        relations=[
            ExtractedRelation(
                source=name,
                target=name,
                kind="RELATED_TO",
                valid_from=None,
                valid_to=None,
                source_refs=[reference],
            )
        ],
        contexts=[],
        warnings=[],
        usage={},
    )


def test_directory_alias_attaches_stable_id_only_when_source_quotes_the_alias() -> None:
    person_id = uuid4()
    snapshot = {
        "people": [{"id": str(person_id), "name": "김민수", "aliases": ["민수"]}],
        "project": None,
    }
    extracted = result("민수", "민수가 말했다")

    canonicalize_directory_entities(extracted, snapshot, "민수가 말했다")

    assert extracted.entities[0].name == "김민수"
    assert extracted.entities[0].identifiers == [f"directory:person:{person_id}"]
    assert extracted.relations[0].source == "김민수"


def test_roster_without_source_evidence_never_invents_a_participant() -> None:
    snapshot = {
        "people": [{"id": str(uuid4()), "name": "김민수", "aliases": ["민수"]}],
        "project": None,
    }
    extracted = result("민수", "회의를 했다")

    canonicalize_directory_entities(extracted, snapshot, "회의를 했다")

    assert extracted.entities[0].name == "민수"
    assert extracted.entities[0].identifiers == []


def test_directory_id_stays_stable_with_email_and_rejects_model_invented_ids() -> None:
    workspace, source, person = uuid4(), uuid4(), uuid4()
    snapshot = {
        "people": [{"id": str(person), "name": "김민수", "aliases": ["민수"]}],
        "project": None,
    }
    first = result("민수", "민수가 말했다")
    trusted = canonicalize_directory_entities(first, snapshot, "민수가 말했다")
    stable = (
        resolve_extraction(
            first,
            workspace_id=workspace,
            source_id=source,
            trusted_directory_identifiers=trusted,
        )
        .entities[0]
        .id
    )

    second = result("민수", "민수가 말했다")
    second.entities[0].identifiers = ["a@example.com", f"directory:person:{uuid4()}"]
    trusted = canonicalize_directory_entities(second, snapshot, "민수가 말했다")
    resolved = resolve_extraction(
        second,
        workspace_id=workspace,
        source_id=source,
        trusted_directory_identifiers=trusted,
    ).entities[0]
    assert resolved.id == stable
    assert resolved.identifiers == ["a@example.com", f"directory:person:{person}"]

    untrusted = result("가짜", "가짜가 말했다")
    untrusted.entities[0].identifiers = [f"directory:person:{person}"]
    assert canonicalize_directory_entities(untrusted, snapshot, "가짜가 말했다") == set()
    assert untrusted.entities[0].identifiers == []
    resolved_untrusted = resolve_extraction(untrusted, workspace_id=workspace, source_id=source)
    assert resolved_untrusted.entities[0].identifiers == []


def test_multiple_projects_and_email_disambiguate_directory_matches() -> None:
    person_a, person_b, project_a, project_b = (uuid4() for _ in range(4))
    snapshot = {
        "people": [
            {"id": str(person_a), "name": "Kim", "aliases": [], "email": "a@example.com"},
            {"id": str(person_b), "name": "Kim", "aliases": [], "email": "b@example.com"},
        ],
        "projects": [
            {"id": str(project_a), "name": "Alpha"},
            {"id": str(project_b), "name": "Beta"},
        ],
    }
    extracted = result("Kim", "Kim b@example.com said yes")
    extracted.entities[0].identifiers = ["b@example.com"]
    project = ExtractedEntity(
        name="Beta",
        kind="Project",
        aliases=[],
        identifiers=[],
        source_refs=["Beta plan"],
    )
    extracted.entities.append(project)
    trusted = canonicalize_directory_entities(
        extracted, snapshot, "Kim b@example.com said yes. Beta plan"
    )
    assert f"directory:person:{person_b}" in trusted
    assert f"directory:project:{project_b}" in trusted
    assert extracted.entities[0].identifiers == ["b@example.com", f"directory:person:{person_b}"]


def test_email_identifies_person_when_extracted_alias_differs() -> None:
    person = uuid4()
    snapshot = {
        "people": [
            {
                "id": str(person),
                "name": "Kim",
                "aliases": [],
                "email": "kim@example.com",
            }
        ]
    }
    extracted = result("New nickname", "New nickname kim@example.com approved")
    extracted.entities[0].identifiers = ["KIM@example.com"]
    trusted = canonicalize_directory_entities(
        extracted, snapshot, "New nickname kim@example.com approved"
    )
    assert extracted.entities[0].name == "Kim"
    assert f"directory:person:{person}" in trusted
