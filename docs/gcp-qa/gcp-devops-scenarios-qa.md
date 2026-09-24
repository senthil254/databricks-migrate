# Google Cloud DevOps Engineer — Scenario Q&A

Real-world scenarios with theory and code together, for the Custom Application Architect / Google Cloud Engineer (CL9) role.

> **How to answer a scenario question**
> - **Clarify** — restate the problem and ask one or two sharp questions.
> - **Diagnose** — say what you would check first, and why.
> - **Fix** — give the immediate fix, then the long-term fix.
> - **Prevent** — name the guardrail, test or alert that stops it happening again.
> - Example values: project `acme-app-prod`, region `europe-west2`.

## 1. Terraform Incidents

### S1. Two engineers ran `terraform apply` at the same time and state looks corrupted.

**Scenario:** A developer ran apply from a laptop while the pipeline was also applying. Now `plan` wants to recreate resources that already exist.

**Theory**

- The GCS backend locks state, but only if everyone uses the **same backend**. A laptop with local state bypasses the lock.
- Resources exist in GCP but are missing from state, so Terraform thinks it must create them.
- GCS object versioning on the state bucket lets you roll back to a known-good state.

**What I would do**

- Freeze all applies (disable the pipeline) and tell the team.
- List state versions and restore the last good one.
- Run `plan` and `import` anything that exists in GCP but not in state.
- Long term: remove human write access to the state bucket; only the pipeline SA can apply.

```bash
# 1. List older versions of the state file
gcloud storage ls --all-versions gs://acme-tfstate-prod/app/default.tfstate

# 2. Restore a known-good generation
gcloud storage cp \
  "gs://acme-tfstate-prod/app/default.tfstate#1727170000123456" \
  gs://acme-tfstate-prod/app/default.tfstate

# 3. Check what Terraform now thinks
terraform plan -input=false
```

```hcl
# 4. Adopt anything that exists in GCP but is missing from state
import {
  to = google_cloud_run_v2_service.orders
  id = "projects/acme-app-prod/locations/europe-west2/services/orders-api"
}
```

### S2. A module upgrade wants to destroy and recreate a production database.

**Scenario:** You bumped the Cloud SQL module from v3 to v4. The plan shows `-/+ destroy and then create replacement` for the prod instance.

**Theory**

- Replacement usually happens because a resource **address** changed (renamed or moved into a `for_each`) or because a **ForceNew** attribute changed.
- Read the plan: `# forces replacement` marks the attribute that triggers it.
- An address change can be fixed with `moved` blocks. A ForceNew change needs a migration plan.

**What I would do**

- Never apply. Add `prevent_destroy` so a mistake can't delete the database.
- If the address changed, add a `moved` block and re-plan until it shows zero replacements.
- If an attribute forces replacement, pin the old value or plan a proper migration (replica, promote, cut over).

```hcl
moved {
  from = module.db.google_sql_database_instance.this
  to   = module.db.google_sql_database_instance.main["orders"]
}

resource "google_sql_database_instance" "main" {
  for_each = var.instances

  name             = each.key
  database_version = "POSTGRES_16"
  region           = var.region

  deletion_protection = true

  settings {
    tier = each.value.tier
  }

  lifecycle {
    prevent_destroy = true
  }
}
```

```bash
# Fail the pipeline if the plan would delete anything in prod
terraform show -json tfplan \
  | jq -e '[.resource_changes[] | select(.change.actions | index("delete"))] | length == 0' \
  || { echo "Plan deletes resources - manual approval required"; exit 1; }
```

### S3. Someone changed a firewall rule in the console. How do you find and fix drift?

**Scenario:** An engineer opened port 22 to `0.0.0.0/0` in the console "just for a minute". Nobody reverted it.

**Theory**

- **Drift** is when real infrastructure no longer matches code.
- `terraform plan` detects drift for resources Terraform manages.
- Cloud Audit Logs show **who** changed it and **when**.
- Org policies and firewall policies can block the risky change in the first place.

**What I would do**

- Run `plan` — Terraform will show the rule reverting. Apply to restore the coded state.
- Check audit logs to find the actor and talk to them.
- Add a nightly drift pipeline and an alert on console changes to firewalls.

