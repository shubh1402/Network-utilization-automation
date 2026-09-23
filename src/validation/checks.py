"""Shared result type for accuracy checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: str = "error"   # "error" | "warning"

    def to_dict(self) -> dict:
        return asdict(self)


def failures(results: list[CheckResult]) -> list[str]:
    return [f"{r.name}: {r.detail}" for r in results if not r.passed]
