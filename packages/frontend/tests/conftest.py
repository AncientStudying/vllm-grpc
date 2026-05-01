from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_vllm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake vllm module so frontend tests run without a GPU install."""
    fake_vllm = MagicMock()

    # SamplingParams just stores kwargs on the mock so tests can inspect them
    class FakeSamplingParams:
        seed: object = None

        def __init__(self, **kwargs: object) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    fake_vllm.SamplingParams = FakeSamplingParams
    monkeypatch.setitem(sys.modules, "vllm", fake_vllm)