```bash
gcloud logging read \
  'protoPayload.methodName:"compute.firewalls" AND protoPayload.authenticationInfo.principalEmail!~"gserviceaccount.com$"' \
  --project acme-app-prod \
  --freshness 7d \
  --format 'table(timestamp, protoPayload.authenticationInfo.principalEmail, protoPayload.methodName, protoPayload.resourceName)'
```

```hcl
# Alert whenever a human changes a firewall rule
resource "google_logging_metric" "human_firewall_change" {
  name   = "human-firewall-change"
  filter = <<-EOT
    protoPayload.methodName:"compute.firewalls"
    AND NOT protoPayload.authenticationInfo.principalEmail:"gserviceaccount.com"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}
```

## 2. Pipeline Failures

### S4. The Azure DevOps pipeline fails with `Permission 'iam.serviceAccounts.getAccessToken' denied`.

**Scenario:** The Terraform pipeline worked yesterday. Today the auth step fails with the error above.

**Theory**

- With Workload Identity Federation, ADO's OIDC token is exchanged at Google STS, then the pipeline **impersonates** a service account.
- This error means the federated identity lacks `roles/iam.workloadIdentityUser` on the SA, or the **attribute condition** no longer matches.
- Common causes: the ADO service connection was renamed (the `sub` claim changes), or someone removed the IAM binding.

**What I would do**

- Decode the OIDC token's `sub` claim and compare it with the provider's `attribute_condition`.
- Check IAM on the service account.
- Fix the binding in Terraform, not by hand.

```bash
# Decode the token claims (in a debug step - never print the full token)
cut -d. -f2 "$(Agent.TempDirectory)/oidc.jwt" | base64 -d 2>/dev/null | jq '{iss, sub, aud}'

# Who can impersonate the deployer SA?
gcloud iam service-accounts get-iam-policy \
  tf-deployer@seed-project.iam.gserviceaccount.com \
  --format json | jq '.bindings[] | select(.role=="roles/iam.workloadIdentityUser")'
```

```hcl
resource "google_service_account_iam_member" "ado_wif" {
  service_account_id = google_service_account.tf_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.ado.name}/subject/sc://acme/platform/gcp-prod"
}
```

### S5. Pipelines are slow — a `terraform plan` takes 25 minutes.

**Scenario:** One root module manages 1,800 resources across networking, IAM and apps.

**Theory**

- Plan time grows with the number of resources, because Terraform refreshes each one through the API.
- API rate limits add retries.
- A large blast radius also makes every change risky.

**What I would do**

- Split into layers with separate state: `org`, `network`, `iam`, `apps/<name>`.
- Share values between layers with outputs and `terraform_remote_state` or data sources.
- Run layers in parallel in ADO when they don't depend on each other.
- Cache providers and use `-parallelism` for the heavy layers.

```yaml
stages:
  - stage: Foundation
    jobs:
      - job: network
        steps:
          - template: templates/tf-apply.yml
            parameters: { layer: network }

  - stage: Workloads
    dependsOn: Foundation
    jobs:
      - job: orders
        steps:
          - template: templates/tf-apply.yml
            parameters: { layer: apps/orders }
      - job: payments # runs in parallel with orders
        steps:
          - template: templates/tf-apply.yml
            parameters: { layer: apps/payments }
```

### S6. A secret was printed in the pipeline log.

**Scenario:** A developer added `echo $DB_URL` for debugging. The connection string, including the password, is now in the build log.

**Theory**

- Treat the secret as **compromised** as soon as it's exposed. Deleting the log doesn't undo that.
- ADO masks secret variables, but not values built from them (such as a URL containing the password).

**What I would do**

- Rotate the password immediately and add the new version in Secret Manager.
- Disable the old secret version and restart consumers.
- Delete the pipeline run's logs, and check who viewed or downloaded them.
- Prevent: register derived values as secret, and add a secret scanner (gitleaks) to PR checks.

```bash
# Rotate: add a new version, then disable the old one
NEW_PASS=$(openssl rand -base64 24)
gcloud sql users set-password app --instance orders-db --password "$NEW_PASS"
printf '%s' "$NEW_PASS" | gcloud secrets versions add orders-db-password --data-file=-
gcloud secrets versions disable 7 --secret orders-db-password
```

