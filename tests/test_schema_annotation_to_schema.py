from __future__ import annotations

import typing
from collections.abc import Mapping, Sequence

from github_mcp.mcp_server.schemas import _annotation_to_schema


def test_annotation_to_schema_supports_annotated() -> None:
    ann = typing.Annotated[str, "some meta"]
    assert _annotation_to_schema(ann) == {"type": "string"}


def test_annotation_to_schema_supports_sequence_origin() -> None:
    ann = Sequence[int]
    # Permissive contract: avoid constraining item types.
    assert _annotation_to_schema(ann) == {"type": "array", "items": {}}


def test_annotation_to_schema_supports_mapping_origin() -> None:
    ann = Mapping[str, int]
    # Permissive contract: avoid constraining value types.
    assert _annotation_to_schema(ann) == {"type": "object", "additionalProperties": True}


def test_annotation_to_schema_literal_bool_is_boolean_not_integer() -> None:
    # bool is a subclass of int in Python; schema typing should still be boolean.
    ann = typing.Literal[True, False]
    # Permissive contract: avoid enums that can block clients.
    assert _annotation_to_schema(ann) == {"type": "boolean"}


def test_annotation_to_schema_literal_int_is_integer() -> None:
    ann = typing.Literal[1, 2, 3]
    # Permissive contract: avoid enums that can block clients.
    assert _annotation_to_schema(ann) == {"type": "integer"}
