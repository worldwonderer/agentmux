"""Shared pytest fixtures."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentmux.config import BridgeConfig
from agentmux.session import SessionManager
from agentmux.tmux import TmuxController


@pytest.fixture
def bridge_config(tmp_path: Path) -> BridgeConfig:
    """Return a test BridgeConfig with safe defaults."""
    return BridgeConfig(
        host="127.0.0.1",
        port=8765,
        token="test-token",
        session_prefix="test-bridge",
        window_name="repl",
        workdir=str(tmp_path),
        agent="claude",
        repl_cmd="",
        startup_delay=0.1,
        log_file=str(tmp_path / "bridge.log"),
    )


@pytest.fixture
def mock_logger() -> logging.Logger:
    """Return a MagicMock logger."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def session_manager() -> SessionManager:
    """Return a fresh SessionManager."""
    return SessionManager()


@pytest.fixture
def tmux_controller(
    bridge_config: BridgeConfig,
    mock_logger: logging.Logger,
    monkeypatch: pytest.MonkeyPatch,
) -> TmuxController:
    """Return a TmuxController with mocked tmux binary path."""
    monkeypatch.setattr("agentmux.tmux.find_binary", lambda name, path: "/usr/bin/tmux")
    return TmuxController(bridge_config, mock_logger)
