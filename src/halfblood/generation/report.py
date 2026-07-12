from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from halfblood.generation.errors import ProviderError

PageStatusValue = Literal["success", "failed", "skipped"]


@dataclass(frozen=True)
class PageGenerationStatus:
    unit_id: str
    ordinal: int
    status: PageStatusValue
    attempts: int = 0
    error: ProviderError | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationReport:
    statuses: tuple[PageGenerationStatus, ...]

    @property
    def failed_pages(self) -> list[int]:
        return sorted(status.ordinal for status in self.statuses if status.status == "failed")

    @property
    def attempted(self) -> tuple[PageGenerationStatus, ...]:
        return tuple(status for status in self.statuses if status.status != "skipped")

    @property
    def all_attempted_failed(self) -> bool:
        attempted = self.attempted
        return bool(attempted) and all(status.status == "failed" for status in attempted)


class AllPagesFailedError(RuntimeError):
    """Raised when every attempted unit in a generation report failed."""

    def __init__(self, report: GenerationReport, message: str | None = None) -> None:
        self.report = report
        if message is None:
            message = f"all {len(report.attempted)} attempted unit(s) failed"
        super().__init__(message)
