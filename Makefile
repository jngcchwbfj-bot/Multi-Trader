.PHONY: help sync install test lint format clean healthcheck smoke-test run-session

help:
	@echo "Financial Powerhouse - Available targets:"
	@echo "  sync           - Sync dependencies with uv"
	@echo "  install        - Alias for sync"
	@echo "  test           - Run all tests"
	@echo "  test-unit      - Run unit tests only"
	@echo "  test-cov       - Run tests with coverage report"
	@echo "  lint           - Run linters (ruff, mypy)"
	@echo "  format         - Format code with black"
	@echo "  clean          - Remove build artifacts and cache"
	@echo "  healthcheck    - Run health check command"
	@echo "  smoke-test     - Run smoke tests"
	@echo "  run-session    - Run a mock premarket session"

sync:
	uv sync

install: sync

test:
	uv run pytest

test-unit:
	uv run pytest -m unit

test-cov:
	uv run pytest --cov=powerhouse --cov-report=html --cov-report=term

lint:
	uv run ruff check src tests
	uv run mypy src

format:
	uv run black src tests

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov

healthcheck:
	uv run python -m powerhouse.cli healthcheck

smoke-test:
	uv run python -m powerhouse.cli smoke-test

run-session:
	uv run python -m powerhouse.cli run-session --mode backtest --phase premarket
