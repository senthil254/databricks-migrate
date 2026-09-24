# Google Cloud DevOps Engineer — Interview Q&A

Bullet-style answers with copy-ready code for the Custom Application Architect / Google Cloud Engineer (CL9) role.

> **How to use this guide**
> - Each question has short bullet answers you can say out loud.
> - Code blocks are complete and formatted — use Copy to paste them into a lab.
> - Placeholder values: project `acme-app-prod`, region `europe-west2`, org folder `folders/445566778899`.
> - Focus areas follow the job description: Terraform modules, Azure DevOps, multi-cloud, AI integration, SDLC.

## 1. Terraform Foundations on GCP

### Q1. How do you bootstrap Terraform state for a new GCP organisation?

- State needs a bucket, but the bucket must exist before Terraform can use it — a chicken-and-egg problem.
- Create a small **seed project** with local state first.
- The seed creates the state bucket, the KMS key and the pipeline service account.
- Then migrate the seed's own state into the new bucket with `terraform init -migrate-state`.
- Lock the bucket down: versioning, uniform access, no public access, only the pipeline SA can write.

```hcl
resource "google_storage_bucket" "tfstate" {
  project                     = var.seed_project_id
  name                        = "acme-tfstate-${var.env}"
  location                    = "EU"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      num_newer_versions = 20
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_storage_bucket_iam_member" "pipeline_rw" {
  bucket = google_storage_bucket.tfstate.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}
```

```bash
# After the bucket exists, move the seed's local state into it
terraform init -migrate-state \
  -backend-config="bucket=acme-tfstate-prod" \
  -backend-config="prefix=seed"
```

### Q2. How do you apply common labels to every resource without repeating yourself?

- Build labels once in `locals` and `merge()` them with resource-specific labels.
- Pass the merged map into every module.
- Validate label keys and values — GCP allows lowercase letters, digits, `_` and `-` only.
- For provider-wide defaults use `default_labels` on the Google provider (v5+).

```hcl
locals {
  common_labels = {
    env         = var.env
    owner       = "platform-team"
    cost-center = "cc-1042"
    managed-by  = "terraform"
  }
}

provider "google" {
  project        = var.project_id
  region         = var.region
  default_labels = local.common_labels
}

resource "google_compute_instance" "app" {
  name         = "app-01"
  machine_type = "e2-medium"
  zone         = "${var.region}-a"

  labels = merge(local.common_labels, {
    app  = "orders"
    tier = "backend"
  })

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    subnetwork = var.subnet_self_link
  }
}
```

### Q3. How do you create many subnets from one variable using complex objects?

- Model the input as a `map(object(...))` — the map key becomes the stable resource address.
- Use `optional()` attributes with defaults (Terraform 1.3+).
- Use `for_each` on the map and nested `dynamic` blocks for secondary ranges.

```hcl
variable "subnets" {
  type = map(object({
    region                = string
    cidr                  = string
    private_google_access = optional(bool, true)
    secondary_ranges      = optional(map(string), {})
  }))
}

resource "google_compute_subnetwork" "this" {
  for_each = var.subnets

  name                     = each.key
  region                   = each.value.region
  ip_cidr_range            = each.value.cidr
  network                  = google_compute_network.vpc.id
  private_ip_google_access = each.value.private_google_access

  dynamic "secondary_ip_range" {
    for_each = each.value.secondary_ranges

    content {
      range_name    = secondary_ip_range.key
      ip_cidr_range = secondary_ip_range.value
    }
  }

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
  }
}
```

```hcl
# terraform.tfvars
subnets = {
  "snet-app-euw2" = {
    region = "europe-west2"
    cidr   = "10.10.0.0/20"
    secondary_ranges = {
      pods     = "10.20.0.0/16"
      services = "10.30.0.0/20"
    }
  }
  "snet-data-euw2" = {
    region = "europe-west2"
    cidr   = "10.10.16.0/20"
  }
}
```

### Q4. A resource keeps showing changes in every plan. How do you handle it?

