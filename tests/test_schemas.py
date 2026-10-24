import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from extraction.schemas import SCHEMAS, JobPosting, Salary, json_schema

GOLDEN_DIR = Path(__file__).parents[1] / "data" / "golden"
GOLDEN = sorted(GOLDEN_DIR.rglob("*.json"))  # yours in <doc_type>/, Claude's in claude/<doc_type>/


def _nodes(node):
    """Every schema node: the dicts that describe a value (not the `properties` maps)."""
    if isinstance(node, list):
        for item in node:
            yield from _nodes(item)
    elif isinstance(node, dict):
        yield node
        for key, value in node.items():
            yield from _nodes(list(value.values()) if key == "properties" else value)


@pytest.mark.parametrize("doc_type", sorted(SCHEMAS))
def test_json_schema_is_portable(doc_type):
    schema = json_schema(SCHEMAS[doc_type])
    assert "$ref" not in json.dumps(schema)
    for node in _nodes(schema):
        assert not {"$defs", "title", "default", "minimum", "exclusiveMinimum"} & node.keys()
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])


def test_json_schema_keeps_a_field_named_like_a_keyword():
    assert "title" in json_schema(JobPosting)["properties"]


def test_salary_rejects_an_inverted_range():
    with pytest.raises(ValidationError, match="greater than"):
        Salary(min_amount=5000, max_amount=3000, currency="USD", period="month")


def test_salary_needs_an_amount():
    with pytest.raises(ValidationError, match="min_amount or max_amount"):
        Salary(min_amount=None, max_amount=None, currency="USD", period="month")


@pytest.mark.parametrize("path", GOLDEN, ids=lambda path: str(path.relative_to(GOLDEN_DIR)))
def test_golden_labels_match_the_schema(path):
    SCHEMAS[path.parent.name].model_validate_json(path.read_bytes())
