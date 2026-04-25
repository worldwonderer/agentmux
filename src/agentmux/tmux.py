"""Tmux operations and session lifecycle for agentmux."""

import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any

from agentmux.config import BridgeConfig
from agentmux.constants import SPECIAL_KEYS
from agentmux.session import SessionInfo, SessionManager


def find_binary(name: str, path: str) -> str:
    """Find an executable from a launchd-friendly PATH set."""
    result = shutil.which(name, path=path)
    if result:
        return result
    raise FileNotFoundError(f"Unable to find required executable: {name}")


def run_command(
    args: list[str],
    *,
    env: dict[str, str],
    timeout: float = 10,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command with shared environment and text output."""
    result = subprocess.run(
        args,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "command failed")
    return result


class TmuxController:
    """Encapsulates all tmux operations and session lifecycle."""

    def __init__(
        self,
        config: BridgeConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.env = config.build_env()
        self.tmux_bin = find_binary("tmux", self.env["PATH"])
        self.logger = logger or logging.getLogger("bridge")
        self.sessions = SessionManager()
        self.lifecycle_lock = threading.RLock()

    def _run_tmux(
        self,
        args: list[str],
        *,
        timeout: float = 10,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a tmux command."""
        return run_command(
            [self.tmux_bin, *args],
            env=self.env,
            timeout=timeout,
            check=check,
        )

    def session_exists(self, name: str) -> bool:
        """Return whether a specific tmux session exists."""
        result = self._run_tmux(["has-session", "-t", name], check=False)
        return result.returncode == 0

    def resolve_target_for(self, session_name: str) -> str:
        """Resolve the pane target for a given session."""
        result = self._run_tmux(
            ["list-windows", "-t", session_name, "-F", "#{window_index}\t#{window_name}"]
        )
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            index, name = line.split("\t", 1)
            if name == self.config.window_name:
                return f"{session_name}:{index}.0"
        raise RuntimeError(
            f"Unable to find window '{self.config.window_name}' in session '{session_name}'"
        )

    def resolve_target(self, target: str | None = None) -> str:
        """Resolve pane target and reject unmanaged explicit targets by default."""
        if target:
            if self.config.allow_external_target or self.sessions.find_by_target(target):
                return target
            raise ValueError("target is not managed by agentmux")

        info = self.sessions.get_active()
        if info and info.target:
            return info.target
        raise RuntimeError("No active session")

    def send_literal(
        self,
        text: str,
        *,
        press_enter: bool = True,
        target: str | None = None,
    ) -> str:
        """Send literal text into the REPL tmux pane."""
        resolved_target = self.resolve_target(target)
        self._run_tmux(["send-keys", "-t", resolved_target, "-l", text])
        if press_enter:
            time.sleep(0.2)
            self._run_tmux(["send-keys", "-t", resolved_target, "Enter"])
        self.logger.info("send_literal: %s (enter=%s)", text[:80], press_enter)
        return resolved_target

    def send_special_key(
        self,
        key_name: str,
        *,
        repeat: int = 1,
        target: str | None = None,
    ) -> str:
        """Send a non-text tmux key into the REPL pane."""
        resolved_target = self.resolve_target(target)
        tmux_key = SPECIAL_KEYS.get(key_name.lower())
        if not tmux_key:
            supported = ", ".join(sorted(SPECIAL_KEYS))
            raise ValueError(f"Unsupported key '{key_name}'. Supported keys: {supported}")
        safe_repeat = max(1, min(repeat, 50))
        for index in range(safe_repeat):
            if index:
                time.sleep(0.08)
            self._run_tmux(["send-keys", "-t", resolved_target, tmux_key])
        self.logger.info("send_key: %s x%d", key_name, safe_repeat)
        return resolved_target

    def capture_pane(
        self,
        *,
        lines: int = 60,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Capture recent pane output for monitoring or debugging."""
        resolved_target = self.resolve_target(target)
        safe_lines = max(10, min(lines, 500))
        result = self._run_tmux(
            ["capture-pane", "-p", "-t", resolved_target, "-S", f"-{safe_lines}"]
        )
        return {"target": resolved_target, "lines": safe_lines, "content": result.stdout}

    def is_idle(self, *, target: str | None = None) -> bool:
        """Check if the agent REPL is at the idle prompt."""
        pattern = self.config.profile.idle_pattern
        capture = self.capture_pane(lines=15, target=target)
        content = capture.get("content", "")
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        tail = "\n".join(lines[-5:])
        return bool(re.search(pattern, tail, re.MULTILINE))

    def get_ctx_percent(self, *, target: str | None = None) -> int | None:
        """Extract context/token usage percentage from the agent status bar."""
        pattern = self.config.profile.ctx_pattern
        if pattern is None:
            return None
        capture = self.capture_pane(lines=5, target=target)
        content = capture.get("content", "")
        match = re.search(pattern, content)
        return int(match.group(1)) if match else None

    def dismiss_trust_prompt(self, *, target: str | None = None) -> bool:
        """Dismiss the trust folder prompt if present."""
        if not self.config.profile.has_trust_prompt:
            return False
        capture = self.capture_pane(lines=20, target=target)
        content = capture.get("content", "").lower()
        if "trust this folder" in content or "trust the contents" in content:
            self.logger.info("Dismissing trust prompt")
            self.send_special_key("enter", target=target)
            time.sleep(self.config.effective_startup_delay)
            return True
        return False

    def dismiss_bypass_warning(self, *, target: str | None = None) -> bool:
        """Accept the --dangerously-skip-permissions warning."""
        if not self.config.profile.has_bypass_warning:
            return False
        capture = self.capture_pane(lines=25, target=target)
        content = capture.get("content", "")
        if "yes, i accept" in content.lower():
            self.logger.info("Accepting bypass permissions warning")
            self.send_special_key("down", target=target)
            time.sleep(0.3)
            self.send_special_key("enter", target=target)
            time.sleep(self.config.effective_startup_delay)
            return True
        return False

    def generate_session_name(self) -> str:
        """Generate a unique tmux session name with timestamp + random suffix."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        suffix = os.urandom(3).hex()
        return f"{self.config.session_prefix}-{ts}-{suffix}"

    def rollback_session(self, name: str) -> None:
        """Best-effort rollback for a failed or partially created session."""
        with self.lifecycle_lock:
            try:
                self._run_tmux(["kill-session", "-t", name], check=False)
            except Exception as exc:
                self.logger.warning("Failed to rollback session '%s': %s", name, exc)
            finally:
                self.sessions.remove(name)

    def create_session(self, session_name: str | None = None) -> SessionInfo:
        """Create a NEW tmux session, start the REPL agent, and register it."""
        with self.lifecycle_lock:
            name = session_name or self.generate_session_name()
            self.logger.info("Creating new tmux session '%s'", name)

            self._run_tmux(["new-session", "-d", "-s", name, "-n", self.config.window_name])
            target = self.resolve_target_for(name)
            info = self.sessions.register(name, target, status="creating")

            try:
                # Change into the working directory before launching the REPL.
                self.send_literal(f"cd {shlex.quote(self.config.workdir)}", target=target)
                time.sleep(0.3)
                self.send_literal(self.config.effective_repl_cmd, target=target)
                time.sleep(self.config.effective_startup_delay)

                # Auto-dismiss agent-specific startup prompts.
                self.dismiss_trust_prompt(target=target)
                self.dismiss_bypass_warning(target=target)
                self.sessions.set_status(name, "active")
                self.logger.info("Session '%s' created, REPL started", name)
                return info
            except Exception:
                self.sessions.set_status(name, "error")
                self.logger.exception("Failed to finish creating session '%s'", name)
                self.rollback_session(name)
                raise

    def wait_for_repl_ready(self, *, target: str, timeout: float = 30) -> bool:
        """Wait for the REPL to show the idle prompt (ready for input)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(1)
            capture_data = self.capture_pane(lines=20, target=target)
            content = capture_data.get("content", "")

            # Dismiss startup prompts if the agent profile declares them.
            if self.config.profile.has_trust_prompt and (
                "trust this folder" in content.lower() or "trust the contents" in content.lower()
            ):
                self.logger.info("wait_for_ready: dismissing trust prompt")
                self.send_special_key("enter", target=target)
                time.sleep(8)
                continue
            if self.config.profile.has_bypass_warning and "yes, i accept" in content.lower():
                self.logger.info("wait_for_ready: accepting bypass warning")
                self.send_special_key("down", target=target)
                time.sleep(0.3)
                self.send_special_key("enter", target=target)
                time.sleep(8)
                continue

            # Check for idle prompt using the agent profile pattern.
            if re.search(self.config.profile.idle_pattern, content, re.MULTILINE):
                time.sleep(2)
                capture2 = self.capture_pane(lines=5, target=target)
                if re.search(
                    self.config.profile.idle_pattern, capture2.get("content", ""), re.MULTILINE
                ):
                    self.logger.info("REPL ready (idle prompt detected)")
                    return True
        self.logger.warning("REPL did not become ready within %.0fs", timeout)
        return False

    def kill_session(self, name: str) -> bool:
        """Kill a specific tmux session and remove it from tracking."""
        with self.lifecycle_lock:
            if self.session_exists(name):
                self._run_tmux(["kill-session", "-t", name])
                self.logger.info("Killed tmux session '%s'", name)
            self.sessions.remove(name)
            return True

    def cleanup_old_sessions(self, keep: str = "") -> list[str]:
        """Kill all tracked sessions that are idle, except the active or preserved one."""
        with self.lifecycle_lock:
            killed: list[str] = []
            active_info = self.sessions.get_active()
            active_name = active_info.name if active_info else ""

            for info in self.sessions.list_sessions():
                # Never kill the currently active session or the one we want to keep.
                if info.name == active_name or info.name == keep:
                    continue
                # Remove sessions that disappeared from tmux.
                if not self.session_exists(info.name):
                    self.sessions.remove(info.name)
                    killed.append(info.name)
                    continue
                # If we cannot inspect a session, treat it as stale and reclaim it.
                try:
                    idle = self.is_idle(target=info.target)
                except Exception:
                    idle = True
                if idle:
                    self.kill_session(info.name)
                    killed.append(info.name)

            return killed
