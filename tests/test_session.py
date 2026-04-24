"""Tests for agentmux.session."""

import threading
import time

from agentmux.session import SessionInfo, SessionManager


class TestSessionInfo:
    """Tests for SessionInfo dataclass."""

    def test_defaults(self) -> None:
        """Test default field values."""
        info = SessionInfo(name="test")
        assert info.name == "test"
        assert info.target == ""
        assert info.status == "active"
        assert time.time() - info.created_at < 1.0


class TestSessionManager:
    """Tests for SessionManager."""

    def test_register_and_get(self, session_manager: SessionManager) -> None:
        """Test registering and retrieving a session."""
        info = session_manager.register("sess1", "target1")
        assert info.name == "sess1"
        assert info.target == "target1"
        assert session_manager.get("sess1") == info
        assert session_manager.active == "sess1"

    def test_register_with_custom_status(self, session_manager: SessionManager) -> None:
        """Test registering a session with a non-default status."""
        info = session_manager.register("sess1", "target1", status="creating")
        assert info.status == "creating"

    def test_get_active_returns_none_when_empty(self) -> None:
        """Test get_active with no sessions."""
        mgr = SessionManager()
        assert mgr.get_active() is None

    def test_find_by_target(self, session_manager: SessionManager) -> None:
        """Test finding a tracked session by its tmux target."""
        session_manager.register("a", "t1")
        found = session_manager.find_by_target("t1")
        assert found is not None
        assert found.name == "a"
        assert session_manager.find_by_target("missing") is None

    def test_list_sessions_snapshot(self, session_manager: SessionManager) -> None:
        """Test list_sessions returns a snapshot."""
        session_manager.register("a", "t1")
        session_manager.register("b", "t2")
        sessions = session_manager.list_sessions()
        assert len(sessions) == 2
        sessions.clear()
        assert len(session_manager.list_sessions()) == 2

    def test_remove_inactive_session(self, session_manager: SessionManager) -> None:
        """Test removing a non-active session."""
        session_manager.register("active", "t1")
        session_manager.register("other", "t2")
        session_manager.remove("other")
        assert session_manager.get("other") is None
        assert session_manager.active == "active"

    def test_remove_active_session_switches_to_latest(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Test removing active session auto-switches to the latest."""
        session_manager.register("old", "t1")
        time.sleep(0.01)
        session_manager.register("new", "t2")
        session_manager.remove("new")
        assert session_manager.active == "old"

    def test_remove_last_session_clears_active(self, session_manager: SessionManager) -> None:
        """Test removing the only session clears active."""
        session_manager.register("only", "t1")
        session_manager.remove("only")
        assert session_manager.active == ""

    def test_set_status(self, session_manager: SessionManager) -> None:
        """Test updating a tracked session status."""
        session_manager.register("s", "t")
        info = session_manager.set_status("s", "error")
        assert info is not None
        assert info.status == "error"

    def test_mark_completed(self, session_manager: SessionManager) -> None:
        """Test marking a session as completed."""
        session_manager.register("s", "t")
        session_manager.mark_completed("s")
        info = session_manager.get("s")
        assert info is not None
        assert info.status == "completed"

    def test_mark_completed_unknown_session(self, session_manager: SessionManager) -> None:
        """Test marking an unknown session is a no-op."""
        session_manager.mark_completed("nonexistent")

    def test_session_count(self, session_manager: SessionManager) -> None:
        """Test session_count tracking."""
        assert session_manager.session_count() == 0
        session_manager.register("a", "t1")
        assert session_manager.session_count() == 1
        session_manager.register("b", "t2")
        assert session_manager.session_count() == 2

    def test_thread_safety(self, session_manager: SessionManager) -> None:
        """Test concurrent registration does not corrupt state."""
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                session_manager.register(f"sess-{idx}", f"target-{idx}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert session_manager.session_count() == 50