```yaml
# Mark a derived value as secret so ADO masks it
- script: |
    DB_URL="postgresql://app:$(DB_PASSWORD)@10.10.0.5/orders"
    echo "##vso[task.setvariable variable=DB_URL;issecret=true]$DB_URL"
  displayName: Build connection string (masked)
```

## 3. Production Outages

### S7. After a deploy, Cloud Run returns 503 errors for 30% of requests.

**Scenario:** The new revision is live at 100% traffic. Latency is high and some requests fail with 503.

**Theory**

- A 503 on Cloud Run often means no instance could take the request: cold starts, `max-instances` reached, or the container failing its startup probe.
- High latency plus 503 during a traffic spike points to scaling limits or slow startup.

**What I would do**

- **Mitigate first:** route traffic back to the previous revision (seconds).
- Then diagnose: check instance count against `max-instances`, the startup probe, and container logs.
- Fix: set `min-instances` for warm capacity, raise `max-instances`, tune concurrency, make startup faster.
- Prevent: canary releases with automatic rollback on error rate.

```bash
# Roll back in one command
PREV=$(gcloud run revisions list --service orders-api --region europe-west2 \
  --format 'value(metadata.name)' --sort-by '~metadata.creationTimestamp' --limit 2 | tail -1)
gcloud run services update-traffic orders-api --region europe-west2 --to-revisions "${PREV}=100"
```

```hcl
resource "google_cloud_run_v2_service" "orders" {
  name     = "orders-api"
  location = "europe-west2"

  template {
    scaling {
      min_instance_count = 2
      max_instance_count = 50
    }

    max_instance_request_concurrency = 40

    containers {
      image = var.image

      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 10
      }

      resources {
        cpu_idle          = false # CPU always allocated - faster request handling
        startup_cpu_boost = true
      }
    }
  }
}
```

### S8. GKE pods are stuck in `CrashLoopBackOff` after a release.

**Scenario:** The `orders` deployment rolled out, and new pods restart every few seconds.

**Theory**

- `CrashLoopBackOff` means the container starts, then exits or fails its liveness probe, and Kubernetes backs off between restarts.
- Common causes: a missing env variable or secret, a bad config, a liveness probe that fires before the app is ready, or OOMKilled.

**What I would do**

- Pause the damage: `kubectl rollout undo`.
- Read `describe` events and the **previous** container's logs.
- Check the exit code — `137` usually means OOMKilled, so raise memory limits.
- Prevent: readiness gates plus `maxUnavailable: 0` so bad pods never replace good ones.

```bash
kubectl -n orders rollout undo deployment/orders-api

kubectl -n orders get pods -l app=orders-api
kubectl -n orders describe pod <pod-name> | sed -n '/Last State/,/Ready/p'
kubectl -n orders logs <pod-name> --previous --tail=100
```

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    spec:
      containers:
        - name: api
          startupProbe: # gives slow starters time before liveness kicks in
            httpGet: { path: /healthz, port: 8080 }
            failureThreshold: 30
            periodSeconds: 2
          livenessProbe:
            httpGet: { path: /healthz, port: 8080 }
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /ready, port: 8080 }
            periodSeconds: 5
```

### S9. A whole region is degraded. How does your design survive it?

**Scenario:** `europe-west2` has a partial outage. The business wants the app back within 15 minutes (RTO) and at most 5 minutes of data loss (RPO).

**Theory**

- **RTO** = how fast you recover; **RPO** = how much data you can lose.
- Stateless tiers (Cloud Run, GKE) can run active-active in two regions behind a global load balancer.
- The data tier sets the RPO: Cloud SQL cross-region replica (async, seconds of lag), or Spanner multi-region (RPO 0).

**What I would do**

- Deploy the app to `europe-west2` and `europe-west1` behind a **Global External Application Load Balancer** with serverless NEGs.
- Cloud SQL primary in west2, cross-region read replica in west1; promote it in a DR runbook.
- Practise failover every quarter — an untested DR plan isn't a plan.

```hcl
locals {
  regions = ["europe-west2", "europe-west1"]
}

