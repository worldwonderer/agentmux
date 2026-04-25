"""HTTP server for agentmux."""

import json
import logging
import signal
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agentmux.config import BridgeConfig
from agentmux.session import SessionInfo, SessionManager
from agentmux.tmux import TmuxController


class RequestError(Exception):
    """An HTTP-friendly request validation error."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def check_auth(headers: dict[str, str], token: str) -> bool:
    """Validate bearer token if configured."""
    if not token:
        return True
    auth_value = headers.get("Authorization", "")
    alt_value = headers.get("X-Bridge-Token", "")
    return auth_value == f"Bearer {token}" or alt_value == token


def _format_created_at(timestamp: float) -> str:
    """Format a session timestamp into local time for JSON responses."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _serialize_session(info: SessionInfo) -> dict[str, Any]:
    """Convert a SessionInfo object into a JSON-friendly dictionary."""
    return {
        "name": info.name,
        "status": info.status,
        "created_at": _format_created_at(info.created_at),
        "target": info.target,
    }


def get_bridge_status(controller: TmuxController) -> dict[str, Any]:
    """Return a JSON-serializable bridge status snapshot.

    Live idle/ctx checks are performed only for the active session to avoid
    spawning a tmux subprocess for every historical session.
    """
    active_info = controller.sessions.get_active()
    all_sessions = controller.sessions.list_sessions()

    result: dict[str, Any] = {
        "ok": True,
        "agent": controller.config.agent,
        "active_session": active_info.name if active_info else None,
        "total_sessions": len(all_sessions),
        "sessions": [],
    }

    for info in all_sessions:
        entry = _serialize_session(info)
        exists = controller.session_exists(info.name)
        if not exists:
            entry["tmux_exists"] = False
        elif active_info and info.name == active_info.name:
            # Live checks are expensive; run them only for the active session.
            try:
                entry["idle"] = controller.is_idle(target=info.target)
                entry["ctx_percent"] = controller.get_ctx_percent(target=info.target)
            except Exception:
                entry["idle"] = None
                entry["ctx_percent"] = None
        result["sessions"].append(entry)

    return result


