"""Port for application metrics emission. Adapter wires it to OpenTelemetry."""

from abc import ABC, abstractmethod


class MetricsCollector(ABC):
    @abstractmethod
    def endpoint_created(self) -> None: ...

    @abstractmethod
    def request_captured(
        self,
        *,
        method: str,
        body_offloaded: bool,
        body_size: int,
        duration_seconds: float,
    ) -> None: ...

    @abstractmethod
    def cleaner_run(self, deleted: int) -> None: ...
