"""Per-gateway webhook registration state (URL, schedule, time scale)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .delivery import DEFAULT_SCHEDULE, SCHEDULES


@dataclass
class Registration:
    url: str
    schedule_key: str
    schedule: list[int]


@dataclass
class Registry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    per_gateway: dict[str, Registration] = field(default_factory=dict)

    def register(self, gateway: str, url: str, schedule: str | None = None) -> Registration:
        key = schedule or DEFAULT_SCHEDULE[gateway]
        if key not in SCHEDULES:
            raise ValueError(f"unknown schedule: {key} (known: {', '.join(SCHEDULES)})")
        reg = Registration(url=url, schedule_key=key, schedule=list(SCHEDULES[key]))
        with self.lock:
            self.per_gateway[gateway] = reg
        return reg

    def get(self, gateway: str) -> Registration | None:
        with self.lock:
            return self.per_gateway.get(gateway)


registry = Registry()
