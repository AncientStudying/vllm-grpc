"""Harness-wide types (v0.0.1 generic home).

Single milestone-agnostic home for the types/enums/aliases the live harness
shares. ``CohortKind`` is the 4-member forward cohort universe (clarify Q1 +
session-3 decision); the dropped ``tuned_grpc_channels`` / ``tuned_grpc``
members live only in the M5.2 tag's history.

During the v0.0.1 refactor this re-exports live types from the legacy modules
that still define them; the definitions move here when those modules are
deleted (Phase 4). The network-probe dataclasses (``M6_1_2NetworkPath`` etc.)
are intentionally NOT hosted here yet — they are de-prefixed alongside
``network_probe.py`` in Phase 3 to avoid colliding with the ``NetworkPath``
transport-kind literal.
"""

from __future__ import annotations

from vllm_grpc_bench.m3_types import (
    EndpointTuple,
    NetworkPath,
    Path_,
    RESTCohortRecord,
    RestHttpsEdgeCohortRecord,
    RTTRecord,
    RunCohort,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS as COHORTS,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CloudProvider as CloudProvider,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CohortKind as CohortKind,
)
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CohortOmissions as CohortOmissions,
)
from vllm_grpc_bench.m6_1_2_types import (
    cohorts_at_concurrency,
)
from vllm_grpc_bench.m6_1_types import (
    M6_1_CELLS as CELLS,
)
from vllm_grpc_bench.m6_1_types import (
    M6_1Cell as Cell,
)
from vllm_grpc_bench.m6_1_types import (
    M6_1Path as Path,
)
from vllm_grpc_bench.m6_sweep import RPCResult

__all__ = [
    "CELLS",
    "COHORTS",
    "Cell",
    "CloudProvider",
    "CohortKind",
    "CohortOmissions",
    "EndpointTuple",
    "NetworkPath",
    "Path",
    "Path_",
    "RESTCohortRecord",
    "RPCResult",
    "RTTRecord",
    "RestHttpsEdgeCohortRecord",
    "RunCohort",
    "cohorts_at_concurrency",
]
