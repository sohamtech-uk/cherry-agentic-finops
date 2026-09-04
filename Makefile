.PHONY: install run test lint format docker adk ylookup-fixtures

install:
	python -m pip install -e ".[dev]"

run:
	uvicorn app.api:app --reload --port 8080

test:
	pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

docker:
	docker compose up --build

adk:
	adk web agents

ylookup-fixtures:
	python scripts/generate_ylookup_fixtures.py