class BridgeHandler(BaseHTTPRequestHandler):
    """Local HTTP API for agent REPL session bridging (multi-session)."""

    server_version = "AgentMux/0.1.0"

    def __init__(
        self,
        request: Any,
        client_address: Any,
        server: Any,
        *,
        controller: TmuxController,
        config: BridgeConfig,
        logger: logging.Logger,
    ) -> None:
        self.controller = controller
        self.config = config
        self.logger = logger
        super().__init__(request, client_address, server)

    def do_GET(self) -> None:  # noqa: N802
        try:
            if not check_auth(dict(self.headers), self.config.token):
                self.respond({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)
                return

            parsed = urlparse(self.path)

            if parsed.path == "/health":
                self.respond(get_bridge_status(self.controller))
                return

            if parsed.path == "/capture":
                params = parse_qs(parsed.query)
                lines = self._parse_int(params.get("lines", ["60"])[0], name="lines", minimum=1)
                target = self._resolve_requested_target(params.get("target", [""])[0] or None)
                self.respond(self.controller.capture_pane(lines=lines, target=target))
                return

            if parsed.path == "/idle":
                info = self.controller.sessions.get_active()
                if not info:
                    raise RequestError(HTTPStatus.NOT_FOUND, "no active session")
                idle = self.controller.is_idle(target=info.target)
                ctx = self.controller.get_ctx_percent(target=info.target)
                self.respond({"idle": idle, "ctx_percent": ctx, "session": info.name})
                return

            if parsed.path == "/sessions":
                self.respond(
                    {
                        "sessions": [
                            _serialize_session(session)
                            for session in self.controller.sessions.list_sessions()
                        ],
                        "active": self.controller.sessions.active,
                    }
                )
                return

            self.respond({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except RequestError as exc:
            self.respond({"error": exc.message}, status=exc.status)
        except ValueError as exc:
            self.respond({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.logger.error("GET %s error: %s", self.path, exc)
            self.respond(
                {"error": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not check_auth(dict(self.headers), self.config.token):
                self.respond({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)
                return

            parsed = urlparse(self.path)
            body = self._read_json_body()

            if parsed.path == "/send":
                text = self._require_text(body, field_name="text")
                target = self._resolve_requested_target(body.get("target"))
                used_target = self.controller.send_literal(text, target=target)
                self.respond({"ok": True, "action": "send", "target": used_target})
                return

            if parsed.path == "/run":
                text = self._require_text(body, field_name="text")
                with self.controller.lifecycle_lock:
                    active_info = self.controller.sessions.get_active()
                    if active_info and self.controller.session_exists(active_info.name):
                        try:
                            idle = self.controller.is_idle(target=active_info.target)
                        except Exception:
                            idle = True
                        if not idle:
                            self.respond(
                                {
                                    "ok": False,
                                    "busy": True,
                                    "error": "Agent is busy, previous task still running",
                                    "session": active_info.name,
                                },
                                status=HTTPStatus.CONFLICT,
                            )
                            return

                    if self.controller.sessions.session_count() >= SessionManager.MAX_SESSIONS:
                        self.logger.info(
                            "/run: session limit (%d) reached, auto-cleanup",
                            SessionManager.MAX_SESSIONS,
                        )
                        self.controller.cleanup_old_sessions()
                        if self.controller.sessions.session_count() >= SessionManager.MAX_SESSIONS:
                            raise RequestError(
                                HTTPStatus.CONFLICT,
                                f"session limit ({SessionManager.MAX_SESSIONS}) reached",
                            )

                    self.logger.info("/run: creating new session (fresh context)")
                    new_info = self.controller.create_session()
                    try:
                        ready = self.controller.wait_for_repl_ready(
                            target=new_info.target, timeout=30
                        )
                        if not ready:
                            self.controller.rollback_session(new_info.name)
                            raise RequestError(
                                HTTPStatus.SERVICE_UNAVAILABLE,
                                "new session did not become ready",
                            )

                        used_target = self.controller.send_literal(text, target=new_info.target)
                    except RequestError:
                        raise
                    except Exception:
                        self.logger.exception(
                            "/run: failed on session '%s', rolling back",
                            new_info.name,
                        )
                        self.controller.rollback_session(new_info.name)
                        raise

                self.logger.info("/run: message sent on new session '%s'", new_info.name)
                self.respond(
                    {
                        "ok": True,
                        "action": "run",
                        "session": new_info.name,
                        "target": used_target,
                    }
                )
                return

            if parsed.path == "/key":
                key_name = self._require_text(body, field_name="key")
                repeat = self._parse_int(body.get("repeat", 1), name="repeat", minimum=1)
                target = self._resolve_requested_target(body.get("target"))
                used_target = self.controller.send_special_key(
                    key_name,
                    repeat=repeat,
                    target=target,
                )
                self.respond(
                    {
                        "ok": True,
                        "action": "key",
                        "target": used_target,
                        "key": key_name,
                    }
                )
                return

            if parsed.path == "/restart":
                with self.controller.lifecycle_lock:
                    active_info = self.controller.sessions.get_active()
                    replacement = self.controller.create_session()
                    ready = self.controller.wait_for_repl_ready(
                        target=replacement.target, timeout=30
                    )
                    if not ready:
                        self.controller.rollback_session(replacement.name)
                        raise RequestError(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            "replacement session did not become ready",
                        )
                    if active_info:
                        self.controller.kill_session(active_info.name)

                self.respond(
                    {
                        "ok": True,
                        "action": "restart",
                        "session": replacement.name,
                        "target": replacement.target,
                        "ready": True,
                    }
                )
                return

            if parsed.path == "/cleanup":
                with self.controller.lifecycle_lock:
                    killed = self.controller.cleanup_old_sessions()
                self.respond({"ok": True, "action": "cleanup", "killed": killed})
                return

            if parsed.path == "/kill":
                name = self._require_text(body, field_name="session")
                with self.controller.lifecycle_lock:
                    if not self.controller.sessions.get(name):
                        raise RequestError(HTTPStatus.NOT_FOUND, f"session '{name}' not found")
                    self.controller.kill_session(name)
                self.respond({"ok": True, "action": "kill", "session": name})
                return

            self.respond({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except RequestError as exc:
            self.respond({"error": exc.message}, status=exc.status)
        except ValueError as exc:
            self.respond({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.logger.error("POST %s error: %s", self.path, exc)
            self.respond(
                {"error": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format_: str, *args: Any) -> None:
        """Send access logs to stderr for launchd log capture."""
        import sys

        sys.stderr.write("[bridge] " + (format_ % args) + "\n")

    def _parse_int(self, value: object, *, name: str, minimum: int | None = None) -> int:
        """Parse and validate an integer value from request input."""
        try:
            if isinstance(value, bool):
                raise TypeError
            parsed: int = int(str(value))
        except (TypeError, ValueError) as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, f"{name} must be an integer") from exc

        if minimum is not None and parsed < minimum:
            raise RequestError(HTTPStatus.BAD_REQUEST, f"{name} must be >= {minimum}")
        return parsed

    def _require_text(self, body: dict[str, Any], *, field_name: str) -> str:
        """Extract a required string field from a JSON body."""
        value = body.get(field_name, "")
        if not isinstance(value, str):
            raise RequestError(HTTPStatus.BAD_REQUEST, f"{field_name} must be a string")
        text = value.strip()
        if not text:
            raise RequestError(HTTPStatus.BAD_REQUEST, f"{field_name} is required")
        return text

    def _resolve_requested_target(self, raw_target: object) -> str | None:
        """Resolve an optional target, falling back to the active session."""
        if raw_target is None:
            info = self.controller.sessions.get_active()
            if not info:
                raise RequestError(HTTPStatus.NOT_FOUND, "no active session")
            return info.target

        if not isinstance(raw_target, str):
            raise RequestError(HTTPStatus.BAD_REQUEST, "target must be a string")

        target = raw_target.strip()
        if not target:
            info = self.controller.sessions.get_active()
            if not info:
                raise RequestError(HTTPStatus.NOT_FOUND, "no active session")
            return info.target
        return target

    def _read_json_body(self) -> dict[str, Any]:
        """Parse and return a JSON request body."""
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from exc

        if length < 0:
            raise RequestError(HTTPStatus.BAD_REQUEST, "invalid Content-Length")

        raw_bytes = self.rfile.read(length) if length else b"{}"
        try:
            raw_body = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "request body must be utf-8") from exc

        try:
            result = json.loads(raw_body or "{}")
        except json.JSONDecodeError as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "invalid JSON body") from exc

        if not isinstance(result, dict):
            raise RequestError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return result

    def respond(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        """Write a JSON response."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(
    config: BridgeConfig,
    controller: TmuxController,
    logger: logging.Logger,
) -> None:
    """Run the bridge HTTP server with graceful shutdown."""
    handler = partial(
        BridgeHandler,
        controller=controller,
        config=config,
        logger=logger,
    )
    server = ThreadingHTTPServer((config.host, config.port), handler)

    def _signal_handler(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s, shutting down gracefully...", signum)
        # server.shutdown() must be called from a non-main thread to avoid deadlock.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    msg = {
        "ok": True,
        "message": "bridge started (multi-session)",
        "host": config.host,
        "port": config.port,
    }
    print(json.dumps(msg, ensure_ascii=False))
    logger.info(
        "Bridge server started on %s:%s (multi-session mode)",
        config.host,
        config.port,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        logger.info("Server stopped")
