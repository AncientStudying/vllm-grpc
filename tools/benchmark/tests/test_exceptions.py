"""New-home coverage for the de-prefixed ``exceptions`` module (T023).

Asserts the hoisted :class:`SchemaValidationFailed` (formerly
``m5_2_regen.M5_2SchemaValidationFailed``) raises and is a ``RuntimeError``.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.exceptions import SchemaValidationFailed


def test_schema_validation_failed_is_runtime_error() -> None:
    assert issubclass(SchemaValidationFailed, RuntimeError)


def test_schema_validation_failed_raises_with_message() -> None:
    with pytest.raises(SchemaValidationFailed, match="bad aggregate"):
        raise SchemaValidationFailed("bad aggregate")


def test_schema_validation_failed_caught_as_runtime_error() -> None:
    """Callers catching the broad ``RuntimeError`` still trap the schema error."""
    with pytest.raises(RuntimeError):
        raise SchemaValidationFailed("schema drift")
