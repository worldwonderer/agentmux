"""Tests for agentmux.tmux."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agentmux.tmux import TmuxController, find_binary, run_command


class TestFindBinary:
    """Tests for find_binary."""

    def test_finds_executable(self) -> None:
        """Test finding a binary that exists."""
        result = find_binary("python3", "/usr/bin:/bin")
        assert result is not None

    def test_raises_when_not_found(self) -> None:
        """Test FileNotFoundError for missing binary."""
        with pytest.raises(FileNotFoundError, match="nonexistent-binary"):
            find_binary("nonexistent-binary", "/usr/bin")


class TestRunCommand:
    """Tests for run_command."""

    def test_success(self) -> None:
        """Test successful command execution."""
        result = run_command(["echo", "hello"], env={"PATH": "/usr/bin"})
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_failure_raises(self) -> None:
        """Test failed command raises RuntimeError."""
        with pytest.raises(RuntimeError):
            run_command(["false"], env={"PATH": "/usr/bin"})

    def test_no_check_does_not_raise(self) -> None:
        """Test check=False suppresses exception."""
        result = run_command(["false"], env={"PATH": "/usr/bin"}, check=False)
        assert result.returncode != 0


class TestTmuxController:
    """Tests for TmuxController."""

    def test_resolve_target_explicit_managed(self, tmux_controller: TmuxController) -> None:
        """Test resolve_target accepts a managed explicit target."""
        tmux_controller.sessions.register("sess", "sess:1.0")
        assert tmux_controller.resolve_target("sess:1.0") == "sess:1.0"

    def test_resolve_target_unmanaged_raises(self, tmux_controller: TmuxController) -> None:
        """Test resolve_target rejects unmanaged explicit targets by default."""
        with pytest.raises(ValueError, match="not managed"):
            tmux_controller.resolve_target("sess:1.0")

    def test_resolve_target_external_allowed(self, tmux_controller: TmuxController) -> None:
        """Test resolve_target accepts unmanaged target when explicitly enabled."""
        tmux_controller.config.allow_external_target = True
        assert tmux_controller.resolve_target("sess:1.0") == "sess:1.0"

    def test_resolve_target_from_active_session(self, tmux_controller: TmuxController) -> None:
        """Test resolve_target falls back to active session."""
        tmux_controller.sessions.register("sess", "sess:1.0")
        assert tmux_controller.resolve_target() == "sess:1.0"

    def test_resolve_target_no_active_raises(self, tmux_controller: TmuxController) -> None:
        """Test resolve_target raises when no active session."""
        with pytest.raises(RuntimeError, match="No active session"):
            tmux_controller.resolve_target()

    def test_send_literal(self, tmux_controller: TmuxController) -> None:
        """Test send_literal invokes tmux correctly."""
        tmux_controller.sessions.register("s", "s:1.0")
        with patch.object(tmux_controller, "_run_tmux") as mock_run:
            result = tmux_controller.send_literal("hello", press_enter=True)
            assert result == "s:1.0"
            assert mock_run.call_count == 2
            assert mock_run.call_args_list[0][0][0] == ["send-keys", "-t", "s:1.0", "-l", "hello"]
            assert mock_run.call_args_list[1][0][0] == ["send-keys", "-t", "s:1.0", "Enter"]

    def test_send_special_key(self, tmux_controller: TmuxController) -> None:
        """Test send_special_key maps names correctly."""
        tmux_controller.sessions.register("s", "s:1.0")
        with patch.object(tmux_controller, "_run_tmux") as mock_run:
            tmux_controller.send_special_key("enter", repeat=2)
            assert mock_run.call_count == 2
            assert mock_run.call_args_list[0][0][0] == ["send-keys", "-t", "s:1.0", "Enter"]

    def test_send_special_key_invalid(self, tmux_controller: TmuxController) -> None:
        """Test send_special_key raises for unknown keys."""
        tmux_controller.sessions.register("s", "s:1.0")
        with pytest.raises(ValueError, match="Unsupported key"):
            tmux_controller.send_special_key("f13")

    def test_send_special_key_clamps_repeat(self, tmux_controller: TmuxController) -> None:
        """Test repeat count is clamped to 50."""
        tmux_controller.sessions.register("s", "s:1.0")
        with patch.object(tmux_controller, "_run_tmux") as mock_run:
            tmux_controller.send_special_key("up", repeat=100)
            assert mock_run.call_count == 50

    def test_capture_pane(self, tmux_controller: TmuxController) -> None:
        """Test capture_pane parses output correctly."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "line1\nline2"
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            result = tmux_controller.capture_pane(lines=20)
            assert result["target"] == "s:1.0"
            assert result["lines"] == 20
            assert result["content"] == "line1\nline2"

    def test_capture_pane_clamps_lines(self, tmux_controller: TmuxController) -> None:
        """Test lines parameter is clamped."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = ""
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            assert tmux_controller.capture_pane(lines=5)["lines"] == 10
            assert tmux_controller.capture_pane(lines=1000)["lines"] == 500

    def test_is_idle_detects_prompt(self, tmux_controller: TmuxController) -> None:
        """Test is_idle detects the Claude idle prompt."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "some line\n❯ "
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            assert tmux_controller.is_idle() is True

    def test_is_idle_not_idle(self, tmux_controller: TmuxController) -> None:
        """Test is_idle returns False when prompt not present."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "thinking...\nanother line"
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            assert tmux_controller.is_idle() is False

    def test_get_ctx_percent(self, tmux_controller: TmuxController) -> None:
        """Test extracting ctx percentage."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "status ctx:42% more"
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            assert tmux_controller.get_ctx_percent() == 42

    def test_get_ctx_percent_none(self, tmux_controller: TmuxController) -> None:
        """Test None when ctx not found."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "no ctx here"
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            assert tmux_controller.get_ctx_percent() is None

    def test_dismiss_trust_prompt(self, tmux_controller: TmuxController) -> None:
        """Test trust prompt dismissal."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "Do you trust this folder?"
        with (
            patch.object(tmux_controller, "_run_tmux", return_value=mock_result),
            patch.object(tmux_controller, "send_special_key") as mock_key,
        ):
            dismissed = tmux_controller.dismiss_trust_prompt()
            assert dismissed is True
            mock_key.assert_called_once_with("enter", target=None)

    def test_dismiss_trust_prompt_not_present(self, tmux_controller: TmuxController) -> None:
        """Test no-op when trust prompt absent."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "normal output"
        with (
            patch.object(tmux_controller, "_run_tmux", return_value=mock_result),
            patch.object(tmux_controller, "send_special_key") as mock_key,
        ):
            dismissed = tmux_controller.dismiss_trust_prompt()
            assert dismissed is False
            mock_key.assert_not_called()

    def test_generate_session_name_format(self, tmux_controller: TmuxController) -> None:
        """Test session name contains prefix and timestamp."""
        name = tmux_controller.generate_session_name()
        assert name.startswith("test-bridge-")
        parts = name.split("-")
        assert len(parts) == 4

    def test_session_exists(self, tmux_controller: TmuxController) -> None:
        """Test session_exists delegates to tmux."""
        with patch.object(tmux_controller, "_run_tmux") as mock_run:
            mock_run.return_value.returncode = 0
            assert tmux_controller.session_exists("sess") is True
            mock_run.return_value.returncode = 1
            assert tmux_controller.session_exists("sess") is False

    def test_resolve_target_for(self, tmux_controller: TmuxController) -> None:
        """Test resolving target from window list."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "0\tother\n1\trepl\n"
        with patch.object(tmux_controller, "_run_tmux", return_value=mock_result):
            target = tmux_controller.resolve_target_for("sess")
            assert target == "sess:1.0"

    def test_resolve_target_for_not_found(self, tmux_controller: TmuxController) -> None:
        """Test RuntimeError when window not found."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "0\tother\n"
        with (
            patch.object(tmux_controller, "_run_tmux", return_value=mock_result),
            pytest.raises(RuntimeError, match="Unable to find window"),
        ):
            tmux_controller.resolve_target_for("sess")

    def test_wait_for_repl_ready_success(self, tmux_controller: TmuxController) -> None:
        """Test ready detection succeeds when prompt appears."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "❯ "
        with (
            patch.object(tmux_controller, "_run_tmux", return_value=mock_result),
            patch("agentmux.tmux.time.sleep", return_value=None),
        ):
            ready = tmux_controller.wait_for_repl_ready(target="s:1.0", timeout=2)
            assert ready is True

    def test_wait_for_repl_ready_timeout(self, tmux_controller: TmuxController) -> None:
        """Test ready detection times out."""
        tmux_controller.sessions.register("s", "s:1.0")
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.stdout = "loading..."
        with (
            patch.object(tmux_controller, "_run_tmux", return_value=mock_result),
            patch("agentmux.tmux.time.sleep", return_value=None),
        ):
            ready = tmux_controller.wait_for_repl_ready(target="s:1.0", timeout=0.01)
            assert ready is False

    def test_rollback_session(self, tmux_controller: TmuxController) -> None:
        """Test rollback_session removes tracked state."""
        tmux_controller.sessions.register("s", "s:1.0")
        with patch.object(tmux_controller, "_run_tmux") as mock_run:
            tmux_controller.rollback_session("s")
            mock_run.assert_called_once_with(["kill-session", "-t", "s"], check=False)
        assert tmux_controller.sessions.get("s") is None

    def test_kill_session(self, tmux_controller: TmuxController) -> None:
        """Test kill_session removes tracked session."""
        tmux_controller.sessions.register("s", "s:1.0")
        with (
            patch.object(tmux_controller, "session_exists", return_value=True),
            patch.object(tmux_controller, "_run_tmux") as mock_run,
        ):
            tmux_controller.kill_session("s")
            mock_run.assert_called_once_with(["kill-session", "-t", "s"])
        assert tmux_controller.sessions.get("s") is None

    def test_cleanup_old_sessions(self, tmux_controller: TmuxController) -> None:
        """Test cleanup kills only idle non-active sessions."""
        tmux_controller.sessions.register("old", "o:1.0")
        tmux_controller.sessions.register("active", "a:1.0")

        with (
            patch.object(tmux_controller, "session_exists", return_value=True),
            patch.object(tmux_controller, "is_idle", return_value=True),
            patch.object(tmux_controller, "kill_session") as mock_kill,
        ):
            killed = tmux_controller.cleanup_old_sessions()
            assert "old" in killed
            assert "active" not in killed
            mock_kill.assert_called_once_with("old")

    def test_cleanup_removes_dead_sessions(self, tmux_controller: TmuxController) -> None:
        """Test cleanup removes sessions that no longer exist in tmux."""
        tmux_controller.sessions.register("dead", "d:1.0")
        tmux_controller.sessions.register("active", "a:1.0")

        def exists(name: str) -> bool:
            return name == "active"

        with patch.object(tmux_controller, "session_exists", side_effect=exists):
            killed = tmux_controller.cleanup_old_sessions()
            assert "dead" in killed
            assert tmux_controller.sessions.get("dead") is None

    def test_create_session(self, tmux_controller: TmuxController) -> None:
        """Test create_session registers and activates a new session."""
        with (
            patch.object(tmux_controller, "_run_tmux"),
            patch.object(tmux_controller, "resolve_target_for", return_value="sess:1.0"),
            patch.object(tmux_controller, "send_literal"),
            patch.object(tmux_controller, "dismiss_trust_prompt"),
            patch("agentmux.tmux.time.sleep", return_value=None),
        ):
            info = tmux_controller.create_session("sess")
            assert info.name == "sess"
            assert info.target == "sess:1.0"
            assert info.status == "active"
            assert tmux_controller.sessions.active == "sess"

    def test_create_session_rolls_back_on_failure(self, tmux_controller: TmuxController) -> None:
        """Test create_session rolls back partially created sessions on failure."""
        with (
            patch.object(tmux_controller, "_run_tmux"),
            patch.object(tmux_controller, "resolve_target_for", return_value="sess:1.0"),
            patch.object(
                tmux_controller,
                "send_literal",
                side_effect=["sess:1.0", RuntimeError("boom")],
            ),
            patch.object(tmux_controller, "rollback_session") as mock_rollback,
            patch("agentmux.tmux.time.sleep", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                tmux_controller.create_session("sess")
            info = tmux_controller.sessions.get("sess")
            assert info is not None
            assert info.status == "error"
            mock_rollback.assert_called_once_with("sess")
