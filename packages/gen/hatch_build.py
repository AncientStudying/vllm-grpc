"""Build-time protobuf/gRPC stub generation for ``vllm-grpc-gen`` (FR-007a).

The generated ``*_pb2.py`` / ``*_pb2_grpc.py`` stubs are gitignored — ``proto/`` is
the single source of truth (Constitution Principle I). This hatchling build hook
runs ``protoc`` into ``src/`` before the wheel/sdist is assembled, reusing the
*same* invocation as the ``make proto`` Makefile target so the two never drift.

Proto sources are located in two layouts:
  * workspace build (``uv build --package``): ``proto/`` lives at the repo root
    (``<package>/../../proto``);
  * sdist build: ``proto/`` is force-included at the package root (``<package>/proto``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# Production protos only — the M4 schema candidates are not part of the
# published surface (Makefile generates them into an isolated namespace).
_PROTOS = (
    "vllm_grpc/v1/health.proto",
    "vllm_grpc/v1/chat.proto",
    "vllm_grpc/v1/completions.proto",
)


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        out = root / "src"

        proto_root = self._find_proto_root(root)
        if proto_root is None:
            # No proto sources available (e.g. an sdist rebuild without the
            # force-included protos) — fall back to pre-generated stubs if they
            # are already present, otherwise fail loudly.
            if (out / "vllm_grpc/v1/chat_pb2.py").is_file():
                return
            raise RuntimeError(
                "vllm-grpc-gen build hook: proto/ sources not found and no "
                "pre-generated stubs present; cannot build."
            )

        out.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{proto_root}",
            f"--python_out={out}",
            f"--grpc_python_out={out}",
            *[str(proto_root / proto) for proto in _PROTOS],
        ]
        subprocess.run(cmd, check=True)

    @staticmethod
    def _find_proto_root(root: Path) -> Path | None:
        for candidate in (root / "proto", root.parent.parent / "proto"):
            if (candidate / "vllm_grpc/v1/health.proto").is_file():
                return candidate
        return None
