"""Tests for agentmux.cli."""

import sys
from unittest.mock import MagicMock

import pytest

from agentmux.cli import build_parser, main


class TestBuildParser:
    """Tests for CLI argument parser."""

    def test_default_command_is_serve(self) -> None:
        """Test that no subcommand defaults to serve."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None  # main() treats None as "serve"

    def test_serve_subcommand(self) -> None:
        """Test serve subcommand parsing."""
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"

    def test_send_subcommand(self) -> None:
        """Test send subcommand parsing."""
        parser = build_parser()
        args = parser.parse_args(["send", "hello world"])
        assert args.command == "send"
        assert args.text == "hello world"

    def test_key_subcommand(self) -> None:
        """Test key subcommand parsing."""
        parser = build_parser()
        args = parser.parse_args(["key", "enter", "--repeat", "3"])
        assert args.command == "key"
        assert args.key_name == "enter"
        assert args.repeat == 3

    def test_capture_subcommand(self) -> None:
        """Test capture subcommand parsing."""
        parser = build_parser()
        args = parser.parse_args(["capture", "--lines", "40"])
        assert args.command == "capture"
        assert args.lines == 40


class TestMain:
    """Tests for main entry point."""

    def test_serve_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test main dispatches to serve."""
        mock_serve = MagicMock()
        monkeypatch.setattr("agentmux.cli.serve", mock_serve)
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: MagicMock())
        monkeypatch.setattr(sys, "argv", ["agentmux", "serve"])
        main()
        mock_serve.assert_called_once()

    def test_status_command(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main dispatches to status."""
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: MagicMock())
        monkeypatch.setattr("agentmux.cli.get_bridge_status", lambda c: {"ok": True})
        monkeypatch.setattr(sys, "argv", ["agentmux", "status"])
        main()
        captured = capsys.readouterr()
        assert '"ok": true' in captured.out

    def test_cleanup_command(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main dispatches to cleanup."""
        mock_controller = MagicMock()
        mock_controller.cleanup_old_sessions.return_value = ["sess1"]
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: mock_controller)
        monkeypatch.setattr(sys, "argv", ["agentmux", "cleanup"])
        main()
        captured = capsys.readouterr()
        assert "sess1" in captured.out

    def test_send_command_no_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test send exits with error when no active session."""
        mock_controller = MagicMock()
        mock_controller.sessions.get_active.return_value = None
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: mock_controller)
        monkeypatch.setattr(sys, "argv", ["agentmux", "send", "hello"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_send_command_with_session(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Test send succeeds with an active session."""
        mock_controller = MagicMock()
        mock_controller.sessions.get_active.return_value = MagicMock(target="s:1.0")
        mock_controller.send_literal.return_value = "s:1.0"
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: mock_controller)
        monkeypatch.setattr(sys, "argv", ["agentmux", "send", "hello"])
        main()
        captured = capsys.readouterr()
        assert '"ok": true' in captured.out
        mock_controller.send_literal.assert_called_once_with("hello", target="s:1.0")

    def test_key_command_with_session(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Test key succeeds with an active session."""
        mock_controller = MagicMock()
        mock_controller.sessions.get_active.return_value = MagicMock(target="s:1.0")
        mock_controller.send_special_key.return_value = "s:1.0"
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: mock_controller)
        monkeypatch.setattr(sys, "argv", ["agentmux", "key", "enter", "--repeat", "2"])
        main()
        captured = capsys.readouterr()
        assert '"ok": true' in captured.out
        mock_controller.send_special_key.assert_called_once_with("enter", repeat=2, target="s:1.0")

    def test_capture_command_with_session(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Test capture succeeds with an active session."""
        mock_controller = MagicMock()
        mock_controller.sessions.get_active.return_value = MagicMock(target="s:1.0")
        mock_controller.capture_pane.return_value = {"content": "output"}
        monkeypatch.setattr("agentmux.cli.BridgeConfig", MagicMock)
        monkeypatch.setattr("agentmux.cli.setup_logging", lambda c: MagicMock())
        monkeypatch.setattr("agentmux.cli.TmuxController", lambda _c, _l: mock_controller)
        monkeypatch.setattr(sys, "argv", ["agentmux", "capture", "--lines", "20"])
        main()
        captured = capsys.readouterr()
        assert "output" in captured.out
        mock_controller.capture_pane.assert_called_once_with(lines=20, target="s:1.0")
