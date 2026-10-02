"""Session analytics — per-session injection event log."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionEvent:
    timestamp: float
    event_type: str  # injection
    details: dict[str, Any] = field(default_factory=dict)  # free-form event payload


@dataclass
class SessionAnalytics:
    session_id: str
    start_time: float
    events: list[SessionEvent] = field(default_factory=list)
    project_root: Path | None = None

    def log_injection(self, block_ids: list[str]) -> None:
        """Append an injection event. State recording is the caller's responsibility."""
        self.events.append(
            SessionEvent(
                timestamp=time.time(),
                event_type="injection",
                details={"block_ids": block_ids},
            )
        )

    def save(self, data_dir: Path) -> Path:
        session_dir = data_dir / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        path = session_dir / f"{self.session_id}.json"
        data = {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "project_root": str(self.project_root) if self.project_root else None,
            "events": [
                {"timestamp": e.timestamp, "type": e.event_type, "details": e.details}
                for e in self.events
            ],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, session_id: str, data_dir: Path) -> SessionAnalytics:
        path = data_dir / "sessions" / f"{session_id}.json"
        if not path.exists():
            return cls(session_id=session_id, start_time=time.time())

        data = json.loads(path.read_text(encoding="utf-8"))
        events = [
            SessionEvent(
                timestamp=e["timestamp"], event_type=e["type"], details=e["details"]
            )
            for e in data["events"]
        ]
        project_root = Path(data["project_root"]) if data.get("project_root") else None
        return cls(
            session_id=data["session_id"],
            start_time=data["start_time"],
            events=events,
            project_root=project_root,
        )
