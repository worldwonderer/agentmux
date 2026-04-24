.PHONY: install test lint format type-check clean coverage serve

install:
	pip install -e ".[dev]"

test:
	pytest -m "not integration"

test-all:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests

format-check:
	ruff format --check src tests

type-check:
	mypy src

coverage:
	pytest --cov=agentmux --cov-report=term-missing -m "not integration"

clean:
	rm -rf build dist *.egg-info .pytest_cache .coverage .mypy_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

serve:
	python -m agentmux serve
