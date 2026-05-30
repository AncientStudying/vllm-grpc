"""Harness-wide types (v0.0.1 generic home).

Single milestone-agnostic home for the types/enums/aliases the live harness
shares. ``CohortKind`` is the 4-member forward cohort universe (clarify Q1 +
session-3 decision); the dropped ``tuned_grpc_channels`` / ``tuned_grpc``
members live only in the M5.2 tag's history.

During the v0.0.1 refactor this re-exports live types from the legacy modules
that still define them; the definitions move here when those modules are
deleted (Phase 4). The network-probe dataclasses (``M6_1_2NetworkPath`` /
``M6_1_2NetworkPathHop`` / ``M6_1_2NetworkPathError``) are re-exported here too
(T014) so the de-prefixed ``network_probe.py`` resolves them from this home;
they keep their ``M6_1_2`` symbol names for now (the milestone-flavored names
are dropped in the T028a symbol-rename pass, which also resolves the
``NetworkPath`` dataclass-vs-transport-literal name clash).
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
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2NetworkPathHop,
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
    "M6_1_2NetworkPath",
    "M6_1_2NetworkPathError",
    "M6_1_2NetworkPathHop",
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
