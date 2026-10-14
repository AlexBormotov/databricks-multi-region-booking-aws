# One contract for contributors and CI. On the host every goal re-runs itself inside the dev
# container; inside the container (IN_DEV_CONTAINER is set by the image) the real recipes run.

GOALS := $(or $(MAKECMDGOALS),help)

ifndef IN_DEV_CONTAINER

# Only test-integration needs the emulators; other goals skip starting them.
DEPS := $(if $(filter test-integration,$(GOALS)),,--no-deps)

.PHONY: $(GOALS)
$(firstword $(GOALS)):
	docker compose run --rm $(DEPS) dev make $(GOALS) $(MAKEOVERRIDES)

$(wordlist 2,$(words $(GOALS)),$(GOALS)):
	@:

else

SCALE ?= small

.PHONY: help sync lint test test-integration security plan up demo down cost-report

help:
	@echo "targets: lint test test-integration security plan up demo down cost-report"

sync:
	uv sync --frozen

lint: sync
	ruff check .
	ruff format --check .

test: sync
	pytest tests/unit

test-integration: sync
	pytest tests/integration

security: sync
	gitleaks git --redact --no-banner .
	trivy fs --no-progress --scanners vuln,misconfig,secret --exit-code 1 --severity HIGH,CRITICAL \
		--skip-dirs ai-factory-kit --skip-dirs .venv .

plan:
	@echo "plan: implemented in slice 0, step 4" && exit 1

up demo down cost-report:
	@echo "$@: implemented in the cloud slice" && exit 1

endif