- Find the attribute: run `terraform plan` and read which field flips.
- Common causes: labels added by another tool, autoscaler-managed node counts, API-normalised values.
- If another system legitimately owns the field, use `lifecycle { ignore_changes }`.
- If it is a real drift, fix the source — don't hide it.
- Never use `ignore_changes = all` on security-relevant resources.

```hcl
resource "google_container_node_pool" "default" {
  name       = "default-pool"
  cluster    = google_container_cluster.gke.id
  node_count = 3

  autoscaling {
    min_node_count = 3
    max_node_count = 10
  }

  lifecycle {
    ignore_changes = [
      node_count,                     # managed by the cluster autoscaler
      node_config[0].resource_labels, # added by GKE
    ]
  }
}
```

### Q5. How do you make a module safe to call with or without an optional feature?

- Use a boolean flag plus `count = var.enabled ? 1 : 0`.
- Return outputs with `one()` so callers get `null` when the feature is off.
- Keep the module interface small: required inputs first, sensible defaults for the rest.

```hcl
variable "enable_private_endpoint" {
  type    = bool
  default = false
}

resource "google_compute_global_address" "psa" {
  count = var.enable_private_endpoint ? 1 : 0

  name          = "psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.network_id
}

output "psa_range_name" {
  value = one(google_compute_global_address.psa[*].name)
}
```

## 2. Azure DevOps CI/CD for GCP

### Q6. How do you post the Terraform plan as a comment on the Azure DevOps pull request?

- Run `plan` in a PR validation build.
- Convert the plan to text with `terraform show -no-color`.
- Call the ADO REST API with `System.AccessToken` to add a PR thread.
- Give the build service identity **Contribute to pull requests** permission on the repo.
- Reviewers approve the change and the plan together.

```yaml
- script: |
    cd $(WORKDIR)
    terraform plan -input=false -out=tfplan
    terraform show -no-color tfplan > plan.txt
  displayName: terraform plan

- task: PythonScript@0
  displayName: Comment plan on PR
  condition: eq(variables['Build.Reason'], 'PullRequest')
  env:
    SYSTEM_ACCESSTOKEN: $(System.AccessToken)
  inputs:
    scriptSource: inline
    script: |
      import json, os, urllib.request

      with open(os.path.join(os.environ["WORKDIR"], "plan.txt")) as f:
          plan = f.read()[-60000:]  # ADO comment size limit

      url = (
          f"{os.environ['SYSTEM_COLLECTIONURI']}{os.environ['SYSTEM_TEAMPROJECT']}"
          f"/_apis/git/repositories/{os.environ['BUILD_REPOSITORY_ID']}"
          f"/pullRequests/{os.environ['SYSTEM_PULLREQUEST_PULLREQUESTID']}"
          "/threads?api-version=7.1"
      )
      body = {
          "comments": [{"content": f"### Terraform plan\n```\n{plan}\n```"}],
          "status": "active",
      }
      req = urllib.request.Request(
          url,
          data=json.dumps(body).encode(),
          headers={
              "Authorization": f"Bearer {os.environ['SYSTEM_ACCESSTOKEN']}",
              "Content-Type": "application/json",
          },
      )
      urllib.request.urlopen(req)
```

### Q7. How do you speed up Terraform pipelines in Azure DevOps?

- Cache the provider plugins with the `Cache@2` task, keyed on `.terraform.lock.hcl`.
- Split big stacks into smaller layers (network, IAM, app) so each plan is small.
- Run independent layers in parallel jobs.
- Use `-refresh=false` only for fast PR feedback, never for the real apply.
- Use `-parallelism=20` for stacks with many independent resources.

