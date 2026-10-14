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
	terraform fmt -check -recursive infra
	terragrunt hcl format --check --working-dir infra/live
	tflint --recursive --chdir infra

test: sync
	pytest tests/unit

test-integration: sync
	pytest tests/integration

security: sync
	gitleaks git --redact --no-banner .
	trivy fs --no-progress --scanners vuln,misconfig,secret --exit-code 1 --severity HIGH,CRITICAL \
		--skip-dirs ai-factory-kit --skip-dirs .venv .

# Read-only: no state lock is taken, so the plan role needs no write access.
plan:
	cd infra/live/demo-prod && terragrunt run --all --non-interactive --provider-cache \
		-- plan -lock=false -input=false

up demo down cost-report:
	@echo "$@: implemented in the cloud slice" && exit 1

endif
