"""Configuration management for agentmux."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from agentmux.agent_profile import get_profile
from agentmux.constants import DEFAULT_PATH


def _is_truthy(value: str | None) -> bool:
    """Return whether a string value should be treated as enabled."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_config_file() -> dict[str, Any]:
    """Load JSON config from trusted standard paths."""
    paths: list[Path] = []
    env_path = os.environ.get("AGENTMUX_CONFIG_FILE")
    if env_path:
        paths.append(Path(env_path).expanduser())

    paths.append(Path.home() / ".config" / "agentmux" / "config.json")

    if _is_truthy(os.environ.get("AGENTMUX_ALLOW_CWD_CONFIG")):
        paths.append(Path.cwd() / "agentmux.json")

    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as file_obj:
                return cast(dict[str, Any], json.load(file_obj))
        except (json.JSONDecodeError, OSError, TypeError):
            continue
    return {}


# Load once at module import time (config files do not change during runtime).
_FILE_CFG = _load_config_file()


def _env_or_file(env_name: str, file_key: str, default: str) -> str:
    """Resolve a config value: env > file > default."""
    file_val = cast(str, _FILE_CFG.get(file_key, default))
    return os.environ.get(env_name, file_val)


def _env_or_file_int(env_name: str, file_key: str, default: int) -> int:
    """Resolve an integer config value: env > file > default."""
    file_val = cast(str, _FILE_CFG.get(file_key, str(default)))
    return int(os.environ.get(env_name, file_val))


def _env_or_file_float(env_name: str, file_key: str, default: float) -> float:
    """Resolve a float config value: env > file > default."""
    file_val = cast(str, _FILE_CFG.get(file_key, str(default)))
    return float(os.environ.get(env_name, file_val))


def _env_or_file_bool(env_name: str, file_key: str, default: bool) -> bool:
    """Resolve a boolean config value: env > file > default."""
    env_value = os.environ.get(env_name)
    if env_value is not None:
        return _is_truthy(env_value)

    file_value = _FILE_CFG.get(file_key)
    if isinstance(file_value, bool):
        return file_value
    if isinstance(file_value, str):
        return _is_truthy(file_value)
    return default


@dataclass
class BridgeConfig:
    """Runtime configuration loaded from environment variables and optional config file."""

    host: str = field(default_factory=lambda: _env_or_file("AGENTMUX_HOST", "host", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_or_file_int("AGENTMUX_PORT", "port", 8765))
    token: str = field(default_factory=lambda: _env_or_file("AGENTMUX_TOKEN", "token", ""))
    session_prefix: str = field(
        default_factory=lambda: _env_or_file("AGENTMUX_SESSION", "session_prefix", "agentmux")
    )
    window_name: str = field(
        default_factory=lambda: _env_or_file("AGENTMUX_WINDOW", "window_name", "repl")
    )
    workdir: str = field(
        default_factory=lambda: _env_or_file("AGENTMUX_WORKDIR", "workdir", str(Path.home()))
    )
    agent: str = field(default_factory=lambda: _env_or_file("AGENTMUX_AGENT", "agent", "claude"))
    repl_cmd: str = field(default_factory=lambda: _env_or_file("AGENTMUX_REPL_CMD", "repl_cmd", ""))
    startup_delay: float = field(
        default_factory=lambda: _env_or_file_float("AGENTMUX_STARTUP_DELAY", "startup_delay", -1.0)
    )
    log_file: str = field(
        default_factory=lambda: _env_or_file(
            "AGENTMUX_LOG_FILE",
            "log_file",
            str(Path.home() / ".agentmux" / "agentmux.log"),
        )
    )
    allow_external_target: bool = field(
        default_factory=lambda: _env_or_file_bool(
            "AGENTMUX_ALLOW_EXTERNAL_TARGET",
            "allow_external_target",
            False,
        )
    )

    @property
    def profile(self):
        """Return the agent profile for the current agent type."""
        return get_profile(self.agent)

    @property
    def effective_repl_cmd(self) -> str:
        """Return repl_cmd if explicitly set, otherwise the profile default."""
        return self.repl_cmd or self.profile.default_repl_cmd

    @property
    def effective_startup_delay(self) -> float:
        """Return startup_delay if explicitly set, otherwise the profile default."""
        if self.startup_delay >= 0:
            return self.startup_delay
        return self.profile.default_startup_delay

    def build_env(self) -> dict[str, str]:
        """Return a process environment with a launchd-safe PATH."""
        env = os.environ.copy()
        env["PATH"] = env.get("PATH") or DEFAULT_PATH
        return env


def setup_logging(config: BridgeConfig) -> logging.Logger:
    """Configure file logging for the bridge."""
    logger = logging.getLogger("bridge")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    return logger