```yaml
variables:
  TF_PLUGIN_CACHE_DIR: $(Pipeline.Workspace)/.terraform.d/plugin-cache

steps:
  - script: mkdir -p $(TF_PLUGIN_CACHE_DIR)
    displayName: Create plugin cache dir

  - task: Cache@2
    displayName: Cache Terraform providers
    inputs:
      key: 'terraform | "$(Agent.OS)" | $(WORKDIR)/.terraform.lock.hcl'
      restoreKeys: |
        terraform | "$(Agent.OS)"
      path: $(TF_PLUGIN_CACHE_DIR)

  - script: |
      cd $(WORKDIR)
      terraform init -input=false
      terraform plan -input=false -parallelism=20 -out=tfplan
    displayName: init + plan
```

### Q8. Build a container in Azure DevOps and push it to Google Artifact Registry.

- Authenticate with Workload Identity Federation — no JSON keys.
- Configure Docker with `gcloud auth configure-docker`.
- Tag with the commit SHA (immutable), not only `latest`.
- Scan the image before deploying (Artifact Analysis or Trivy).

```yaml
variables:
  REGION: europe-west2
  PROJECT: acme-app-prod
  REPO: apps
  IMAGE: orders-api
  TAG: $(Build.SourceVersion)

steps:
  - template: templates/gcp-auth.yml # writes GOOGLE_APPLICATION_CREDENTIALS

  - script: |
      gcloud auth login --cred-file="$GOOGLE_APPLICATION_CREDENTIALS" --quiet
      gcloud auth configure-docker $(REGION)-docker.pkg.dev --quiet
    displayName: Authenticate Docker to Artifact Registry

  - script: |
      IMG=$(REGION)-docker.pkg.dev/$(PROJECT)/$(REPO)/$(IMAGE)
      docker build -t "$IMG:$(TAG)" .
      docker push "$IMG:$(TAG)"
    displayName: Build and push

  - script: |
      docker run --rm aquasec/trivy:0.55.0 image --exit-code 1 --severity CRITICAL \
        $(REGION)-docker.pkg.dev/$(PROJECT)/$(REPO)/$(IMAGE):$(TAG)
    displayName: Scan image (fail on CRITICAL)
```

### Q9. Deploy to Cloud Run with a canary release and automatic rollback.

- Deploy the new revision with `--no-traffic` and a revision tag.
- Shift 10% of traffic, then check error rate for a few minutes.
- If healthy, move to 100%; if not, send traffic back to the previous revision.
- Keep the previous revision name so rollback is one command.

```bash
#!/usr/bin/env bash
set -euo pipefail

SERVICE=orders-api
REGION=europe-west2
IMAGE="europe-west2-docker.pkg.dev/acme-app-prod/apps/orders-api:${TAG}"

# 1. Deploy with zero traffic
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --no-traffic \
  --tag canary

NEW_REV=$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(status.latestCreatedRevisionName)')

# 2. Send 10% to the new revision
gcloud run services update-traffic "$SERVICE" \
  --region "$REGION" \
  --to-revisions "${NEW_REV}=10"

sleep 300

# 3. Check 5xx count in the last 5 minutes
ERRORS=$(gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.revision_name=${NEW_REV} AND httpRequest.status>=500" \
  --freshness=5m --format='value(timestamp)' | wc -l)

if [ "$ERRORS" -gt 5 ]; then
  echo "Canary unhealthy ($ERRORS errors) - rolling back"
  gcloud run services update-traffic "$SERVICE" --region "$REGION" --to-revisions "${NEW_REV}=0"
  exit 1
fi

# 4. Promote
gcloud run services update-traffic "$SERVICE" --region "$REGION" --to-latest
```

### Q10. What does a Cloud Build pipeline look like, and when would you use it instead of Azure DevOps?

- Use **Cloud Build** when builds must stay inside GCP (private pools in a VPC, VPC-SC perimeters).
- Use **Azure DevOps** when it is the enterprise standard — as in this role — and call GCP through WIF.
- Both can coexist: ADO orchestrates, and Cloud Build runs builds that need private GCP access.

