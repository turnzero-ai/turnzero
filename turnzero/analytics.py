"""Session analytics and estimated ROI for TurnZero."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ROI constants — single source of truth for both CLI stats and SessionAnalytics.
# Changing these propagates to all display surfaces.
# ---------------------------------------------------------------------------

# Turns saved per injected block (conservative estimate for stats display).
# Distinct from TURNS_SAVED_PER_PRIOR (2.5) which measures correction avoidance.
TURNS_SAVED_PER_INJECTION: float = 0.5
TOKENS_PER_TURN: int = 1500  # matches SessionAnalytics.TOKENS_PER_TURN


@dataclass
class SessionEvent:
    timestamp: float
    event_type: str  # injection | miss | solve
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionAnalytics:
    session_id: str
    start_time: float
    events: list[SessionEvent] = field(default_factory=list)
    project_root: Path | None = None

    # Rough estimates — 1 prior ≈ 1 avoided correction turn, ~1500 tokens, ~4 min
    TURNS_SAVED_PER_PRIOR: float = 2.5
    TOKENS_PER_TURN: int = 1500
    MINUTES_PER_TURN: float = 4.0

    def log_injection(self, block_ids: list[str]) -> None:
        """Append injection event for ROI tracking. State recording is the caller's responsibility."""
        self.events.append(
            SessionEvent(
                timestamp=time.time(),
                event_type="injection",
                details={"block_ids": block_ids},
            )
        )

    def log_miss(self, correction_text: str) -> None:
        """Log a moment where TurnZero failed to provide the right context."""
        self.events.append(
            SessionEvent(
                timestamp=time.time(),
                event_type="miss",
                details={"correction": correction_text[:100]},
            )
        )

    def calculate_roi(self) -> dict[str, Any]:
        """Compute estimated ROI metrics for this session."""
        injections = [e for e in self.events if e.event_type == "injection"]
        misses = [e for e in self.events if e.event_type == "miss"]

        # Net avoided knowledge gaps
        # A miss means we didn't save any turns, and actually cost the user time
        # to correct and then eventually harvest.
        net_priors = len(injections) - len(misses)

        turns_saved = max(0, net_priors * self.TURNS_SAVED_PER_PRIOR)
        tokens_saved = int(turns_saved * self.TOKENS_PER_TURN)
        minutes_saved = round(turns_saved * self.MINUTES_PER_TURN, 1)

        return {
            "session_id": self.session_id,
            "turns_saved": turns_saved,
            "tokens_saved": tokens_saved,
            "minutes_saved": minutes_saved,
            "injection_count": len(injections),
            "miss_count": len(misses),
            "precision_rate": len(injections) / (len(injections) + len(misses))
            if (len(injections) + len(misses)) > 0
            else 1.0,
        }

    def save(self, data_dir: Path) -> Path:
        session_dir = data_dir / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)

        path = session_dir / f"{self.session_id}.json"

        # Simple serialisation
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


def get_global_roi(data_dir: Path) -> dict[str, Any]:
    """Aggregate ROI across all historical sessions. Kept for backwards compat — prefer stats_svc."""
    from turnzero.services import stats_svc

    return stats_svc.get_global_roi(data_dir)
