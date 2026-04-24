"""Tests for agentmux.server."""

import json
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest

from agentmux.config import BridgeConfig
from agentmux.server import BridgeHandler, check_auth, get_bridge_status
from agentmux.session import SessionInfo


def _start_server(controller: MagicMock, config: BridgeConfig, logger: MagicMock):
    """Start a test HTTP server and return (server, port)."""
    from functools import partial
    from http.server import ThreadingHTTPServer

    handler = partial(
        BridgeHandler,
        controller=controller,
        config=config,
        logger=logger,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # type: ignore[arg-type]
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestCheckAuth:
    """Tests for check_auth."""

    def test_no_token_required(self) -> None:
        """Test access allowed when no token configured."""
        assert check_auth({}, "") is True
        assert check_auth({"Authorization": "Bearer x"}, "") is True

    def test_bearer_token(self) -> None:
        """Test valid Bearer token."""
        assert check_auth({"Authorization": "Bearer secret"}, "secret") is True

    def test_x_bridge_token(self) -> None:
        """Test valid X-Bridge-Token header."""
        assert check_auth({"X-Bridge-Token": "secret"}, "secret") is True

    def test_invalid_token(self) -> None:
        """Test invalid token is rejected."""
        assert check_auth({"Authorization": "Bearer wrong"}, "secret") is False


class TestGetBridgeStatus:
    """Tests for get_bridge_status."""

    def test_empty(self) -> None:
        """Test status with no sessions."""
        controller = MagicMock()
        controller.sessions.get_active.return_value = None
        controller.sessions.list_sessions.return_value = []
        status = get_bridge_status(controller)
        assert status["ok"] is True
        assert status["active_session"] is None
        assert status["total_sessions"] == 0

    def test_with_sessions(self) -> None:
        """Test status with active and inactive sessions."""
        controller = MagicMock()
        controller.sessions.get_active.return_value = SessionInfo(name="active", target="a:1.0")
        controller.sessions.list_sessions.return_value = [
            SessionInfo(name="active", target="a:1.0"),
            SessionInfo(name="old", target="o:1.0"),
        ]
        controller.session_exists.return_value = True
        controller.is_idle.return_value = True
        controller.get_ctx_percent.return_value = 10

        status = get_bridge_status(controller)
        assert status["total_sessions"] == 2
        assert status["active_session"] == "active"
        assert status["sessions"][0]["idle"] is True
        assert status["sessions"][0]["ctx_percent"] == 10
        assert isinstance(status["sessions"][0]["created_at"], str)

    def test_dead_session(self) -> None:
        """Test status marks dead sessions."""
        controller = MagicMock()
        controller.sessions.get_active.return_value = None
        controller.sessions.list_sessions.return_value = [
            SessionInfo(name="dead", target="d:1.0"),
        ]
        controller.session_exists.return_value = False

        status = get_bridge_status(controller)
        assert status["sessions"][0].get("tmux_exists") is False


class TestServerIntegration:
    """Integration tests using a real ThreadingHTTPServer."""

    @pytest.fixture
    def server_port(
        self,
        bridge_config: BridgeConfig,
        mock_logger: MagicMock,
    ):
        """Yield a running test server and its port."""
        controller = MagicMock()
        controller.sessions.get_active.return_value = None
        controller.sessions.list_sessions.return_value = []
        controller.sessions.active = ""
        controller.session_exists.return_value = False
        controller.lifecycle_lock = threading.RLock()

        server, port = _start_server(controller, bridge_config, mock_logger)
        try:
            yield port, controller
        finally:
            server.shutdown()

    def _request(
        self,
        port: int,
        path: str,
        method: str = "GET",
        data: dict | None = None,
        token: str = "test-token",
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        """Helper to make HTTP requests."""
        if data is not None and raw_body is not None:
            raise ValueError("data and raw_body are mutually exclusive")

        url = f"http://127.0.0.1:{port}{path}"
        request_headers = {
            "Authorization": f"Bearer {token}",
        }
        if headers:
            request_headers.update(headers)

        body = raw_body
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif raw_body is not None and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /health returns status."""
        port, controller = server_port
        status, data = self._request(port, "/health")
        assert status == HTTPStatus.OK
        assert data["ok"] is True
        controller.sessions.list_sessions.assert_called()

    def test_sessions(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /sessions returns session list."""
        port, controller = server_port
        session = SessionInfo(name="s", target="s:1.0")
        controller.sessions.list_sessions.return_value = [session]
        status, data = self._request(port, "/sessions")
        assert status == HTTPStatus.OK
        assert data["sessions"][0]["name"] == "s"
        assert isinstance(data["sessions"][0]["created_at"], str)
        assert "active" in data

    def test_capture_no_active(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /capture 404 when no active session."""
        port, _ = server_port
        status, data = self._request(port, "/capture")
        assert status == HTTPStatus.NOT_FOUND
        assert "error" in data

    def test_capture_invalid_lines(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /capture rejects invalid lines parameter."""
        port, _ = server_port
        status, data = self._request(port, "/capture?lines=abc")
        assert status == HTTPStatus.BAD_REQUEST
        assert data["error"] == "lines must be an integer"

    def test_idle_no_active(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /idle 404 when no active session."""
        port, _ = server_port
        status, _ = self._request(port, "/idle")
        assert status == HTTPStatus.NOT_FOUND

    def test_send_no_text(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /send rejects empty text."""
        port, _ = server_port
        status, data = self._request(port, "/send", method="POST", data={})
        assert status == HTTPStatus.BAD_REQUEST
        assert data["error"] == "text is required"

    def test_send_no_active(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /send 404 when no active session."""
        port, _ = server_port
        status, _ = self._request(port, "/send", method="POST", data={"text": "hello"})
        assert status == HTTPStatus.NOT_FOUND

    def test_send_rejects_unmanaged_target(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /send surfaces unmanaged-target validation as 400."""
        port, controller = server_port
        controller.send_literal.side_effect = ValueError("target is not managed by agentmux")
        status, data = self._request(
            port,
            "/send",
            method="POST",
            data={"text": "hello", "target": "other:1.0"},
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert data["error"] == "target is not managed by agentmux"

    def test_run_no_text(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /run rejects empty text."""
        port, _ = server_port
        status, _ = self._request(port, "/run", method="POST", data={})
        assert status == HTTPStatus.BAD_REQUEST

    def test_run_success(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /run creates a session and sends text."""
        port, controller = server_port
        controller.sessions.get_active.return_value = None
        controller.session_exists.return_value = False
        controller.sessions.session_count.return_value = 0
        new_info = MagicMock()
        new_info.name = "new"
        new_info.target = "new:1.0"
        controller.create_session.return_value = new_info
        controller.wait_for_repl_ready.return_value = True
        controller.send_literal.return_value = "new:1.0"
        status, data = self._request(port, "/run", method="POST", data={"text": "hello"})
        assert status == HTTPStatus.OK, data
        assert data["ok"] is True
        assert data["action"] == "run"
        controller.create_session.assert_called_once()

    def test_run_busy(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /run returns 409 when Claude is busy."""
        port, controller = server_port
        active = MagicMock()
        active.name = "busy"
        active.target = "b:1.0"
        controller.sessions.get_active.return_value = active
        controller.session_exists.return_value = True
        controller.is_idle.return_value = False
        status, data = self._request(port, "/run", method="POST", data={"text": "hello"})
        assert status == HTTPStatus.CONFLICT
        assert data["busy"] is True

    def test_run_ready_timeout_rolls_back(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /run rolls back when a new session never becomes ready."""
        port, controller = server_port
        controller.sessions.get_active.return_value = None
        controller.session_exists.return_value = False
        controller.sessions.session_count.return_value = 0
        new_info = MagicMock()
        new_info.name = "new"
        new_info.target = "new:1.0"
        controller.create_session.return_value = new_info
        controller.wait_for_repl_ready.return_value = False

        status, data = self._request(port, "/run", method="POST", data={"text": "hello"})
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
        assert data["error"] == "new session did not become ready"
        controller.rollback_session.assert_called_once_with("new")

    def test_run_limit_reached_after_cleanup(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /run fails when cleanup cannot free session capacity."""
        port, controller = server_port
        controller.sessions.get_active.return_value = None
        controller.sessions.session_count.side_effect = [10, 10]
        controller.cleanup_old_sessions.return_value = []

        status, data = self._request(port, "/run", method="POST", data={"text": "hello"})
        assert status == HTTPStatus.CONFLICT
        assert data["error"] == "session limit (10) reached"

    def test_key_no_key(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /key rejects empty key."""
        port, _ = server_port
        status, _ = self._request(port, "/key", method="POST", data={})
        assert status == HTTPStatus.BAD_REQUEST

    def test_key_invalid_repeat(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /key rejects non-integer repeat values."""
        port, controller = server_port
        active = MagicMock()
        active.name = "s"
        active.target = "s:1.0"
        controller.sessions.get_active.return_value = active
        status, data = self._request(
            port,
            "/key",
            method="POST",
            data={"key": "enter", "repeat": "abc"},
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert data["error"] == "repeat must be an integer"

    def test_kill_no_session(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /kill rejects missing session name."""
        port, _ = server_port
        status, _ = self._request(port, "/kill", method="POST", data={})
        assert status == HTTPStatus.BAD_REQUEST

    def test_not_found(self, server_port: tuple[int, MagicMock]) -> None:
        """Test 404 for unknown paths."""
        port, _ = server_port
        status, _ = self._request(port, "/unknown")
        assert status == HTTPStatus.NOT_FOUND

    def test_auth_forbidden(self, server_port: tuple[int, MagicMock]) -> None:
        """Test 403 with bad token."""
        port, _ = server_port
        status, data = self._request(port, "/health", token="bad-token")
        assert status == HTTPStatus.FORBIDDEN
        assert data["error"] == "forbidden"

    def test_send_success(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /send with valid input."""
        port, controller = server_port
        active = MagicMock()
        active.name = "s"
        active.target = "s:1.0"
        controller.sessions.get_active.return_value = active
        controller.send_literal.return_value = "s:1.0"
        status, data = self._request(port, "/send", method="POST", data={"text": "hello"})
        assert status == HTTPStatus.OK
        assert data["ok"] is True
        assert data["action"] == "send"

    def test_key_success(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /key with valid input."""
        port, controller = server_port
        active = MagicMock()
        active.name = "s"
        active.target = "s:1.0"
        controller.sessions.get_active.return_value = active
        controller.send_special_key.return_value = "s:1.0"
        status, data = self._request(port, "/key", method="POST", data={"key": "enter"})
        assert status == HTTPStatus.OK
        assert data["ok"] is True
        assert data["action"] == "key"

    def test_restart_success(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /restart creates a ready replacement before killing the old session."""
        port, controller = server_port
        old = MagicMock()
        old.name = "old"
        old.target = "old:1.0"
        new = MagicMock()
        new.name = "new"
        new.target = "new:1.0"
        controller.sessions.get_active.return_value = old
        controller.create_session.return_value = new
        controller.wait_for_repl_ready.return_value = True
        status, data = self._request(port, "/restart", method="POST", data={})
        assert status == HTTPStatus.OK
        assert data["ok"] is True
        assert data["action"] == "restart"
        assert data["ready"] is True
        controller.kill_session.assert_called_once_with("old")

    def test_restart_ready_timeout_rolls_back(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /restart keeps the old session if replacement is not ready."""
        port, controller = server_port
        old = MagicMock()
        old.name = "old"
        old.target = "old:1.0"
        new = MagicMock()
        new.name = "new"
        new.target = "new:1.0"
        controller.sessions.get_active.return_value = old
        controller.create_session.return_value = new
        controller.wait_for_repl_ready.return_value = False
        status, data = self._request(port, "/restart", method="POST", data={})
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
        assert data["error"] == "replacement session did not become ready"
        controller.rollback_session.assert_called_once_with("new")
        controller.kill_session.assert_not_called()

    def test_cleanup_success(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /cleanup returns killed sessions."""
        port, controller = server_port
        controller.cleanup_old_sessions.return_value = ["sess1"]
        status, data = self._request(port, "/cleanup", method="POST", data={})
        assert status == HTTPStatus.OK
        assert data["killed"] == ["sess1"]

    def test_kill_success(self, server_port: tuple[int, MagicMock]) -> None:
        """Test POST /kill with a valid session name."""
        port, controller = server_port
        controller.sessions.get.return_value = MagicMock()
        status, data = self._request(port, "/kill", method="POST", data={"session": "s"})
        assert status == HTTPStatus.OK
        assert data["ok"] is True
        controller.kill_session.assert_called_once_with("s")

    def test_capture_with_target(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /capture with explicit target parameter."""
        port, controller = server_port
        controller.capture_pane.return_value = {
            "target": "sess:1.0",
            "lines": 20,
            "content": "output",
        }
        status, data = self._request(port, "/capture?target=sess:1.0&lines=20")
        assert status == HTTPStatus.OK
        assert data["content"] == "output"

    def test_capture_rejects_unmanaged_target(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /capture surfaces unmanaged-target validation as 400."""
        port, controller = server_port
        controller.capture_pane.side_effect = ValueError("target is not managed by agentmux")
        status, data = self._request(port, "/capture?target=other:1.0&lines=20")
        assert status == HTTPStatus.BAD_REQUEST
        assert data["error"] == "target is not managed by agentmux"

    def test_idle_with_active_session(self, server_port: tuple[int, MagicMock]) -> None:
        """Test GET /idle when an active session exists."""
        port, controller = server_port
        active = MagicMock()
        active.name = "s"
        active.target = "s:1.0"
        controller.sessions.get_active.return_value = active
        controller.is_idle.return_value = True
        controller.get_ctx_percent.return_value = 42
        status, data = self._request(port, "/idle")
        assert status == HTTPStatus.OK
        assert data["idle"] is True
        assert data["ctx_percent"] == 42
        assert data["session"] == "s"

    def test_invalid_json_returns_400(self, server_port: tuple[int, MagicMock]) -> None:
        """Test malformed JSON bodies return 400 instead of 500."""
        port, _ = server_port
        status, data = self._request(port, "/send", method="POST", raw_body=b"{")
        assert status == HTTPStatus.BAD_REQUEST
        assert data["error"] == "invalid JSON body"
