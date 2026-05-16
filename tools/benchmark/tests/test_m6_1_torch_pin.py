"""Tests for ``m6_1_torch_pin`` — driver-start torch validation (FR-006)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from vllm_grpc_bench import m6_1_torch_pin


def _read_pyproject_torch_pin() -> str:
    """Read the ``torch==`` pin from ``tools/benchmark/pyproject.toml``."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text()
    for line in text.splitlines():
        stripped = line.strip().strip(",").strip('"')
        if stripped.startswith("torch=="):
            return stripped.split("==", 1)[1]
    raise AssertionError("torch== pin not found in tools/benchmark/pyproject.toml")


def test_constant_matches_pyproject_pin() -> None:
    assert _read_pyproject_torch_pin() == m6_1_torch_pin._EXPECTED_TORCH_VERSION


def test_validate_torch_version_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch, "__version__", "2.11.0")
    assert m6_1_torch_pin.validate_torch_version() == "2.11.0"


def test_validate_torch_version_mismatch_raises_systemexit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import torch

    monkeypatch.setattr(torch, "__version__", "2.12.0")
    with pytest.raises(SystemExit) as exc_info:
        m6_1_torch_pin.validate_torch_version()
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "2.11.0" in err
    assert "2.12.0" in err


def test_validate_torch_version_import_error_raises_systemexit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if isinstance(__builtins__, dict):
        real_import = __builtins__["__import__"]
    else:
        real_import = __builtins__.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torch":
            raise ImportError("simulated missing torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(SystemExit) as exc_info:
        m6_1_torch_pin.validate_torch_version()
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "pip install torch==2.11.0" in err
