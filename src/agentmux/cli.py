"""CLI entry point for agentmux."""

import argparse
import json
import sys

from agentmux.config import BridgeConfig, setup_logging
from agentmux.server import get_bridge_status, serve
from agentmux.tmux import TmuxController


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(description="AgentMux — HTTP bridge for managing AI agent REPL sessions via tmux")
    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("serve", help="Run the local HTTP bridge server")
    subparsers.add_parser("status", help="Print bridge status as JSON")
    subparsers.add_parser("cleanup", help="Kill all idle old sessions")

    send_parser = subparsers.add_parser("send", help="Send a text prompt into active session")
    send_parser.add_argument("text", help="Text to send")

    key_parser = subparsers.add_parser("key", help="Send a special key into active session")
    key_parser.add_argument("key_name", help="Key name, e.g. enter/up/down")
    key_parser.add_argument("--repeat", type=int, default=1, help="Repeat count")

    capture_parser = subparsers.add_parser("capture", help="Capture recent tmux pane output")
    capture_parser.add_argument("--lines", type=int, default=60, help="Number of lines to capture")

    return parser


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "serve"

    config = BridgeConfig()
    logger = setup_logging(config)
    controller = TmuxController(config, logger)

    if command == "serve":
        serve(config, controller, logger)
        return

    if command == "status":
        print(json.dumps(get_bridge_status(controller), ensure_ascii=False, indent=2))
        return

    if command == "cleanup":
        killed = controller.cleanup_old_sessions()
        print(json.dumps({"ok": True, "killed": killed}, ensure_ascii=False))
        return

    if command == "send":
        info = controller.sessions.get_active()
        if not info:
            print(json.dumps({"error": "no active session"}, ensure_ascii=False))
            sys.exit(1)
        used_target = controller.send_literal(args.text, target=info.target)
        print(json.dumps({"ok": True, "target": used_target}, ensure_ascii=False))
        return

    if command == "key":
        info = controller.sessions.get_active()
        if not info:
            print(json.dumps({"error": "no active session"}, ensure_ascii=False))
            sys.exit(1)
        used_target = controller.send_special_key(
            args.key_name, repeat=args.repeat, target=info.target
        )
        print(json.dumps({"ok": True, "target": used_target}, ensure_ascii=False))
        return

    if command == "capture":
        info = controller.sessions.get_active()
        if not info:
            print(json.dumps({"error": "no active session"}, ensure_ascii=False))
            sys.exit(1)
        print(
            json.dumps(
                controller.capture_pane(lines=args.lines, target=info.target),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    parser.error(f"Unsupported command: {command}")