```yaml
# cloudbuild.yaml
steps:
  - id: test
    name: python:3.12-slim
    entrypoint: bash
    args: ["-c", "pip install -r requirements.txt && pytest -q"]

  - id: build
    name: gcr.io/cloud-builders/docker
    args:
      - build
      - -t
      - europe-west2-docker.pkg.dev/$PROJECT_ID/apps/orders-api:$SHORT_SHA
      - .

  - id: push
    name: gcr.io/cloud-builders/docker
    args: ["push", "europe-west2-docker.pkg.dev/$PROJECT_ID/apps/orders-api:$SHORT_SHA"]

  - id: deploy
    name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - orders-api
      - --image=europe-west2-docker.pkg.dev/$PROJECT_ID/apps/orders-api:$SHORT_SHA
      - --region=europe-west2

options:
  logging: CLOUD_LOGGING_ONLY
  pool:
    name: projects/$PROJECT_ID/locations/europe-west2/workerPools/private-pool
```

## 3. GKE and Containers

### Q11. Write a production-ready Dockerfile for a Python API.

- Multi-stage build: install dependencies in one stage, copy only what's needed.
- Run as a non-root user.
- Pin the base image version.
- Use `gunicorn` or `uvicorn` and read `PORT` from the environment (Cloud Run sets it).

```dockerfile
# ---- build stage ----
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime stage ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app

COPY --from=build /install /usr/local
COPY src/ ./src/

RUN useradd --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
```

### Q12. Deploy an app on GKE that uses Workload Identity and autoscales.

- Create a Kubernetes ServiceAccount annotated with the Google service account.
- Bind `roles/iam.workloadIdentityUser` so the pod can act as the Google SA — no keys mounted.
- Set requests and limits; the HPA scales on CPU.
- Add readiness and liveness probes.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: orders-api
  namespace: orders
  annotations:
    iam.gke.io/gcp-service-account: orders-api@acme-app-prod.iam.gserviceaccount.com
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-api
  namespace: orders
spec:
  replicas: 2
  selector:
    matchLabels:
      app: orders-api
  template:
    metadata:
      labels:
        app: orders-api
    spec:
      serviceAccountName: orders-api
      containers:
        - name: api
          image: europe-west2-docker.pkg.dev/acme-app-prod/apps/orders-api:1.4.2
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: orders-api
  namespace: orders
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: orders-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

```hcl
resource "google_service_account_iam_member" "wi" {
  service_account_id = google_service_account.orders_api.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:acme-app-prod.svc.id.goog[orders/orders-api]"
}
```

### Q13. How do you make sure only trusted images run in production?

- Turn on **Binary Authorization** for GKE or Cloud Run.
- The CI pipeline signs (attests) an image only after tests and scans pass.
- The policy blocks any image without the attestation.
- Allow Google-maintained system images so the cluster still works.

```hcl
resource "google_binary_authorization_policy" "policy" {
  project = var.project_id

  admission_whitelist_patterns {
    name_pattern = "gcr.io/google_containers/*"
  }

  default_admission_rule {
    evaluation_mode         = "REQUIRE_ATTESTATION"
    enforcement_mode        = "ENFORCED_BLOCK_AND_AUDIT_LOG"
    require_attestations_by = [google_binary_authorization_attestor.ci.name]
  }

  global_policy_evaluation_mode = "ENABLE"
}
```

## 4. Security and Governance

### Q14. How do you keep secrets out of Terraform and pipelines?

- Store secret **values** in Secret Manager; Terraform manages only the secret **container** and IAM.
- Let apps read secrets at runtime through their service account.
- In ADO, use variable groups linked to Key Vault for Azure-side secrets and mark them secret.
- Never `echo` secrets in scripts; ADO masks secret variables, but not values derived from them.

```hcl
resource "google_secret_manager_secret" "db_password" {
  secret_id = "orders-db-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "app_access" {
  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orders_api.email}"
}

# The value is added out-of-band:
# echo -n "$PASSWORD" | gcloud secrets versions add orders-db-password --data-file=-
```

### Q15. How do you stop data leaving your GCP projects even if credentials leak?

