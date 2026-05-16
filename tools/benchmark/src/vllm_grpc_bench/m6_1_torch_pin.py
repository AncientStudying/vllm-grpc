"""M6.1 client-side ``torch`` version pin + driver-start validation gate.

Per spec FR-006 and research R-2: the bench client's ``torch.save``-serialised
prompt-embeds tensors must round-trip cleanly through the server-side
``decode_embeds`` call. Because the ``torch.save`` pickle ZIP format + tensor
metadata can drift across versions, the client MUST run the exact version that
``vllm==0.20.1`` pulls transitively.

Validation runs once at the start of both the full sweep and the smoke gate,
before any Modal deploy or measurement RPC. A mismatch (or missing ``torch``)
turns a downstream silent ``decode_embeds`` failure into an actionable startup
error with exit code 2.
"""

from __future__ import annotations

import sys
from typing import Final

_EXPECTED_TORCH_VERSION: Final[str] = "2.11.0"


def validate_torch_version() -> str:
    """Validate ``torch.__version__`` matches the M6.1 pinned version.

    Returns the detected version on success. Raises ``SystemExit(2)`` with a
    clear actionable stderr message if ``torch`` is not importable or the
    detected version does not match the pin.
    """
    try:
        import torch
    except ImportError:
        print(
            "M6.1 ERROR: torch is required on the client to ship "
            "prompt-embeds tensors.\n"
            f"  Install: pip install torch=={_EXPECTED_TORCH_VERSION}\n"
            "  See: specs/022-m6-1-real-prompt-embeds/quickstart.md "
            "§ Prerequisites.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    detected = str(torch.__version__)
    if detected != _EXPECTED_TORCH_VERSION:
        print(
            "M6.1 ERROR: client torch version mismatch.\n"
            f"  Expected: {_EXPECTED_TORCH_VERSION} "
            "(matches vllm==0.20.1 transitive pin)\n"
            f"  Detected: {detected}\n"
            "  Reason: torch.save / torch.load wire format may differ across "
            "versions (FR-006).\n"
            f"  Fix: pip install torch=={_EXPECTED_TORCH_VERSION}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return detected


__all__ = ["_EXPECTED_TORCH_VERSION", "validate_torch_version"]
