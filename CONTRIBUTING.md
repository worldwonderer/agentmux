# Contributing to AgentMux

Thanks for your interest in improving AgentMux!

## Quick Start

```bash
git clone https://github.com/example/agentmux.git
cd agentmux
pip install -e ".[dev]"
pre-commit install
```

## Development Workflow

1. **Create a branch** — `git checkout -b feature/your-feature`
2. **Make changes** — Follow existing code style (ruff + mypy)
3. **Run checks** — `make lint && make type-check && make test`
4. **Commit** — Pre-commit hooks will auto-format and lint
5. **Open a PR** — Describe the change and link any related issues

## Code Style

- **Formatter / Linter**: `ruff`
- **Type checker**: `mypy --strict`
- **Tests**: `pytest` with 80%+ coverage target
- **Docstrings**: Google style

## Reporting Issues

Please include:
- Python version and OS
- `tmux` version (`tmux -V`)
- Steps to reproduce
- Relevant logs (redact tokens)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
