"""Harness-wide exceptions (v0.0.1 generic home).

The schema-validation error was hoisted in-place at Phase 4 (T020) from the
legacy ``m5_2_regen`` module (where it was ``M5_2SchemaValidationFailed``);
this module no longer imports from any milestone-prefixed source. See
``specs/029-post-m6.2-cleanup-v0.0.1/``.
"""

from __future__ import annotations


class SchemaValidationFailed(RuntimeError):
    """Raised when a produced aggregate JSON fails schema validation."""


__all__ = ["SchemaValidationFailed"]
