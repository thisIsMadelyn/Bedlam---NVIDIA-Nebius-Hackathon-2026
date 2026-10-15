.PHONY: smoke lint fmt up down run headless test

smoke:
	python scripts/smoke_nebius.py
	python scripts/smoke_tavily.py

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff format .

# Phase 1 onwards — these fail until the target stack exists.
up:
	docker compose up -d --wait

down:
	docker compose down -v

run:
	python -m bedlam.tui

headless:
	python -m bedlam.loop --headless

test:
	python -m pytest
