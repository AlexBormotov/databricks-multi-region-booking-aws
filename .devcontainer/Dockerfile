# Dev and CI image: every tool the Make targets call, at pinned versions.
FROM python:3.13.16-slim-trixie

ARG TERRAFORM_VERSION=1.16.5
ARG TERRAGRUNT_VERSION=1.1.6
ARG DATABRICKS_CLI_VERSION=1.20.0
ARG K6_VERSION=2.3.0
ARG TFLINT_VERSION=0.64.0
ARG TRIVY_VERSION=0.75.0
ARG GITLEAKS_VERSION=8.30.1
ARG AWSCLI_VERSION=2.38.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git make unzip \
    openjdk-21-jre-headless \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/tools
RUN set -eux; \
    curl -fsSLo tf.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"; \
    unzip -q tf.zip terraform -d /usr/local/bin; \
    curl -fsSLo /usr/local/bin/terragrunt "https://github.com/gruntwork-io/terragrunt/releases/download/v${TERRAGRUNT_VERSION}/terragrunt_linux_amd64"; \
    chmod +x /usr/local/bin/terragrunt; \
    curl -fsSLo dbx.zip "https://github.com/databricks/cli/releases/download/v${DATABRICKS_CLI_VERSION}/databricks_cli_${DATABRICKS_CLI_VERSION}_linux_amd64.zip"; \
    unzip -q dbx.zip databricks -d /usr/local/bin; \
    curl -fsSL "https://github.com/grafana/k6/releases/download/v${K6_VERSION}/k6-v${K6_VERSION}-linux-amd64.tar.gz" \
      | tar -xz --strip-components=1 -C /usr/local/bin "k6-v${K6_VERSION}-linux-amd64/k6"; \
    curl -fsSLo tflint.zip "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_amd64.zip"; \
    unzip -q tflint.zip tflint -d /usr/local/bin; \
    curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
      | tar -xz -C /usr/local/bin trivy; \
    curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
      | tar -xz -C /usr/local/bin gitleaks; \
    curl -fsSLo awscli.zip "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip"; \
    unzip -q awscli.zip; ./aws/install; \
    rm -rf /tmp/tools

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    IN_DEV_CONTAINER=1

WORKDIR /workspace
