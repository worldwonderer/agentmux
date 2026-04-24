# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-24

### Added

- Modular Python package structure under `src/agentmux/`.
- `TmuxController` class to encapsulate all tmux operations.
- `SessionManager` with thread-safe session tracking.
- Comprehensive test suite with pytest, targeting 80%+ coverage.
- GitHub Actions CI for lint, type-check, and test on Python 3.10–3.13.
- `ruff` for linting and formatting.
- `mypy` for static type checking.
- `pre-commit` hooks configuration.
- Makefile for common development tasks.
- `pyproject.toml` with modern Python packaging metadata.

### Changed

- Reorganized monolithic script into focused modules:
  - `config.py` – configuration and logging
  - `session.py` – session state management
  - `tmux.py` – tmux subprocess operations
  - `server.py` – HTTP API handler
  - `cli.py` – command-line interface
- `BridgeHandler` now receives dependencies via constructor injection for testability.
- `BridgeConfig` uses `field(default_factory=...)` for proper dataclass defaults.

### Removed

- Single-file `launchagent_bridge.py` script (superseded by package).
