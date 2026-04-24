"""Session management for agentmux."""

import threading
import time
from dataclasses import dataclass, field


@dataclass
class SessionInfo:
    """Track state for a single tmux session."""

    name: str
    created_at: float = field(default_factory=time.time)
    target: str = ""
    status: str = "active"  # creating | active | completed | error


class SessionManager:
    """Manage multiple named tmux sessions (thread-safe)."""

    MAX_SESSIONS = 10

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._active: str = ""
        self._lock = threading.Lock()

    @property
    def active(self) -> str:
        """Return the name of the currently active session."""
        with self._lock:
            return self._active

    def get(self, name: str) -> SessionInfo | None:
        """Get a session by name."""
        with self._lock:
            return self._sessions.get(name)

    def get_active(self) -> SessionInfo | None:
        """Get the currently active session."""
        with self._lock:
            if self._active:
                return self._sessions.get(self._active)
            return None

    def find_by_target(self, target: str) -> SessionInfo | None:
        """Return the session that owns a tmux target, if any."""
        with self._lock:
            for session in self._sessions.values():
                if session.target == target:
                    return session
            return None

    def list_sessions(self) -> list[SessionInfo]:
        """Return a snapshot of all tracked sessions."""
        with self._lock:
            return list(self._sessions.values())

    def register(self, name: str, target: str, *, status: str = "active") -> SessionInfo:
        """Register a new session and make it active."""
        with self._lock:
            info = SessionInfo(name=name, target=target, status=status)
            self._sessions[name] = info
            self._active = name
            return info

    def set_status(self, name: str, status: str) -> SessionInfo | None:
        """Update the status of a tracked session."""
        with self._lock:
            info = self._sessions.get(name)
            if info is not None:
                info.status = status
            return info

    def mark_completed(self, name: str) -> None:
        """Mark a session as completed."""
        self.set_status(name, "completed")

    def remove(self, name: str) -> None:
        """Remove a session and update active session if needed."""
        with self._lock:
            self._sessions.pop(name, None)
            if self._active == name:
                if self._sessions:
                    latest = max(self._sessions.values(), key=lambda session: session.created_at)
                    self._active = latest.name
                else:
                    self._active = ""

    def session_count(self) -> int:
        """Return the number of tracked sessions."""
        with self._lock:
            return len(self._sessions)
