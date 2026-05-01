from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RequestSample:
    id: str
    messages: list[dict[str, str]]
    model: str
    max_tokens: int
    temperature: float
    seed: int


def load_corpus(path: Path) -> list[RequestSample]:
    raw = json.loads(path.read_text())
    if not raw:
        raise ValueError(f"Corpus at {path} is empty")
    return [
        RequestSample(
            id=item["id"],
            messages=item["messages"],
            model=item["model"],
            max_tokens=item["max_tokens"],
            temperature=item["temperature"],
            seed=item["seed"],
        )
        for item in raw
    ]