- Use **VPC Service Controls** to put sensitive APIs (BigQuery, GCS) inside a perimeter.
- Calls from outside the perimeter are blocked, even with valid credentials.
- Start in **dry-run** mode, read the violation logs, then enforce.
- Allow CI and admin access through access levels (trusted IP ranges or devices).

```hcl
resource "google_access_context_manager_service_perimeter" "data" {
  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/data_perimeter"
  title  = "data_perimeter"

  use_explicit_dry_run_spec = true

  spec {
    resources = [
      "projects/${var.data_project_number}",
    ]
    restricted_services = [
      "bigquery.googleapis.com",
      "storage.googleapis.com",
    ]
    access_levels = [
      google_access_context_manager_access_level.corp_network.name,
    ]
  }
}
```

### Q16. How do you enforce guardrails before `terraform apply`?

- Scan code in CI with Checkov or tfsec.
- Test the **plan JSON** with OPA/Conftest — this catches values that only exist at plan time.
- Keep org policies as the last line of defence at runtime.
- Fail the pipeline on high-severity findings.

```rego
# policy/gcs.rego
package main

import rego.v1

deny contains msg if {
  some rc in input.resource_changes
  rc.type == "google_storage_bucket"
  rc.change.after.public_access_prevention != "enforced"
  msg := sprintf("%s must enforce public access prevention", [rc.address])
}

deny contains msg if {
  some rc in input.resource_changes
  rc.type == "google_compute_instance"
  some ni in rc.change.after.network_interface
  count(ni.access_config) > 0
  msg := sprintf("%s must not have an external IP", [rc.address])
}
```

```bash
terraform plan -out=tfplan
terraform show -json tfplan > tfplan.json
conftest test tfplan.json --policy policy/
```

## 5. Observability and Reliability

### Q17. Create an alert that pages when a Cloud Run service's error rate is high.

- Use a Cloud Monitoring alert policy with a metric threshold.
- Filter on 5xx responses and align over a short window.
- Send notifications to a channel (email, PagerDuty, Slack webhook).
- Include runbook text in the `documentation` block.

```hcl
resource "google_monitoring_alert_policy" "run_5xx" {
  display_name = "orders-api 5xx rate"
  combiner     = "OR"

  conditions {
    display_name = "5xx > 5/min"

    condition_threshold {
      filter          = <<-EOT
        resource.type = "cloud_run_revision"
        AND resource.labels.service_name = "orders-api"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall.id]

  documentation {
    content   = "Check the latest revision; roll back with: gcloud run services update-traffic orders-api --to-revisions PREV=100"
    mime_type = "text/markdown"
  }
}
```

### Q18. Define an SLO for an API as code.

- Pick an SLI: share of requests that succeed (or are faster than a threshold).
- Set a target such as 99.5% over 28 days.
- Alert on **error-budget burn rate**, not on single errors.

```hcl
resource "google_monitoring_slo" "availability" {
  service      = google_monitoring_custom_service.orders.service_id
  slo_id       = "availability-995"
  display_name = "99.5% of requests succeed"

  goal                = 0.995
  rolling_period_days = 28

  request_based_sli {
    good_total_ratio {
      good_service_filter = join(" AND ", [
        "metric.type=\"run.googleapis.com/request_count\"",
        "resource.labels.service_name=\"orders-api\"",
        "metric.labels.response_code_class=\"2xx\"",
      ])
      total_service_filter = join(" AND ", [
        "metric.type=\"run.googleapis.com/request_count\"",
        "resource.labels.service_name=\"orders-api\"",
      ])
    }
  }
}
```

### Q19. How do you centralise logs from all projects for security and audit?

- Create an **organisation-level aggregated log sink**.
- Route audit logs to a central BigQuery dataset or log bucket in a security project.
- Grant the sink's writer identity access to the destination.
- Set retention to meet compliance needs.

