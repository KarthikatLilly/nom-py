"""
RequestContext — threaded through the request pipeline so each stage
can record structured events as they happen.
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.auth.models import Principal


@dataclass
class RequestContext:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    method: str = ""
    principal: Principal | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)

    def record(self, stage: str, **fields: Any) -> None:
        """Append a structured event to the trace."""
        self.events.append({
            "stage": stage,
            "t_ms": round((time.monotonic() - self.started_at) * 1000, 2),
            **fields,
        })

    @property
    def duration_ms(self) -> float:
        return round((time.monotonic() - self.started_at) * 1000, 2)