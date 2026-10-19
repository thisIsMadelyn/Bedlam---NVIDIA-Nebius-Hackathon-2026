.PHONY: smoke lint fmt up down run headless test prove-routing

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

# Phase 2 gate: live Tavily output changes which specialist is selected.
prove-routing:
	python scripts/prove_routing.py

test:
	python -m pytest
