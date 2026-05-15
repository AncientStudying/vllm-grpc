"""M6 — Real-Engine Mini-Validation: shared types and cell-iteration constants.

Data shapes follow `specs/020-m6-real-engine-mini-validation/data-model.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# --- Cell-iteration constants (T003) -----------------------------------------

M6_PATHS: tuple[Literal["embed", "chat_stream"], ...] = ("embed", "chat_stream")
M6_HIDDEN_SIZE: Literal[4096] = 4096
M6_CONCURRENCIES: tuple[Literal[1, 4, 8], ...] = (1, 4, 8)

# Cell iteration order per data-model.md `M6Cell.Identity`:
#   embed × c=1, embed × c=4, embed × c=8, chat_stream × c=1, ...
M6_CELLS: tuple[tuple[Literal["embed", "chat_stream"], Literal[4096], Literal[1, 4, 8]], ...] = (
    ("embed", 4096, 1),
    ("embed", 4096, 4),
    ("embed", 4096, 8),
    ("chat_stream", 4096, 1),
    ("chat_stream", 4096, 4),
    ("chat_stream", 4096, 8),
)

# Three cohorts measured per cell (FR-002). `rest_plain_tcp` and
# `tuned_grpc_channels` are out of scope for M6.
M6_COHORTS: tuple[Literal["rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"], ...] = (
    "rest_https_edge",
    "default_grpc",
    "tuned_grpc_multiplexed",
)

# Smoke gate exercises 2 cells × 3 cohorts × n=10 (FR-011).
M6_SMOKE_CELLS: tuple[tuple[Literal["embed", "chat_stream"], Literal[4096], Literal[1]], ...] = (
    ("embed", 4096, 1),
    ("chat_stream", 4096, 1),
)

# --- Per-cell types (T004 placeholders; full shapes added in Phase 2) --------

M6Path = Literal["embed", "chat_stream"]
M6Concurrency = Literal[1, 4, 8]
M6CohortKind = Literal["rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
VerdictClassification = Literal[
    "verdict_survives",
    "verdict_changed",
    "verdict_buried_by_engine",
    "no_winner_at_n100",
    "cell_incomplete",
]


@dataclass(frozen=True)
class M6Cell:
    path: M6Path
    hidden_size: Literal[4096]
    concurrency: M6Concurrency