resource "google_compute_region_network_endpoint_group" "run" {
  for_each = toset(local.regions)

  name                  = "orders-neg-${each.key}"
  region                = each.key
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = "orders-api"
  }
}

resource "google_compute_backend_service" "orders" {
  name                  = "orders-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"

  dynamic "backend" {
    for_each = google_compute_region_network_endpoint_group.run

    content {
      group = backend.value.id
    }
  }
}
```

```bash
# DR runbook step: promote the replica in the healthy region
gcloud sql instances promote-replica orders-db-replica-euw1 --project acme-app-prod
```

## 4. Security Scenarios

### S10. A service account key was found in a public GitHub repo.

**Scenario:** Google emails you: a key for `etl-runner@acme-data.iam.gserviceaccount.com` was detected in a public repo.

**Theory**

- A leaked key gives full access as that SA until it's **disabled**. Attackers scan GitHub within minutes.
- Keys are the root problem: use WIF, attached service accounts and impersonation instead.

**What I would do**

- **Contain:** disable the key right away, then delete it.
- **Investigate:** audit logs for every call made with that key ID.
- **Recover:** move the workload to keyless auth; rotate anything the SA could read.
- **Prevent:** org policy `iam.disableServiceAccountKeyCreation`, plus secret scanning in repos.

```bash
SA=etl-runner@acme-data.iam.gserviceaccount.com
KEY_ID=3f2a9c...   # from the alert

gcloud iam service-accounts keys disable "$KEY_ID" --iam-account "$SA"

gcloud logging read \
  "protoPayload.authenticationInfo.serviceAccountKeyName:\"${KEY_ID}\"" \
  --organization 123456789012 --freshness 30d \
  --format 'table(timestamp, protoPayload.methodName, protoPayload.resourceName, protoPayload.requestMetadata.callerIp)'

gcloud iam service-accounts keys delete "$KEY_ID" --iam-account "$SA" --quiet
```

```hcl
resource "google_org_policy_policy" "no_sa_keys" {
  name   = "organizations/123456789012/policies/iam.disableServiceAccountKeyCreation"
  parent = "organizations/123456789012"

  spec {
    rules {
      enforce = "TRUE"
    }
  }
}
```

### S11. The security team says a GCS bucket with customer data is public.

**Scenario:** A scanner flagged `allUsers` with `roles/storage.objectViewer` on `acme-customer-exports`.

**What I would do**

- Remove the public binding now, then set public access prevention to `enforced`.
- Check data access logs to see if anyone outside downloaded objects (if Data Access logs were on).
- Bring the bucket under Terraform and enforce the org policy `storage.publicAccessPrevention`.
- Report it to the data protection officer if customer data may have been exposed.

```bash
gcloud storage buckets remove-iam-policy-binding gs://acme-customer-exports \
  --member allUsers --role roles/storage.objectViewer

gcloud storage buckets update gs://acme-customer-exports --public-access-prevention
```

```hcl
resource "google_org_policy_policy" "enforce_pap" {
  name   = "organizations/123456789012/policies/storage.publicAccessPrevention"
  parent = "organizations/123456789012"

  spec {
    rules {
      enforce = "TRUE"
    }
  }
}
```

### S12. A developer asks for Owner on the prod project "to fix an urgent bug".

**Theory**

- Standing Owner access breaks least privilege, and one mistake could delete production.
- Better: **time-bound, just-in-time access** with approval and audit.

**What I would say and do**

- "I'll get you exactly the access you need, for the time you need it."
- Grant a narrow role (for example `roles/run.developer`) with an **IAM condition** that expires.
- Or use Privileged Access Manager (PAM) so they request it and a lead approves.
- Everything is logged; the access disappears on its own.

```hcl
resource "google_project_iam_member" "temp_run_dev" {
  project = "acme-app-prod"
  role    = "roles/run.developer"
  member  = "user:dev.name@acme.com"

  condition {
    title       = "expires-incident-4821"
    description = "Temporary access for INC-4821"
    expression  = "request.time < timestamp(\"2026-09-25T18:00:00Z\")"
  }
}
```

## 5. Multi-Cloud and AI Scenarios

### S13. GCP to Azure traffic over VPN is slow and drops during peak hours.

**Scenario:** A Cloud Run app calls an Azure-hosted API over HA VPN. At peak, latency jumps and some calls time out.

**Theory**

- Each HA VPN tunnel carries up to roughly 3 Gbps. Traffic from one flow stays on one tunnel.
- MTU mismatches cause fragmentation and drops (GCP VPN MTU is 1460; the inner payload should be smaller).
- BGP may not be spreading traffic across tunnels (ECMP) if routes aren't advertised equally.

**What I would do**

- Check tunnel throughput and dropped packets in Cloud Monitoring.
- Confirm both tunnels are up and BGP advertises the same routes with equal priority.
- Add more tunnels, or move to **Cross-Cloud Interconnect** for steady high bandwidth.
- Set MSS clamping / MTU correctly on the Azure side.

```bash
# Tunnel status and BGP session state
gcloud compute vpn-tunnels list --filter="region:europe-west2" \
  --format="table(name, status, detailedStatus)"

