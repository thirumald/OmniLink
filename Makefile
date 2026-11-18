PY ?= python3
export PYTHONPATH := libs/omnilink_contracts:libs/omnilink_sdk:services:connectors:edge:workflow/temporal:assistant:.

.PHONY: bringup onboard-dry-run test test-node test-console contracts contracts-check devstack console-build lint compose-check all

test:
	$(PY) -m pytest -q tests

test-node:
	cd workflow/node-red/node-red-contrib-omnilink && node --test test/*.test.js

test-console:
	cd frontend/console && npx ng test --watch=false

contracts:
	$(PY) -m omnilink_contracts.export_schemas --out contracts/schemas

contracts-check:
	$(PY) -m omnilink_contracts.export_schemas --out contracts/schemas --check

console-build:
	cd frontend/console && npm ci && npx ng build

devstack:
	OMNILINK_AUTH_MODE=dev $(PY) tools/devstack.py

lint:
	ruff check .

compose-check:
	cd deploy/compose && cp -n .env.example .env; docker compose --profile all config -q

all: lint contracts-check test test-node test-console compose-check

bringup:
	scripts/bringup.sh all

onboard-dry-run:
	$(PY) tools/onboard.py $(SITE) --dry-run
