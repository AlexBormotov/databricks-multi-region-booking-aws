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

.PHONY: help sync lint test test-integration security package plan plan-asl up demo down cost-report

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
	pytest tests/unit tests/lakehouse

test-integration: sync
	pytest tests/integration

security: sync
	gitleaks git --redact --no-banner .
	trivy fs --no-progress --scanners vuln,misconfig,secret --exit-code 1 --severity HIGH,CRITICAL \
		--skip-dirs ai-factory-kit --skip-dirs .venv .

# Read-only: no state lock is taken, so the plan role needs no write access.
plan: plan-asl package
	cd infra/live/demo-prod && terragrunt run --all --non-interactive --provider-cache \
		-- plan -lock=false -input=false

# One zip for every function: the booking package plus its Linux wheels for Python 3.13.
package:
	rm -rf build && mkdir -p build/pkg
	uv export --frozen --no-dev --no-hashes --no-emit-project -o build/requirements.txt
	uv pip install --quiet -r build/requirements.txt --target build/pkg \
		--python-platform x86_64-manylinux2014 --python-version 3.13 --only-binary :all:
	cp -r src/booking build/pkg/
	cd build/pkg && python -m zipfile -c ../lambda.zip *

# The saga's state machine, with its template placeholders filled by sample values, must pass
# Step Functions' own validator (a free API call).
ASL := infra/modules/saga/definition.asl.json
plan-asl:
	sed -e 's/$${payment_timeout_s}/60/' \
		-e 's/$${[a-z_]*_function_arn}/arn:aws:lambda:us-east-1:123456789012:function:sample/' \
		$(ASL) > /tmp/definition.asl.json
	aws stepfunctions validate-state-machine-definition --region us-east-1 \
		--definition file:///tmp/definition.asl.json --output json > /tmp/asl-result.json
	cat /tmp/asl-result.json
	grep -q '"result": "OK"' /tmp/asl-result.json

up demo down cost-report:
	@echo "$@: implemented in the cloud slice" && exit 1

endif