```hcl
resource "google_logging_organization_sink" "audit" {
  name             = "org-audit-to-bq"
  org_id           = var.org_id
  include_children = true
  destination      = "bigquery.googleapis.com/projects/${var.security_project}/datasets/org_audit"
  filter           = "logName:\"cloudaudit.googleapis.com\""

  bigquery_options {
    use_partitioned_tables = true
  }
}

resource "google_bigquery_dataset_iam_member" "sink_writer" {
  project    = var.security_project
  dataset_id = "org_audit"
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_organization_sink.audit.writer_identity
}
```

## 6. Multi-Cloud and AI Integration

### Q20. Connect GCP to an Azure-hosted AI service privately.

- Build HA VPN (or Interconnect) between the GCP VPC and the Azure VNet.
- Expose Azure OpenAI through an Azure **Private Endpoint**.
- Forward DNS for `privatelink.openai.azure.com` from Cloud DNS to Azure DNS.
- Cloud Run reaches the private IP through Direct VPC egress.

```hcl
resource "google_dns_managed_zone" "azure_openai" {
  name        = "azure-openai-fwd"
  dns_name    = "privatelink.openai.azure.com."
  visibility  = "private"
  description = "Forward Azure OpenAI private endpoint lookups to Azure DNS"

  private_visibility_config {
    networks {
      network_url = google_compute_network.vpc.id
    }
  }

  forwarding_config {
    target_name_servers {
      ipv4_address    = var.azure_dns_resolver_ip # Azure DNS Private Resolver inbound IP
      forwarding_path = "private"
    }
  }
}
```

### Q21. Write a Python client that calls AWS Bedrock from GCP without stored keys.

- Get a Google-signed ID token for the service account.
- Exchange it with AWS STS `AssumeRoleWithWebIdentity`.
- Call Bedrock with the short-lived credentials.
- Add timeouts and retries; never log the prompt contents if they may hold PII.

```python
import json

import boto3
import google.auth.transport.requests
from botocore.config import Config
from google.oauth2 import id_token

ROLE_ARN = "arn:aws:iam::111122223333:role/gcp-bedrock-invoker"
MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"


def bedrock_client():
    token = id_token.fetch_id_token(
        google.auth.transport.requests.Request(), "sts.amazonaws.com"
    )
    creds = boto3.client("sts").assume_role_with_web_identity(
        RoleArn=ROLE_ARN,
        RoleSessionName="gcp-orders-api",
        WebIdentityToken=token,
        DurationSeconds=900,
    )["Credentials"]

    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        config=Config(retries={"max_attempts": 4, "mode": "adaptive"}, read_timeout=60),
    )


def summarise(text: str) -> str:
    resp = bedrock_client().converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": f"Summarise:\n{text}"}]}],
        inferenceConfig={"maxTokens": 512},
    )
    return resp["output"]["message"]["content"][0]["text"]
```

### Q22. Copy data from AWS S3 to GCS on a schedule.

- Use **Storage Transfer Service** — managed, incremental and retried.
- Authenticate to AWS with a role that trusts Google's transfer service account (no access keys).
- Schedule it daily; only changed objects are copied.

```hcl
resource "google_storage_transfer_job" "s3_to_gcs" {
  description = "Daily S3 -> GCS sync"
  project     = var.project_id

  transfer_spec {
    aws_s3_data_source {
      bucket_name = "acme-landing-s3"
      role_arn    = "arn:aws:iam::111122223333:role/gcp-storage-transfer"
    }

    gcs_data_sink {
      bucket_name = google_storage_bucket.landing.name
      path        = "from-aws/"
    }

    transfer_options {
      delete_objects_unique_in_sink = false
    }
  }

  schedule {
    schedule_start_date {
      year  = 2026
      month = 10
      day   = 1
    }
    start_time_of_day {
      hours   = 2
      minutes = 0
      seconds = 0
      nanos   = 0
    }
  }
}
```

## 7. Python Automation

### Q23. Write a script that finds and reports idle Compute Engine VMs.

- Use the Recommender API — Google already calculates idle VMs.
- Loop over projects and zones; print project, VM and estimated saving.
- Run it weekly from a pipeline and send the report to the FinOps channel.

