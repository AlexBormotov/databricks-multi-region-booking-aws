# One contract for contributors and CI. On the host every goal re-runs itself inside the dev
# container; inside the container (IN_DEV_CONTAINER is set by the image) the real recipes run.

GOALS := $(or $(MAKECMDGOALS),help)

ifndef IN_DEV_CONTAINER

# Only test-integration and k6-local need the emulators; other goals skip starting them.
DEPS := $(if $(filter test-integration k6-local,$(GOALS)),,--no-deps)

.PHONY: $(GOALS)
$(firstword $(GOALS)):
	docker compose run --rm $(DEPS) dev make $(GOALS) $(MAKEOVERRIDES)

$(wordlist 2,$(words $(GOALS)),$(GOALS)):
	@:

else

SCALE ?= small
SEED ?= 7
# Kept by `make down` (plan D11): free while idle, and the MRSC table may refuse deletion for 24 h.
PERSISTENT := --filter '!./us-east-1/landing' --filter '!./us-east-1/mrsc'

.PHONY: help sync lint test test-integration security package plan plan-asl up demo down reap \
	cost-report k6-local

help:
	@echo "targets: lint test test-integration security plan up demo down reap cost-report k6-local"

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

# The expiry is written first, so the reaper also cleans up after an `up` that fails half-way.
up: sync package
	python -m ops.session expiry-set
	cd infra/live/demo-prod && terragrunt run --all --non-interactive --provider-cache \
		-- apply -input=false -auto-approve
	python -m ops.session prepare --seed $(SEED) --scale $(SCALE)

# Destroying the functions reads the zip's hash, so `down` builds it too.
down: sync package
	python -m ops.session empty-landing
	cd infra/live/demo-prod && terragrunt run --all --non-interactive --provider-cache $(PERSISTENT) \
		-- destroy -input=false -auto-approve
	python -m ops.session expiry-clear

reap: sync
	if python -m ops.session due; then $(MAKE) down; else echo "no expired session"; fi

# The contention scenario against the API handler on PostgreSQL, before any cloud spend.
K6_ATTEMPTS ?= 1000
k6-local: sync
	mkdir -p artifacts
	rm -f /tmp/room.json
	python load/local_api.py --port 8080 --room-file /tmp/room.json & server=$$!; \
	for i in $$(seq 60); do [ -s /tmp/room.json ] && break; sleep 1; done; \
	k6 run --quiet -e API_URLS=http://127.0.0.1:8080 -e ATTEMPTS=$(K6_ATTEMPTS) \
		-e START_AT=$$(python -c "import time;print(int(time.time()*1000)+5000)") \
		-e HOTEL_ID=$$(python -c "import json;print(json.load(open('/tmp/room.json'))['hotel_id'])") \
		-e ROOM_ID=$$(python -c "import json;print(json.load(open('/tmp/room.json'))['room_id'])") \
		-e SUMMARY=artifacts/k6-local.json load/contention.js; \
	status=$$?; kill $$server; [ $$status -eq 0 ] && \
		python -m ops.demo check-k6 --attempts $(K6_ATTEMPTS) artifacts/k6-local.json

demo cost-report:
	@echo "$@: implemented in slice C2" && exit 1

endif
