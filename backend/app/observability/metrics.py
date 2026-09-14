import time
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)

    def observe(self, name: str, started: float) -> None:
        self._counts[name] += 1
        self._latencies[name].append(round((time.perf_counter() - started) * 1000, 2))

    def snapshot(self) -> dict[str, object]:
        return {"counts": dict(self._counts), "latencies_ms": dict(self._latencies)}


metrics = Metrics()
