"""Tests for agentmux.config."""

import importlib
import logging
import json
from pathlib import Path

import pytest

import agentmux.config as config_module
from agentmux.config import setup_logging


class TestBridgeConfig:
    """Tests for BridgeConfig."""

    def test_default_values(self) -> None:
        """Test that defaults are sensible."""
        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8765
        assert config.token == ""
        assert config.session_prefix == "agentmux"
        assert config.window_name == "repl"
        assert config.repl_cmd == "claude"
        assert config.startup_delay == 3.0
        assert config.allow_external_target is False

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment variable overrides."""
        monkeypatch.setenv("AGENTMUX_HOST", "0.0.0.0")
        monkeypatch.setenv("AGENTMUX_PORT", "9999")
        monkeypatch.setenv("AGENTMUX_TOKEN", "secret")
        monkeypatch.setenv("AGENTMUX_SESSION", "custom-prefix")
        monkeypatch.setenv("AGENTMUX_STARTUP_DELAY", "1.5")
        monkeypatch.setenv("AGENTMUX_ALLOW_EXTERNAL_TARGET", "true")

        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 9999
        assert config.token == "secret"
        assert config.session_prefix == "custom-prefix"
        assert config.startup_delay == 1.5
        assert config.allow_external_target is True

    def test_build_env_uses_default_path_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that build_env falls back to DEFAULT_PATH when PATH is empty."""
        monkeypatch.delenv("PATH", raising=False)
        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        env = config.build_env()
        assert "/usr/bin" in env["PATH"]
        assert "/bin" in env["PATH"]

    def test_build_env_preserves_existing_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that build_env preserves existing PATH."""
        monkeypatch.setenv("PATH", "/custom/bin")
        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        env = config.build_env()
        assert env["PATH"] == "/custom/bin"

    def test_ignores_cwd_config_by_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Test that current-directory config is ignored unless explicitly enabled."""
        config_path = tmp_path / "agentmux.json"
        config_path.write_text(json.dumps({"host": "0.0.0.0"}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AGENTMUX_ALLOW_CWD_CONFIG", raising=False)
        monkeypatch.delenv("AGENTMUX_CONFIG_FILE", raising=False)

        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.host == "127.0.0.1"

    def test_allows_cwd_config_when_opted_in(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Test that current-directory config can be re-enabled explicitly."""
        config_path = tmp_path / "agentmux.json"
        config_path.write_text(json.dumps({"host": "0.0.0.0"}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AGENTMUX_ALLOW_CWD_CONFIG", "1")

        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.host == "0.0.0.0"


class TestSetupLogging:
    """Tests for setup_logging."""

    def test_creates_log_file(self, tmp_path: Path) -> None:
        """Test that setup_logging creates the log file and directories."""
        config = config_module.BridgeConfig(log_file=str(tmp_path / "nested" / "bridge.log"))
        logger = setup_logging(config)
        assert logger.name == "bridge"
        assert (tmp_path / "nested" / "bridge.log").exists()

    def test_idempotent_handlers(self, tmp_path: Path) -> None:
        """Test that multiple calls do not duplicate handlers."""
        config = config_module.BridgeConfig(log_file=str(tmp_path / "bridge.log"))
        logger_base = logging.getLogger("bridge")
        logger_base.handlers.clear()
        logger1 = setup_logging(config)
        handler_count = len(logger1.handlers)
        logger2 = setup_logging(config)
        assert len(logger2.handlers) == handler_count
