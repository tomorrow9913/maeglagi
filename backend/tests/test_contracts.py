import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

CONTRACTS = Path(__file__).parents[2] / "contracts"


def load_schemas() -> tuple[dict[str, dict], Registry]:
    schemas = {}
    registry = Registry()
    for path in sorted((CONTRACTS / "schemas").glob("*.json")):
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return schemas, registry


def test_ontology_files_are_valid_yaml() -> None:
    for path in sorted((CONTRACTS / "ontology").glob("*.yaml")):
        assert yaml.safe_load(path.read_text())["version"] == 1


def test_meeting_seed_matches_contract() -> None:
    schemas, registry = load_schemas()
    instance = json.loads(
        (CONTRACTS / "seeds/redis-adoption/expected-meeting-analysis.json").read_text()
    )

    Draft202012Validator(
        schemas["meeting-analysis.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(instance)
