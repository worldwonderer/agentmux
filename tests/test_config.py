"""Tests for agentmux.config."""

import importlib
import json
import logging
import os
from pathlib import Path

import pytest

import agentmux.config as config_module
from agentmux.config import setup_logging


class TestBridgeConfig:
    """Tests for BridgeConfig."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that defaults are sensible."""
        for key in list(os.environ):
            if key.startswith("AGENTMUX_"):
                monkeypatch.delenv(key, raising=False)
        reloaded = importlib.reload(config_module)
        reloaded._FILE_CFG = {}
        config = reloaded.BridgeConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8765
        assert config.token == ""
        assert config.session_prefix == "agentmux"
        assert config.window_name == "repl"
        assert config.agent == "claude"
        assert config.repl_cmd == ""
        assert config.startup_delay == -1.0
        assert config.effective_repl_cmd == "claude"
        assert config.effective_startup_delay == 3.0
        assert config.allow_external_target is False

    def test_profile_property(self) -> None:
        """Test profile returns correct AgentProfile."""
        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.profile.name == "claude"
        assert config.profile.idle_pattern == r"❯\s*$"

    def test_codex_agent_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Codex agent profile defaults."""
        for key in list(os.environ):
            if key.startswith("AGENTMUX_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("AGENTMUX_AGENT", "codex")
        reloaded = importlib.reload(config_module)
        reloaded._FILE_CFG = {}
        config = reloaded.BridgeConfig()
        assert config.agent == "codex"
        assert config.effective_repl_cmd == "codex --no-alt-screen --full-auto"
        assert config.effective_startup_delay == 5.0
        assert config.profile.name == "codex"

    def test_explicit_repl_cmd_overrides_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that explicit repl_cmd takes priority over profile default."""
        monkeypatch.setenv("AGENTMUX_AGENT", "codex")
        monkeypatch.setenv("AGENTMUX_REPL_CMD", "codex --no-alt-screen")
        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.effective_repl_cmd == "codex --no-alt-screen"

    def test_explicit_startup_delay_overrides_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that explicit startup_delay takes priority over profile default."""
        monkeypatch.setenv("AGENTMUX_AGENT", "codex")
        monkeypatch.setenv("AGENTMUX_STARTUP_DELAY", "2.0")
        reloaded = importlib.reload(config_module)
        config = reloaded.BridgeConfig()
        assert config.effective_startup_delay == 2.0

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
        """Test that file config values are used when no env override."""
        monkeypatch.delenv("AGENTMUX_HOST", raising=False)
        reloaded = importlib.reload(config_module)
        reloaded._FILE_CFG = {"host": "0.0.0.0"}
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