gcloud compute routers get-status cr-azure --region europe-west2 \
  --format="table(result.bgpPeerStatus[].name, result.bgpPeerStatus[].status, result.bgpPeerStatus[].numLearnedRoutes)"
```

### S14. The external AI API is rate-limiting you (HTTP 429) and users see errors.

**Scenario:** Your GCP app calls an enterprise AI model on Azure OpenAI. At busy times it returns 429 and requests fail.

**Theory**

- 429 means you've hit the provider's tokens-per-minute or requests-per-minute quota.
- Retrying immediately makes it worse — use **exponential backoff with jitter**, and honour `Retry-After`.
- For non-urgent work, decouple with a queue so spikes are smoothed out.

**What I would do**

- Add backoff with jitter and a timeout.
- Push batch jobs through **Pub/Sub** or **Cloud Tasks** with a rate limit.
- Ask for more quota, or spread load across deployments in two regions.
- Cache repeated prompts where it's safe to.

```python
import random
import time

import requests


def call_ai(url: str, headers: dict, payload: dict, max_attempts: int = 6) -> dict:
    for attempt in range(max_attempts):
        resp = requests.post(url, headers=headers, json=payload, timeout=30)

        if resp.status_code == 429 or resp.status_code >= 500:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else min(2**attempt, 30)
            time.sleep(wait + random.uniform(0, 1))  # jitter avoids thundering herd
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"AI API still failing after {max_attempts} attempts")
```

```hcl
# Smooth batch traffic: at most 5 calls/second to the AI API
resource "google_cloud_tasks_queue" "ai_calls" {
  name     = "ai-calls"
  location = "europe-west2"

  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 10
  }

  retry_config {
    max_attempts  = 8
    min_backoff   = "2s"
    max_backoff   = "120s"
    max_doublings = 4
  }
}
```

### S15. An Azure Data Factory pipeline must process files that land in GCS, only once.

**Scenario:** Files arrive in GCS through the day. ADF must process each file exactly once, even if the trigger fires twice.

**Theory**

- Event delivery (Eventarc, Pub/Sub) is **at-least-once**, so duplicates will happen.
- Make the consumer **idempotent**: record each processed object (name + generation) and skip repeats.

**What I would do**

- GCS event → Eventarc → Cloud Run function.
- The function writes a marker to Firestore in a transaction; if it already exists, skip.
- Only new files trigger the ADF `createRun`.

```python
import functions_framework
from google.cloud import firestore

db = firestore.Client()


@firestore.transactional
def claim(tx, ref) -> bool:
    if ref.get(transaction=tx).exists:
        return False
    tx.set(ref, {"claimed_at": firestore.SERVER_TIMESTAMP})
    return True


@functions_framework.cloud_event
def on_file(event):
    data = event.data
    key = f"{data['bucket']}|{data['name']}|{data['generation']}".replace("/", "_")
    ref = db.collection("processed_files").document(key)

    if not claim(db.transaction(), ref):
        print(f"Duplicate event, skipping {key}")
        return

    trigger_adf(bucket=data["bucket"], name=data["name"])  # see earlier Q&A for trigger_adf