```python
import sys

from google.cloud import recommender_v1

RECOMMENDER = "google.compute.instance.IdleResourceRecommender"


def idle_vms(project: str, zones: list[str]):
    client = recommender_v1.RecommenderClient()
    for zone in zones:
        parent = f"projects/{project}/locations/{zone}/recommenders/{RECOMMENDER}"
        for rec in client.list_recommendations(parent=parent):
            cost = rec.primary_impact.cost_projection.cost
            saving = -(cost.units + cost.nanos / 1e9)
            yield zone, rec.description, round(saving, 2)


if __name__ == "__main__":
    project = sys.argv[1]
    zones = ["europe-west2-a", "europe-west2-b", "europe-west2-c"]
    for zone, desc, saving in idle_vms(project, zones):
        print(f"{zone:18} {saving:>10} {desc}")
```

### Q24. Write a Cloud Run function that auto-labels new buckets with the creator's email.

- Trigger it from the Cloud Audit Log `storage.buckets.create` event through Eventarc.
- Read the creator from `protoPayload.authenticationInfo.principalEmail`.
- Convert the email into a valid label value (lowercase, no `@` or `.`).

```python
import re

import functions_framework
from google.cloud import storage


def to_label(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", value.lower())[:63]


@functions_framework.cloud_event
def label_bucket(event):
    payload = event.data["protoPayload"]
    creator = payload["authenticationInfo"]["principalEmail"]
    bucket_name = payload["resourceName"].split("/")[-1]

    bucket = storage.Client().get_bucket(bucket_name)
    labels = bucket.labels or {}
    labels["created-by"] = to_label(creator)
    bucket.labels = labels
    bucket.patch()

    print(f"Labelled {bucket_name} created-by={labels['created-by']}")
```

## 8. Scenario and Behavioural Questions

### Q25. A production `terraform apply` failed halfway. What do you do?

- Stop — don't re-run blindly.
- Read the error; Terraform keeps the resources it already created in state.
- Run `terraform plan` to see what is still missing or changed.
- Fix the cause (quota, IAM, API not enabled), then re-apply the new plan.
- If state is wrong, use `terraform import` or `terraform state rm` carefully, after backing up state.
- Write a short post-incident note and add a guard (validation, pre-check) to stop it happening again.

```bash
# Back up the current state before touching it
gsutil cp gs://acme-tfstate-prod/app/default.tfstate ./backup-$(date +%F-%H%M).tfstate

terraform plan -out=recovery.tfplan
terraform apply recovery.tfplan
```

### Q26. How would you design the GCP landing zone for a new business unit?

- **Resource hierarchy:** Org → folders per environment (prod / non-prod) → projects per app.
- **Networking:** hub-and-spoke or Shared VPC; central egress and firewall policies.
- **Identity:** groups, not users, in IAM; least-privilege custom roles; WIF for CI.
- **Guardrails:** org policies (no external IPs, restrict regions, no SA keys).
- **Logging:** org-level aggregated sinks to a security project.
- **Automation:** project vending through a Terraform module + ADO pipeline.

```hcl
resource "google_org_policy_policy" "restrict_regions" {
  name   = "folders/445566778899/policies/gcp.resourceLocations"
  parent = "folders/445566778899"

  spec {
    rules {
      values {
        allowed_values = ["in:europe-locations"]
      }
    }
  }
}

resource "google_org_policy_policy" "no_sa_keys" {
  name   = "folders/445566778899/policies/iam.disableServiceAccountKeyCreation"
  parent = "folders/445566778899"

  spec {
    rules {
      enforce = "TRUE"
    }
  }
}
```

> **Before the interview**
> - Be ready to explain **why** for every choice — trade-offs matter more than syntax.
> - Have one real story each for: a failed deploy, a security fix, a cost saving, and a multi-cloud integration.
> - Know the difference between Terraform `plan`-time and `apply`-time values.
> - Practise drawing the WIF flow: ADO → OIDC token → GCP STS → service account impersonation.
