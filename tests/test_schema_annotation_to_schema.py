from __future__ import annotations

import typing
from collections.abc import Mapping, Sequence

from github_mcp.mcp_server.schemas import _annotation_to_schema


def test_annotation_to_schema_supports_annotated() -> None:
    ann = typing.Annotated[str, "some meta"]
    assert _annotation_to_schema(ann) == {"type": "string"}


def test_annotation_to_schema_supports_sequence_origin() -> None:
    ann = Sequence[int]
    assert _annotation_to_schema(ann) == {"type": "array", "items": {"type": "integer"}}


def test_annotation_to_schema_supports_mapping_origin() -> None:
    ann = Mapping[str, int]
    assert _annotation_to_schema(ann) == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }


def test_annotation_to_schema_literal_bool_is_boolean_not_integer() -> None:
    # bool is a subclass of int in Python; schema typing should still be boolean.
    ann = typing.Literal[True, False]
    assert _annotation_to_schema(ann) == {"enum": [True, False], "type": "boolean"}


def test_annotation_to_schema_literal_int_is_integer() -> None:
    ann = typing.Literal[1, 2, 3]
    assert _annotation_to_schema(ann) == {"enum": [1, 2, 3], "type": "integer"}
