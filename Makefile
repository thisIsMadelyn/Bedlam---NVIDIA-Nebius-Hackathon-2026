.PHONY: smoke lint fmt up down run headless record test prove-routing

smoke:
	python scripts/smoke_nebius.py
	python scripts/smoke_tavily.py

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff format .

# Phase 1 onwards — these fail until the target stack exists.
# Seeding is the boilerplate's own idempotent script: tables, the free tier,
# and the admin the app probe signs in as.
up:
	docker compose up -d --wait
	docker compose exec -T -w /app api python scripts/setup_initial_data.py

down:
	docker compose down -v

# SEED=1729 picks the root seed; without it, BEDLAM_SEED or the default.
# SCRIPTED=1 applies the prepared diffs in demo/patches/ instead of your edits.
run:
	python -m bedlam.tui $(if $(SEED),--seed $(SEED)) $(if $(SCRIPTED),--scripted)

headless:
	python -m bedlam.loop --headless

# Phase 2 gate: one live run, recorded for the replay determinism test.
record:
	python -m bedlam.loop --headless --record tests/fixtures/replay-seed1729.json --seed 1729

# Phase 2 gate: live Tavily output changes which specialist is selected.
prove-routing:
	python scripts/prove_routing.py

test:
	python -m pytest