```

## 6. Cost and Operations

### S16. The GCP bill went up 40% this month. Where do you start?

**Theory**

- Export billing to BigQuery — it's the only way to break cost down by project, service, SKU and label.
- Labels (`env`, `owner`, `cost-center`) turn "the bill" into "team X's forgotten GKE cluster".

**What I would do**

- Query the billing export for the biggest month-on-month increases.
- Check the usual suspects: idle VMs, unattached disks, oversized GKE node pools, logging ingestion, egress.
- Act: rightsize, set budgets with alerts, schedule dev environments to shut down at night.

```sql
SELECT
  project.id AS project,
  service.description AS service,
  ROUND(SUM(IF(invoice.month = '202609', cost, 0)), 2) AS this_month,
  ROUND(SUM(IF(invoice.month = '202608', cost, 0)), 2) AS last_month,
  ROUND(SUM(IF(invoice.month = '202609', cost, 0))
      - SUM(IF(invoice.month = '202608', cost, 0)), 2) AS increase
FROM `acme-billing.billing_export.gcp_billing_export_v1_XXXXXX`
WHERE invoice.month IN ('202608', '202609')
GROUP BY project, service
ORDER BY increase DESC
LIMIT 15;
```

```hcl
resource "google_billing_budget" "app_prod" {
  billing_account = var.billing_account
  display_name    = "acme-app-prod monthly"

  budget_filter {
    projects = ["projects/${var.project_number}"]
  }

  amount {
    specified_amount {
      currency_code = "GBP"
      units         = "5000"
    }
  }

  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
}
```

### S17. You must onboard 30 new application teams quickly and consistently.

**Theory**

- Manual project creation doesn't scale and drifts.
- Use a **project factory**: one Terraform module + one YAML file per team, applied by a pipeline.
- A pull request is the request form, so every project is reviewed and auditable.

**What I would do**

- Teams open a PR adding `teams/<name>.yaml`.
- The pipeline reads all YAML files and calls the project module for each one.
- Every project gets the same guardrails: labels, budgets, Shared VPC, logging, groups-based IAM.

```yaml
# teams/payments.yaml
name: payments
folder: non-prod
owners_group: grp-payments-admins@acme.com
cost_center: cc-2210
apis:
  - run.googleapis.com
  - secretmanager.googleapis.com
budget_gbp: 1500
```

```hcl
locals {
  teams = {
    for f in fileset("${path.module}/teams", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${path.module}/teams/${f}"))
  }
}

module "project" {
  source   = "git::https://dev.azure.com/acme/platform/_git/tf-modules//project?ref=v3.1.0"
  for_each = local.teams

  name            = each.value.name
  folder_id       = var.folders[each.value.folder]
  billing_account = var.billing_account
  apis            = each.value.apis
  owners_group    = each.value.owners_group
  budget_amount   = each.value.budget_gbp

  labels = {
    team        = each.key
    cost-center = each.value.cost_center
  }
}
```

## 7. Behavioural Scenarios

### S18. Your change caused a production outage. How do you handle it?

- **Own it early.** Tell the incident channel what you changed and when.
- **Restore service first** (rollback), and investigate after.
- **Blameless post-mortem:** timeline, root cause, what went well, what didn't.
- **Concrete actions** with owners: for example, add a canary step or a plan-deletion check.
- Share the learning with other teams so it doesn't happen elsewhere.

### S19. The app team wants to skip the pipeline and deploy from their laptops "because it's faster".

- Listen first: find out **what** is slow — reviews, test time, approvals?
- Explain the risk in their terms: no audit trail, no rollback, and "it worked on my machine" drift.
- Fix the real problem: faster pipelines (caching, parallel jobs), auto-approval for dev, self-service templates.
- Keep the guardrail: only the pipeline SA can deploy to prod (IAM + org policy).
- Measure it: show deploy lead time before and after.

> Final tips for scenario rounds
- Always say **mitigate first, root-cause second**.
- Quantify: "rollback in 30 seconds", "RPO under 5 minutes", "cut plan time from 25 to 4 minutes".
- Name the **prevention** step — interviewers look for engineers who stop repeat incidents.
- Mention trade-offs (cost vs resilience, speed vs control) before you pick an option.
