# Databricks Lakebridge — Technical Session Record

**Date:** 2026-07-27 · **Duration:** ~19:33 – 20:53 IST
**Host:** macOS 26.3.2, Apple Silicon (arm64)
**Workspace:** `https://<old-workspace>.cloud.databricks.com` (org `<workspace-id>`)
**Identity:** <user-email>
**Result:** All objectives met. 30 logged steps, 9 findings, 2 upstream defects found.

> **On screenshots:** no screen captures exist for this session. Everything below is
> verbatim terminal input/output captured live. Where output was not captured, it says
> so explicitly rather than reconstructing it.

---

## Table of Contents

1. [What Lakebridge is](#1-what-lakebridge-is)
2. [Prerequisites and environment audit](#2-prerequisites-and-environment-audit)
3. [Installation](#3-installation)
4. [Authentication](#4-authentication)
5. [Installing Lakebridge](#5-installing-lakebridge)
6. [Installing the transpilers (wizard)](#6-installing-the-transpilers-wizard)
7. [Running the Analyzer](#7-running-the-analyzer)
8. [Running the Transpiler](#8-running-the-transpiler)
9. [Building the Unity Catalog sandbox](#9-building-the-unity-catalog-sandbox)
10. [Importing CSV, Excel, Parquet](#10-importing-csv-excel-parquet)
11. [Configuring Reconcile (wizard)](#11-configuring-reconcile-wizard)
12. [Building a serverless reconcile job](#12-building-a-serverless-reconcile-job)
13. [End-to-end reconciliation proof](#13-end-to-end-reconciliation-proof)
14. [All findings](#14-all-findings)
15. [Command quick reference](#15-command-quick-reference)
16. [Final inventory](#16-final-inventory)

---

## 1. What Lakebridge is

A Databricks Labs toolkit for migrating SQL/ETL workloads onto Databricks. It ships as
a **Databricks CLI extension**, not a standalone binary.

| Component | Job | Runs where |
|---|---|---|
| **Profiler** | Surveys the source estate; sizing and TCO | Local |
| **Analyzer** | Scores code complexity, flags migration blockers | Local (x86 binary) |
| **Transpiler** | Converts source SQL → Databricks SQL | Local (JVM) |
| **Reconciler** | Verifies data matches after migration | Databricks job |

Three transpiler engines exist: **BladeBridge** (mature), **Morpheus** (next-gen, JVM),
and **Switch** (LLM-based). Snowflake selection routes to Morpheus.

---

## 2. Prerequisites and environment audit

Official requirements (from https://databrickslabs.github.io/lakebridge/docs/installation/):

- Python **3.10.1 – 3.14.x**
- **Java 21+** (required by Morpheus)
- Databricks CLI (no minimum version stated)
- Network to GitHub, Maven Central, PyPI

### Audit commands

```bash
python3 --version; which python3
pip3 --version
uv --version
git --version
java -version
databricks --version
docker --version
terraform --version
aws --version
sw_vers; uname -m
brew --version
```

### Captured output

```
=== PYTHON ===
Python 3.9.6
/usr/bin/python3
--- pip ---
pip 21.2.4 from /Applications/Xcode.app/.../python3.9/site-packages/pip (python 3.9)
--- uv ---
uv 0.11.29 (901092ee1 2026-07-15 aarch64-apple-darwin)
=== GIT ===
git version 2.53.0
=== JAVA ===
The operation couldn't be completed. Unable to locate a Java Runtime.
=== DATABRICKS CLI ===
(eval):1: command not found: databricks
=== DOCKER ===
(eval):1: command not found: docker
=== TERRAFORM ===
(eval):1: command not found: terraform
=== AWS CLI ===
aws-cli/2.35.11 Python/3.14.5 Darwin/25.3.0 exe/arm64
=== OS ===
ProductName:  macOS
ProductVersion: 26.3.2
BuildVersion: 25D2150
arm64
=== BREW ===
Homebrew 6.0.10
```

### Result

| Requirement | Needed | Found | Verdict |
|---|---|---|---|
| Python | 3.10.1–3.14.x | 3.9.6 default | ⚠️ too old |
| Python (alt) | — | brew 3.14.6; uv 3.12.13, 3.11.15 | ✅ usable |
| Java | 21+ | **absent** | ❌ blocker |
| Databricks CLI | required | **absent** | ❌ blocker |
| uv | recommended | 0.11.29 | ✅ |
| Docker / Terraform / gcloud / az | not required | absent | ➖ n/a |

### Network preflight

```bash
for u in https://github.com https://repo1.maven.org/maven2/ https://pypi.org; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 15 -I "$u")
  echo "$u -> HTTP $code"
done
```

```
https://github.com -> HTTP 200
https://repo1.maven.org/maven2/ -> HTTP 200
https://pypi.org -> HTTP 200
```

---

## 3. Installation

### 3.1 Databricks CLI

```bash
brew tap databricks/tap
brew install databricks
```

**This failed on first attempt:**

```
==> Tapping databricks/tap
Cloning into '/opt/homebrew/Library/Taps/databricks/homebrew-tap'...
Tapped 1 formula (21 files, 277.5KB).
--- installing CLI ---
Error: Refusing to load formula databricks/tap/databricks from untrusted tap
databricks/tap.
Run `brew trust --formula databricks/tap/databricks` or `brew trust databricks/tap`
to trust it.
```

**Fix** — Homebrew now requires explicit trust for third-party taps. `databricks/tap`
is Databricks' own published tap, referenced by the official docs:

```bash
brew trust databricks/tap
brew install databricks
```

```
Trusted tap: databricks/tap
```

**Verify:**

```bash
databricks --version
which databricks
```

```
Databricks CLI v1.9.0
/opt/homebrew/bin/databricks
```

### 3.2 Java 21

The documented cask route **failed** in a non-interactive shell:

```bash
brew install --cask temurin@21
```

```
==> Running installer for temurin@21 with `sudo` (which may request your password)...
sudo: a terminal is required to read the password; either use the -S option to read
from standard input or configure an askpass helper
sudo: a password is required
Error: Failure while executing; `/usr/bin/sudo -u root -E ... /usr/sbin/installer
-pkg .../OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.11_10.pkg -target /` exited with 1.
```

**Fix** — use the **formula** instead of the cask. It installs into the Homebrew
Cellar and needs no root:

```bash
brew install openjdk@21
```

```
openjdk@21 is keg-only, which means it was not symlinked into /opt/homebrew,
because this is an alternate version of another formula.

If you need to have openjdk@21 first in your PATH, run:
  echo 'export PATH="/opt/homebrew/opt/openjdk@21/bin:$PATH"' >> ~/.zshrc
```

Keg-only means it is not auto-linked, so set the path yourself:

```bash
export JAVA_HOME="/opt/homebrew/opt/openjdk@21"
export PATH="$JAVA_HOME/bin:$PATH"
java -version
```

```
openjdk version "21.0.12" 2026-07-21
OpenJDK Runtime Environment Homebrew (build 21.0.12)
OpenJDK 64-Bit Server VM Homebrew (build 21.0.12, mixed mode, sharing)
```

Persist it:

```bash
printf '\n# Java 21 for Databricks Lakebridge (Morpheus transpiler)\nexport JAVA_HOME="/opt/homebrew/opt/openjdk@21"\nexport PATH="$JAVA_HOME/bin:$PATH"\n' >> ~/.zshrc
```

---

## 4. Authentication

OAuth (U2M) is preferred — no token is ever typed or stored in plain text.

```bash
databricks auth login \
  --host https://<old-workspace>.cloud.databricks.com \
  --profile lakebridge-eval
```

```
Databricks skills are not installed. To work with Databricks reliably, first run:
databricks aitools install
Profile lakebridge-eval was successfully saved
```

A browser window opens for approval. Verify:

```bash
databricks current-user me -p lakebridge-eval
```

```json
{
  "active": true,
  "emails": [{ "primary": true, "type": "work", "value": "<user-email>" }],
  "entitlements": [
    { "value": "allow-cluster-create" },
    { "value": "allow-instance-pool-create" }
  ],
  ...
}
```

### Workspace inventory

```bash
databricks catalogs list   -p lakebridge-eval
databricks warehouses list -p lakebridge-eval
databricks clusters list   -p lakebridge-eval
```

```
=== CATALOGS ===
    "full_name": "workspace"
    "full_name": "system"
    "full_name": "samples"
    "full_name": "dbacademy"
    "full_name": "demo_catalog"

=== WAREHOUSES ===
ID                Name                          Size      State
<old-warehouse-id>  Serverless Starter Warehouse  2X-Small  STOPPED

=== CLUSTERS ===
ID  Name  State
```

**Critical observation:** the cluster list is **empty**. This is a serverless-only
workspace. This single fact causes Finding 8 later.

---

## 5. Installing Lakebridge

The default `python3` is 3.9.6, below Lakebridge's 3.10.1 floor. Prepend a supported
interpreter so the labs venv picks it up:

```bash
PY312=$(dirname $(uv python find 3.12))
export PATH="$PY312:/opt/homebrew/opt/openjdk@21/bin:$PATH"
python3 --version     # -> Python 3.12.13
databricks labs install lakebridge -p lakebridge-eval
```

```
19:35:02  INFO [databricks.sdk] Using Databricks CLI authentication
19:35:04  INFO [d.l.lakebridge.install] Successfully Setup Lakebridge Components Locally
19:35:04  INFO [d.l.lakebridge.install] For more information, please visit
          https://databrickslabs.github.io/lakebridge/
```

Verify the venv interpreter and version:

```bash
~/.databricks/labs/lakebridge/state/venv/bin/python --version
cat ~/.databricks/labs/lakebridge/state/version.json
```

```
Python 3.12.13
{"version":"v0.14.2","date":"2026-07-27T19:34:49.657807+05:30"}
```

Confirm the command surface:

```bash
databricks labs lakebridge --help -p lakebridge-eval
```

```
Code Transpiler and Data Reconciliation tool for Accelerating Data onboarding to
Databricks from EDW, CDW and other ETL sources.

Available Commands:
  aggregates-reconcile        Reconcile source and target data using aggregated metrics
  analyze                     Analyze existing non-Databricks database or ETL sources
  configure-database-profiler (Experimental) Configure database profiler
  configure-reconcile         Configure 'reconcile' dependencies
  describe-transpile          Describe installed transpilers
  execute-database-profiler   (Experimental) Profile the source system database
  install-transpile           Install & optionally configure 'transpile' dependencies
  llm-transpile               Transpile using LLM-based conversion (EXPERIMENTAL)
  reconcile                   Reconcile source and target data residing on Databricks
  test-profiler-connection    (Internal) Test connection to the source database
  transpile                   Transpile SQL/ETL sources to Databricks-compatible code
```

---

## 6. Installing the transpilers (wizard)

```bash
databricks labs lakebridge install-transpile -p lakebridge-eval
```

This is **interactive**. Answers used, with reasoning:

| Prompt | Answer | Reason |
|---|---|---|
| Select the source dialect | `8` (snowflake) | Matches the sample corpus |
| Enter input SQL path | `.../samples/snowflake` | Source directory |
| Enter output directory | `.../out/transpiled` | Target directory |
| Enter error file path | `.../out/errors.log` | Warning/error sink |
| Validate syntax and semantics? | `no` | **Validation needs a running warehouse.** Saying yes on a serverless-only workspace with a stopped warehouse risks a hang or failure |
| Open config in browser? | `no` | Headless |

Selecting snowflake routed to Morpheus — this is why Java 21 was required:

```
19:35:56  INFO [d.l.l.transpiler.installers] Successfully installed bladebridge
          transpiler (v0.3.0)
19:36:45  INFO [d.l.lakebridge.install] Lakebridge will use the Morpheus transpiler
19:37:36  INFO [d.l.lakebridge.install] Saving configuration file config.yml
19:37:50  INFO [d.l.lakebridge.install] Finished configuring lakebridge `transpile`.
19:37:56  INFO [d.l.lakebridge.install] Installation completed successfully!
```

Verify:

```bash
databricks labs lakebridge describe-transpile -p lakebridge-eval
```

```
Transpiler   Installed Version  Plugin Configuration
==========   =================  ====================
Bladebridge  0.3.0              ~/.databricks/labs/remorph-transpilers/bladebridge/lib/config.yml
Morpheus     0.9.0              ~/.databricks/labs/remorph-transpilers/databricks-morph-plugin/lib/config.yml

Supported Source Dialects
=========================
 - datastage
 - informatica (desktop edition)
 - informatica cloud
 - mssql
 - netezza
 - oracle
 - redshift
 - snowflake
 - ssis
 - synapse
 - teradata
```

---

## 7. Running the Analyzer

```bash
databricks labs lakebridge analyze -p lakebridge-eval \
  --source-directory .../samples/snowflake \
  --report-file .../out/analysis.xlsx \
  --source-tech Snowflake
```

### First attempt — FAILED

```
ERROR [d.l.bladespector.analyzer] Analysis failed
Traceback (most recent call last):
  File ".../bladespector/analyzer.py", line 142, in _run_binary
    with subprocess.Popen(
  File ".../subprocess.py", line 1955, in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
OSError: [Errno 86] Bad CPU type in executable:
'.../databricks/labs/bladespector/Analyzer/MacOS/analyzer'
```

### Diagnosis — evidence, not guesswork

```bash
B=~/.databricks/labs/lakebridge/state/venv/lib/python3.12/site-packages/databricks/labs/bladespector/Analyzer/MacOS/analyzer
file "$B"
uname -m
/usr/bin/pgrep -q oahd && echo "Rosetta running" || echo "NO Rosetta 2"
```

```
.../analyzer: Mach-O 64-bit executable x86_64      <- not a universal binary
arm64                                               <- host is Apple Silicon
NO - Rosetta 2 not installed
```

Lakebridge ships this binary as **x86_64-only**. On Apple Silicon without Rosetta 2
the kernel refuses to execute it. Upstream packaging gap, not misconfiguration.

### Fix (needs your password — cannot be automated)

```bash
softwareupdate --install-rosetta --agree-to-license
```

```
2026-07-27 19:43:07.570 softwareupdate[87173:7641770] Package Authoring Error:
122-10397: Package reference com.apple.pkg.RosettaUpdateAuto is missing
installKBytes attribute
Install of Rosetta 2 finished successfully
```

> The `Package Authoring Error` line is a cosmetic defect in Apple's own package
> metadata. It does **not** indicate failure.

Verify three ways:

```bash
/usr/bin/pgrep -q oahd && echo "YES - Rosetta 2 active"
ls -d /Library/Apple/usr/share/rosetta
"$B" --help >/dev/null 2>&1; echo "exit code: $?"
```

```
YES - Rosetta 2 active
/Library/Apple/usr/share/rosetta
exit code: 255      # program ran and rejected the flag; NOT errno 86
```

### Second attempt — SUCCESS

```
ANLZ_CC [694]: PROGRESS:  Consolidating data
ANLZ_CC [694]: PROGRESS:  Creating stats file
CodeAnalyzer [1309]: Analyzer run completed. for -t SQL, -r .../out/analysis.xlsx
ANLZ_CC [702]: INFO:      DONE!
19:44:31 INFO [d.l.l.analyzer.lakebridge_analyzer] Analyzed Snowflake files in
         .../samples/snowflake; report saved to: .../out/analysis.xlsx
```

### Report contents

Analyzer engine **5.6.6 build 20251204**, 8 sheets, 16 KB.

| Script | Lines | Category | Complexity |
|---|---|---|---|
| `01_customer_dim.sql` | 19 | `TABLE_DDL_AS_SELECT` | LOW |
| `02_orders_agg.sql` | 34 | `CTE_TABLE` | LOW |
| `03_semi_structured.sql` | 21 | `CREATE_VIEW` | LOW |
| `04_merge_scd2.sql` | 24 | `MERGE` | LOW |

Function census: `CURRENT_TIMESTAMP` ×3, `COUNT` ×2, `SUM` ×2, `TO_VARCHAR` ×2,
`DATEADD` ×2, plus `FLATTEN`, `DATE_TRUNC`, `LISTAGG`, `RANK`, `ROW_NUMBER`,
`DIV0`, `TRY_CAST`. Every Snowflake-specific construct planted in the corpus was
detected.

> **Gotcha:** `analyze` writes `.tmp` scratch files into the **`--report-file`
> directory** during the run. Point it at a writable scratch dir.

---

## 8. Running the Transpiler

```bash
databricks labs lakebridge transpile -p lakebridge-eval \
  --input-source .../samples/snowflake \
  --output-folder .../out/transpiled \
  --source-dialect snowflake \
  --error-file-path .../out/errors.log \
  --skip-validation true
```

```
19:38:59 INFO Processed file: .../01_customer_dim.sql (errors: 0)
19:38:59 INFO Processed file: .../02_orders_agg.sql (errors: 0)
19:39:00 INFO Processed file: .../03_semi_structured.sql (errors: 3)
19:39:00 INFO Processed file: .../04_merge_scd2.sql (errors: 0)
19:39:00 INFO Done transpiling.
19:39:00 WARNING .../03_semi_structured.sql: 3 warnings found

total_files_processed  total_queries_processed  analysis_error_count
4                      4                        0
parsing_error_count  validation_error_count  generation_error_count
0                    0                       0
```

### Conversions verified correct

Input (`01_customer_dim.sql`, Snowflake):

```sql
SELECT
    NVL(c.c_address, 'UNKNOWN')                   AS address,
    IFF(c.c_acctbal < 0, 'DELINQUENT', 'ACTIVE')  AS account_status,
    DATEADD(day, -30, CURRENT_DATE())             AS lookback_start
FROM raw.customer c
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.c_custkey ORDER BY c.c_acctbal DESC) = 1;
```

Output (Databricks):

```sql
SELECT
    COALESCE(c.c_address, 'UNKNOWN') AS address,
    IF(c.c_acctbal < 0, 'DELINQUENT', 'ACTIVE') AS account_status,
    DATE_ADD(day, -30, CURRENT_DATE()) AS lookback_start
FROM raw.customer AS c
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.c_custkey ORDER BY c.c_acctbal DESC NULLS FIRST) = 1;
```

| Snowflake | → Databricks | |
|---|---|---|
| `NVL` | `COALESCE` | ✅ |
| `IFF` | `IF` | ✅ |
| `DATEADD` | `DATE_ADD` | ✅ |
| `LATERAL FLATTEN(input => …)` | `LATERAL VARIANT_EXPLODE(…)` | ✅ |
| `OBJECT_CONSTRUCT` | `STRUCT(… AS …)` | ✅ |
| `IS_NULL_VALUE` | `IS_VARIANT_NULL` | ✅ |
| `QUALIFY` | preserved, `NULLS FIRST` made explicit | ✅ |
| `MERGE` multi-`WHEN` | preserved | ✅ |

### The 3 warnings — a real transpiler defect

```
TranspileError(code=None, kind=INTERNAL, severity=WARNING,
  path='.../03_semi_structured.sql', message='Unsupported expression in a JSON path')
```

Output:

```sql
CAST(e.payload/* SESSION_USER() */.id AS VARCHAR(16777216)) AS user_id,
-- FIXME: Unsupported expression in a JSON path
```

The JSON path key `user` was parsed as Snowflake's `USER` session function and
replaced with a **comment**, producing structurally broken SQL — emitted only as a
warning.

**Isolated with a controlled probe.** Same statement, four different keys:

```sql
SELECT
  e.payload:user.id::STRING     AS a_user,
  e.payload:customer.id::STRING AS b_customer,
  e.payload:table.id::STRING    AS c_table,
  e.payload:device.id::STRING   AS d_device
FROM raw.events e;
```

Result:

```sql
SELECT
    CAST(e.payload/* SESSION_USER() */.id AS VARCHAR(16777216)) AS a_user,
    -- FIXME: Unsupported expression in a JSON path
    CAST(e.payload:customer.id AS VARCHAR(16777216)) AS b_customer,
    CAST(e.payload:table.id AS VARCHAR(16777216)) AS c_table,
    CAST(e.payload:device.id AS VARCHAR(16777216)) AS d_device
FROM raw.events AS e;
```

| Key | Result |
|---|---|
| `:user` | ❌ broken |
| `:customer` | ✅ |
| `:table` (reserved word) | ✅ |
| `:device` | ✅ |

Since `:table` — a reserved SQL word — transpiles fine, this is **not** general
reserved-word handling. It is specific to the `USER` function collision.

**Workaround:** bracket-quote the key in the source — `e.payload['user'].id` — or
post-fix the emitted `-- FIXME` sites.

---

## 9. Building the Unity Catalog sandbox

### Does this need a new workspace? No.

```bash
databricks account workspaces list -p lakebridge-eval
```

```
Error: Not Found
```

No account-console API on this tier — workspace creation is impossible from here.
It is also **pointless**: Unity Catalog allows one metastore per region per account,
and catalogs live in the metastore. A second workspace in `us-east-2` would attach to
the same metastore `d1b26481-…` and see the same catalogs.

```bash
databricks metastores current -p lakebridge-eval
```

```json
{
  "default_catalog_name": "workspace",
  "metastore_id": "d1b26481-6554-4eca-9d4d-77578124b759",
  "workspace_id": <workspace-id>
}
```

**The catalog is the isolation boundary, not the workspace.**

### Start the warehouse

```bash
databricks warehouses start <old-warehouse-id> -p lakebridge-eval
databricks warehouses get   <old-warehouse-id> -p lakebridge-eval | grep state
```

```
"state": "RUNNING",
```

### Create the catalog — REST fails, SQL works

```
create_catalog failed: API request failed: Client error '400 Bad Request' for url
'.../api/2.1/unity-catalog/catalogs'
- Metastore storage root URL does not exist. Default Storage is enabled in your
account. You can use the UI to create a new catalog using Default Storage, or please
provide a storage location for the catalog
(for example 'CREATE CATALOG myCatalog MANAGED LOCATION '<location-path>').
```

The SQL equivalent succeeds immediately:

```sql
CREATE CATALOG IF NOT EXISTS lakebridge_demo
  COMMENT 'Lakebridge evaluation sandbox - created 2026-07-27';
```

```json
{"status":{"state":"SUCCEEDED"}}
```

> **Rule:** on Default-Storage accounts use SQL `CREATE CATALOG`, never the
> `/api/2.1/unity-catalog/catalogs` REST endpoint.

### Schema, metadata table, volume

```sql
CREATE SCHEMA IF NOT EXISTS lakebridge_demo.migration_lab
  COMMENT 'Migration lab: metadata, imported CSV/Excel/Parquet datasets';

CREATE TABLE IF NOT EXISTS lakebridge_demo.migration_lab.migration_metadata (
  migration_id      BIGINT     COMMENT 'Surrogate key',
  source_system     STRING     COMMENT 'Source platform e.g. Snowflake',
  source_object     STRING     COMMENT 'Fully qualified source object',
  target_object     STRING     COMMENT 'Fully qualified Databricks target',
  object_type       STRING     COMMENT 'TABLE | VIEW | MERGE | CTE',
  complexity        STRING     COMMENT 'LOW | MEDIUM | HIGH from analyzer',
  transpile_status  STRING     COMMENT 'SUCCESS | WARNING | FAILED',
  warning_count     INT        COMMENT 'Transpiler warnings emitted',
  loaded_at         TIMESTAMP  COMMENT 'Load timestamp'
) USING DELTA
COMMENT 'Lakebridge migration control table';

CREATE VOLUME IF NOT EXISTS lakebridge_demo.migration_lab.landing
  COMMENT 'Landing zone for CSV/Excel/Parquet source files';
```

Insert the real transpile outcomes:

```sql
INSERT INTO lakebridge_demo.migration_lab.migration_metadata VALUES
 (1,'Snowflake','raw.customer -> analytics.dim_customer',
    'lakebridge_demo.migration_lab.dim_customer','TABLE_DDL_AS_SELECT','LOW','SUCCESS',0,current_timestamp()),
 (2,'Snowflake','raw.orders (monthly agg)',
    'lakebridge_demo.migration_lab.orders_agg','CTE_TABLE','LOW','SUCCESS',0,current_timestamp()),
 (3,'Snowflake','raw.events -> analytics.v_event_detail',
    'lakebridge_demo.migration_lab.v_event_detail','CREATE_VIEW','LOW','WARNING',3,current_timestamp()),
 (4,'Snowflake','raw.part -> analytics.dim_product',
    'lakebridge_demo.migration_lab.dim_product','MERGE','LOW','SUCCESS',0,current_timestamp());
```

```
num_affected_rows  num_inserted_rows
4                  4
```

---

## 10. Importing CSV, Excel, Parquet

### Generate sample data

```python
import pandas as pd, numpy as np
np.random.seed(42)

csv_df = pd.DataFrame({
    "customer_id": range(1001, 1021),
    "customer_name": [f"Customer_{i}" for i in range(1, 21)],
    "region": np.random.choice(["AMER","EMEA","APAC"], 20),
    "account_balance": np.round(np.random.uniform(-500, 9500, 20), 2),
    "signup_date": pd.date_range("2024-01-15", periods=20, freq="17D").date,
})
csv_df.to_csv("data/customers.csv", index=False)
# products.xlsx (15 rows), orders.parquet (50 rows) built similarly
```

```
customers.csv           20 rows x 5 cols
products.xlsx           15 rows x 5 cols
orders.parquet          50 rows x 6 cols
```

### Upload to the volume

```bash
V=dbfs:/Volumes/lakebridge_demo/migration_lab/landing
for f in customers.csv products.xlsx orders.parquet; do
  databricks fs cp "data/$f" "$V/$f" -p lakebridge-eval --overwrite
done
databricks fs ls "$V" -p lakebridge-eval
```

```
customers.csv
orders.parquet
products.xlsx
```

### CSV and Parquet — native

```sql
CREATE OR REPLACE TABLE lakebridge_demo.migration_lab.customers_csv AS
SELECT * FROM read_files(
  '/Volumes/lakebridge_demo/migration_lab/landing/customers.csv',
  format => 'csv', header => true, inferSchema => true);

CREATE OR REPLACE TABLE lakebridge_demo.migration_lab.orders_parquet AS
SELECT * FROM read_files(
  '/Volumes/lakebridge_demo/migration_lab/landing/orders.parquet',
  format => 'parquet');
```

### Excel — NOT native

Tested rather than assumed:

```sql
SELECT * FROM read_files(
  '/Volumes/lakebridge_demo/migration_lab/landing/products.xlsx',
  format => 'xlsx') LIMIT 5;
```

```
[CF_FAILED_TO_FIND_PROVIDER] Failed to find provider for xlsx SQLSTATE: 42000
```

`read_files` supports csv / json / parquet / avro / orc / text / binaryFile — **not
xlsx**. Convert first:

```python
import pandas as pd
df = pd.read_excel("data/products.xlsx", sheet_name="catalog")
df.to_parquet("data/products_from_excel.parquet", index=False)
```

```
converted xlsx -> parquet: 15 rows,
cols=['product_id','product_name','brand','retail_price','in_stock']
```

```sql
CREATE OR REPLACE TABLE lakebridge_demo.migration_lab.products_excel AS
SELECT * FROM read_files(
  '/Volumes/lakebridge_demo/migration_lab/landing/products_from_excel.parquet',
  format => 'parquet');
```

> In production do this conversion in a notebook on compute (pandas or `spark-excel`)
> so it is reproducible in-platform, not on a laptop.

### Verify

```sql
SELECT 'migration_metadata' AS tbl, count(*) AS rows FROM lakebridge_demo.migration_lab.migration_metadata
UNION ALL SELECT 'customers_csv',  count(*) FROM lakebridge_demo.migration_lab.customers_csv
UNION ALL SELECT 'products_excel', count(*) FROM lakebridge_demo.migration_lab.products_excel
UNION ALL SELECT 'orders_parquet', count(*) FROM lakebridge_demo.migration_lab.orders_parquet
ORDER BY tbl;
```

```
customers_csv       20
migration_metadata   4
orders_parquet      50
products_excel      15
```

All counts match the generated sources exactly.

### Integrity proof — cross-format join

```sql
SELECT c.region, p.brand, count(*) AS order_cnt, round(sum(o.order_total),2) AS revenue
FROM lakebridge_demo.migration_lab.orders_parquet o
JOIN lakebridge_demo.migration_lab.customers_csv  c ON o.customer_id = c.customer_id
JOIN lakebridge_demo.migration_lab.products_excel p ON o.product_id  = p.product_id
GROUP BY c.region, p.brand ORDER BY revenue DESC LIMIT 8;
```

```
region  brand    order_cnt  revenue
APAC    Globex   14         19383.45
APAC    Acme      9         11630.45
AMER    Initech   6          8810.05
APAC    Initech   7          8487.7
EMEA    Initech   4          6265.97
EMEA    Acme      4          4522.42
EMEA    Globex    4          4239.34
AMER    Acme      1            61.14
```

---

## 11. Configuring Reconcile (wizard)

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
export PATH="$JAVA_HOME/bin:$PATH"
databricks labs lakebridge configure-reconcile -p lakebridge-eval
```

### Answers and reasoning

| Prompt | Answer | Why |
|---|---|---|
| Select the Data Source | `1` databricks | **Critical.** Choosing `snowflake` demands live Snowflake credentials (account, user, key, warehouse). With none available that is a dead end. `databricks` needs no external credentials |
| Select the report type | `0` all | Provisions metadata for schema + row + data comparison; nothing foreclosed |
| Source catalog | `lakebridge_demo` | Real sandbox data |
| Source schema | `migration_lab` | |
| Target catalog | `lakebridge_demo` | |
| Target schema | `migration_lab` | |
| Metadata catalog | `lakebridge_demo` | Keeps everything in the sandbox |
| Metadata schema | `reconcile_meta` → create? `yes` | New, isolated |
| Volume name | `reconcile_volume` → create? `yes` | Default accepted |
| Open config in browser | `no` | Headless |

> **Prompt-order trap:** the source/target prompts come **first** and refer to the
> *data being reconciled*. The metadata location is asked **four prompts later**.
> Confusing the two is easy and produces a broken config.

### Output

```
20:25:42 INFO [d.l.l.helpers.metastore] Created schema `reconcile_meta` in catalog
         `lakebridge_demo`.
20:26:47 INFO [d.l.l.helpers.metastore] Created volume `reconcile_volume` in catalog
         `lakebridge_demo` and schema `reconcile_meta`
20:26:48 INFO [d.l.lakebridge.install] Saving configuration file reconcile.yml
20:27:58 INFO [d.l.l.deployment.table] Deploying table aggregate_detai in
         lakebridge_demo.reconcile_meta
20:28:00 INFO [d.l.l.deployment.table] Deploying table aggregate_rule in
         lakebridge_demo.reconcile_meta
20:28:03 INFO [d.l.l.deployment.recon] Deploying reconciliation dashboards.
20:28:06 INFO Dashboard deployed with URL: https://<old-workspace>.cloud.databricks.com/sql/dashboardsv3/01f189cb92cf1083aaf3a52f94ce442a
20:28:07 INFO [d.l.l.deployment.job] Deploying reconciliation job.
20:28:08 INFO [d.l.l.deployment.job] Creating new job configuration for job
         `Reconciliation Runner`
20:28:08 ERROR [d.l.lakebridge.configure-reconcile]
         InvalidParameterValue: Only serverless compute is supported in the workspace.
```

### What deployed vs what failed

Succeeded:

```
lakebridge_demo.reconcile_meta.aggregate_details  MANAGED
lakebridge_demo.reconcile_meta.aggregate_metrics  MANAGED
lakebridge_demo.reconcile_meta.aggregate_rules    MANAGED
lakebridge_demo.reconcile_meta.details            MANAGED
lakebridge_demo.reconcile_meta.main               MANAGED
lakebridge_demo.reconcile_meta.metrics            MANAGED
```

Plus `reconcile_volume`, 2 dashboards, and `reconcile.yml`:

```yaml
metadata_config:
  catalog: lakebridge_demo
  schema: reconcile_meta
  volume: reconcile_volume
report_type: all
source:
  catalog: lakebridge_demo
  dialect: databricks
  schema: migration_lab
target:
  catalog: lakebridge_demo
  schema: migration_lab
version: 2
```

Failed — verified empty:

```bash
databricks jobs list -p lakebridge-eval
```

```
(no output — no jobs exist)
```

---

## 12. Building a serverless reconcile job

### Root cause, from Lakebridge's own source

`~/.databricks/labs/lakebridge/lib/src/databricks/labs/lakebridge/deployment/job.py`:

```python
def _default_job_cluster(self) -> JobCluster:
    latest_lts_spark = self._ws.clusters.select_spark_version(latest=True, long_term_support=True)
    return JobCluster(
        job_cluster_key=self.DEFAULT_CLUSTER_NAME,
        new_cluster=compute.ClusterSpec(
            data_security_mode=compute.DataSecurityMode.USER_ISOLATION,
            spark_conf={},
            node_type_id=self._get_default_node_type_id(),
            autoscale=compute.AutoScale(min_workers=2, max_workers=10),
            spark_version=latest_lts_spark,
        ),
    )
```

Lakebridge always builds a **classic job cluster**. A serverless-only workspace
rejects that payload server-side. The `allow-cluster-create` entitlement does not
override it — rejection happens at job creation, not permission check.

### The replacement spec

Same task, same entry point; only the compute layer differs.

| Lakebridge default | Serverless build |
|---|---|
| `job_clusters: [Remorph_Reconciliation_Cluster]` | *(omitted)* |
| `task.job_cluster_key = "Remorph_Reconciliation_Cluster"` | `task.environment_key = "lakebridge_env"` |
| — | `environments: [{environment_key, spec:{client:"3", dependencies:[<wheel>]}}]` |

`out/recon_job_serverless.json`:

```json
{
  "name": "LAKEBRIDGE_Reconciliation_Runner",
  "tags": { "version": "v0.14.2", "provisioned_by": "manual-serverless-workaround" },
  "max_concurrent_runs": 2,
  "parameters": [
    { "name": "operation_name", "default": "reconcile" },
    { "name": "install_folder", "default": "/Users/<user-email>/.lakebridge" }
  ],
  "environments": [
    {
      "environment_key": "lakebridge_env",
      "spec": {
        "client": "3",
        "dependencies": [
          "/Workspace/Users/<user-email>/.lakebridge/wheels/databricks_labs_lakebridge-0.14.2-py3-none-any.whl"
        ]
      }
    }
  ],
  "tasks": [
    {
      "task_key": "run_reconciliation",
      "description": "Run the reconciliation process",
      "environment_key": "lakebridge_env",
      "python_wheel_task": {
        "package_name": "databricks_labs_lakebridge",
        "entry_point": "reconcile",
        "parameters": [
          "{{job.parameters.[operation_name]}}",
          "{{job.parameters.[install_folder]}}"
        ]
      }
    }
  ]
}
```

```bash
databricks jobs create --json @out/recon_job_serverless.json -p lakebridge-eval
```

```json
{ "job_id": <reconcile-job-id> }
```

### Register it in the install state

`ReconcileRunner._get_recon_job_id` reads `install_state.jobs[RECON_JOB_NAME]`, where
`RECON_JOB_NAME = "Reconciliation Runner"`:

```python
def _get_recon_job_id(self) -> int:
    if RECON_JOB_NAME in self._install_state.jobs:
        return int(self._install_state.jobs[RECON_JOB_NAME])
    raise SystemExit("Reconcile Job ID not found. Please try reinstalling.")
```

So `state.json` must contain:

```json
{
  "resources": {
    "dashboards": {
      "aggregate_reconciliation_metrics": "01f189cb91e51a74b1cb3aaf1393cf45",
      "reconciliation_metrics": "01f189cb92cf1083aaf3a52f94ce442a"
    },
    "jobs": { "Reconciliation Runner": "<reconcile-job-id>" }
  },
  "version": 1
}
```

```bash
databricks workspace import /Users/<user-email>/.lakebridge/state.json \
  --file out/state_new.json --format AUTO --overwrite -p lakebridge-eval
```

### First run — config missing, not a compute failure

```bash
databricks jobs run-now --json '{"job_id":<reconcile-job-id>,"job_parameters":{"operation_name":"reconcile"}}' -p lakebridge-eval
```

```
Error: failed to reach TERMINATED or SKIPPED, got INTERNAL_ERROR:
Task run_reconciliation failed with message: Workload failed, see run output for details.
```

```bash
databricks jobs get-run-output 150867893138633 -p lakebridge-eval
```

```
ResourceDoesNotExist: Path
(/Users/<user-email>/.lakebridge/recon_config_databricks_lakebridge_demo_all.json)
doesn't exist.
```

**Important:** the wheel installed, the entry point ran, and Lakebridge's code
executed. The compute problem was solved. This is a **missing table-mapping file**,
which `configure-reconcile` does *not* create — you author it, or use
`auto-configure-recon-tables`.

Filename pattern: `recon_config_<dialect>_<source_catalog>_<report_type>.json`

---

## 13. End-to-end reconciliation proof

A self-match proves nothing. A target with **deliberate defects** was built instead:

```sql
CREATE OR REPLACE TABLE lakebridge_demo.migration_lab.customers_v2 AS
SELECT
  customer_id,
  CASE WHEN customer_id = 1003 THEN 'Customer_MODIFIED' ELSE customer_name END AS customer_name,
  CASE WHEN customer_id = 1007 THEN 'ANTARCTICA'        ELSE region        END AS region,
  CASE WHEN customer_id = 1011 THEN account_balance + 999.99 ELSE account_balance END AS account_balance,
  signup_date
FROM lakebridge_demo.migration_lab.customers_csv
WHERE customer_id <> 1019;     -- deleted row
```

Four defects: one changed name, one changed region, one changed number, one deleted row.

Mapping file:

```json
{
  "tables": [
    {
      "source_name": "customers_csv",
      "target_name": "customers_v2",
      "join_columns": ["customer_id"],
      "select_columns": ["customer_id", "customer_name", "region", "account_balance"]
    }
  ],
  "version": 2
}
```

```bash
databricks workspace import \
  /Users/<user-email>/.lakebridge/recon_config_databricks_lakebridge_demo_all.json \
  --file out/recon_config_databricks_lakebridge_demo_all.json --format AUTO --overwrite \
  -p lakebridge-eval

databricks jobs run-now --json '{"job_id":<reconcile-job-id>,"job_parameters":{"operation_name":"reconcile"}}' -p lakebridge-eval
```

```json
"status": {
  "state": "TERMINATED",
  "termination_details": { "code": "SUCCESS", "message": "", "type": "SUCCESS" }
},
"task_key": "run_reconciliation"
```

### Run header

```sql
SELECT recon_id, source_type, source_table.table_name AS src,
       target_table.table_name AS tgt, report_type, start_ts, end_ts
FROM lakebridge_demo.reconcile_meta.main ORDER BY start_ts DESC LIMIT 5;
```

```
recon_id                          source_type  src            tgt            report_type
36d1b2e2ac6b43d29ad51be0a4c87749  Databricks   customers_csv  customers_v2   all
start_ts                     end_ts
2026-07-27T15:21:52.970Z     2026-07-27T15:22:24.255Z      (~31 s)
```

### Metrics

```sql
SELECT
  recon_metrics.row_comparison.missing_in_source     AS missing_in_src,
  recon_metrics.row_comparison.missing_in_target     AS missing_in_tgt,
  recon_metrics.column_comparison.absolute_mismatch  AS col_mismatch,
  recon_metrics.column_comparison.threshold_mismatch AS thresh_mismatch,
  recon_metrics.schema_comparison                    AS schema_match,
  run_metrics.status                                 AS status
FROM lakebridge_demo.reconcile_meta.metrics ORDER BY inserted_ts DESC LIMIT 3;
```

```
missing_in_src  missing_in_tgt  col_mismatch  thresh_mismatch  schema_match  status
0               1               3             0                true          false
```

| Metric | Value | Expected |
|---|---|---|
| `missing_in_source` | 0 | 0 ✅ |
| `missing_in_target` | 1 | 1 ✅ |
| `absolute_mismatch` | 3 | 3 ✅ |
| `threshold_mismatch` | 0 | 0 ✅ |
| `schema_comparison` | true | identical ✅ |
| `status` | false | correct — differences found ✅ |

### Detail records

```sql
SELECT recon_type, data FROM lakebridge_demo.reconcile_meta.details
WHERE recon_type IN ('mismatch','missing_in_target') ORDER BY recon_type LIMIT 10;
```

| customer_id | Column | Source | Target | Verdict |
|---|---|---|---|---|
| 1003 | `customer_name` | `Customer_3` | `Customer_MODIFIED` | ✅ caught |
| 1007 | `region` | `APAC` | `ANTARCTICA` | ✅ caught |
| 1011 | `account_balance` | `4060.7` | `5060.69` | ✅ caught |
| 1019 | *(whole row)* | present | absent | ✅ `missing_in_target` |

**4 injected defects → 4 detected, 0 missed, 0 false positives.**

---

## 14. All findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | 🔴 | Analyzer binary is x86_64-only; fails on Apple Silicon without Rosetta 2 | ✅ resolved |
| 2 | 🟡 | Morpheus misparses `:user` JSON path as `SESSION_USER()` | ⚠️ open (upstream) |
| 3 | 🟢 | Transpilation quality otherwise correct across 8 construct families | ✅ |
| 4 | 🟡 | Workspace is serverless-only; no clusters | ℹ️ constraint |
| 5 | 🟢 | Analyzer output verified — 8 sheets, correct categories and function census | ✅ |
| 6 | 🟡 | UC catalogs REST API unusable on Default Storage; SQL works | ✅ workaround |
| 7 | 🟡 | No native Excel reader in Databricks SQL | ✅ workaround |
| 8 | 🔴 | `configure-reconcile` job deploy fails on serverless-only workspaces | ✅ workaround |
| 9 | 🟢 | End-to-end reconciliation verified with injected defects | ✅ |

### Worth reporting upstream to `databrickslabs/lakebridge`

- **Finding 2** — `:user` JSON path corruption. Reproducible with a 4-line query. Emits
  broken SQL as a *warning*, so it can slip into production silently.
- **Finding 8** — job deployment should detect serverless-only workspaces and emit an
  `environments` spec instead of a classic job cluster.

---

## 15. Command quick reference

```bash
# --- one-time setup ---
brew trust databricks/tap && brew install databricks
brew install openjdk@21
export JAVA_HOME="/opt/homebrew/opt/openjdk@21"
export PATH="$JAVA_HOME/bin:$PATH"
softwareupdate --install-rosetta --agree-to-license      # Apple Silicon only

databricks auth login --host <workspace-url> --profile lakebridge-eval
databricks current-user me -p lakebridge-eval

# --- install lakebridge ---
export PATH="$(dirname $(uv python find 3.12)):$PATH"    # ensure Python >= 3.10.1
databricks labs install lakebridge -p lakebridge-eval
databricks labs lakebridge install-transpile -p lakebridge-eval   # interactive
databricks labs lakebridge describe-transpile -p lakebridge-eval

# --- daily use ---
databricks labs lakebridge analyze -p lakebridge-eval \
  --source-directory ./samples/snowflake \
  --report-file ./out/analysis.xlsx --source-tech Snowflake

databricks labs lakebridge transpile -p lakebridge-eval \
  --input-source ./samples/snowflake --output-folder ./out/transpiled \
  --source-dialect snowflake --error-file-path ./out/errors.log \
  --skip-validation true

databricks labs lakebridge configure-reconcile -p lakebridge-eval  # interactive
databricks jobs run-now --json '{"job_id":<ID>,"job_parameters":{"operation_name":"reconcile"}}' -p lakebridge-eval

# --- maintenance ---
databricks labs upgrade lakebridge
databricks labs uninstall lakebridge
```

---

## 16. Final inventory

### Local

| Component | Version | Path |
|---|---|---|
| Databricks CLI | 1.9.0 | `/opt/homebrew/bin/databricks` |
| Lakebridge | 0.14.2 | `~/.databricks/labs/lakebridge` |
| Bladebridge | 0.3.0 | `~/.databricks/labs/remorph-transpilers/bladebridge` |
| Morpheus | 0.9.0 | `~/.databricks/labs/remorph-transpilers/databricks-morph-plugin` |
| Analyzer engine | 5.6.6 b20251204 | bundled |
| Java | OpenJDK 21.0.12 | `/opt/homebrew/opt/openjdk@21` |
| Labs venv Python | 3.12.13 | `~/.databricks/labs/lakebridge/state/venv` |
| Rosetta 2 | installed | `/Library/Apple/usr/share/rosetta` |

### Workspace

```
lakebridge_demo                              MANAGED_CATALOG (isolation OPEN)
├── migration_lab
│   ├── landing                              VOLUME
│   ├── migration_metadata                    4 rows
│   ├── customers_csv                        20 rows
│   ├── products_excel                       15 rows
│   ├── orders_parquet                       50 rows
│   └── customers_v2                         19 rows (defect target)
└── reconcile_meta
    ├── reconcile_volume                     VOLUME
    ├── main / metrics / details
    └── aggregate_rules / aggregate_metrics / aggregate_details

Job    <reconcile-job-id>  LAKEBRIDGE_Reconciliation_Runner (serverless)
Config /Workspace/Users/<user-email>/.lakebridge/{config,reconcile}.yml
       + state.json, recon_config_databricks_lakebridge_demo_all.json
```

### Known maintenance caveat

The reconcile job is **hand-built**. `databricks labs upgrade lakebridge` or a re-run
of `configure-reconcile` will try to recreate the Lakebridge-managed job and fail on
the same serverless constraint. It will not touch job `<reconcile-job-id>`, but it will
not maintain it either. Re-apply `out/recon_job_serverless.json` after upgrades.

### Teardown

```sql
DROP CATALOG IF EXISTS lakebridge_demo CASCADE;
```
```bash
databricks jobs delete <reconcile-job-id> -p lakebridge-eval
databricks labs uninstall lakebridge
```

## 17. G13/G14 — how `transpile` validation and `reconcile` really work (hands-on, local CLI)

Two separate real investigations, both done with the locally-configured `databricks labs
lakebridge` CLI and `databricks` CLI against this project's real workspace (`lakebridge-eval`
profile) — not simulated, not read from docs alone.

### 17.1 Does `transpile --skip-validation false` actually create anything? (G13)

**No.** Read the real Lakebridge source (`helpers/validation.py`): every "validated" statement
is wrapped in `EXPLAIN {statement}` before being run — `EXPLAIN CREATE TABLE ...` returns a
query plan, it never executes the statement. Confirmed live:
- Ran `transpile` with `--catalog-name lakebridge_demo --schema-name g14_validation_test
  --skip-validation false` against a real sample file.
- `SHOW TABLES IN lakebridge_demo.g14_validation_test` was empty before and after.
- Validation correctly caught a real error (`[TABLE_OR_VIEW_NOT_FOUND] raw.customer`) — proving
  it's a genuine live check, not a no-op — while still creating nothing.

**Validation compute requirement, and the free-tier wall:** validation needs to run
`EXPLAIN` somewhere live. Read `helpers/db_sql.py`: if a `warehouse_id` is configured,
Lakebridge uses `StatementExecutionBackend` (the SQL Statement Execution API against a SQL
warehouse) — **no cluster needed**. Confirmed live by setting `DATABRICKS_WAREHOUSE_ID` to this
project's existing `Serverless Starter Warehouse` (`<old-warehouse-id>`) — validation ran to
completion using only the warehouse already in use everywhere else in this project. Without a
`warehouse_id` set, it falls back to `DatabricksConnectBackend` (needs a live Spark Connect
session via `databricks-connect`), which failed on this Free/Express workspace with
`"Serverless mode is not yet supported in this version of Databricks Connect"` — reproduced with
the raw official `DatabricksSession.builder.serverless(True)` API too, ruling out a
Lakebridge-specific bug. **Local environment note**: the transpiler engine (Morpheus, LSP-based)
needs a real JVM — `JAVA_HOME=/opt/homebrew/opt/openjdk@21` (already documented in §6) must be
exported in the shell running the CLI, or it fails with `IllegalStateException: Client has not
yet registered its transpile capability.` This same error also appears if `--input-source` is a
**single file** instead of a **directory** — confirmed by matching this project's own working
`migrate.py` pattern (`--input-source <dir>` containing a file literally named `<name>.sql`).

### 17.2 What does `reconcile` actually check? (G14) — real Redshift ↔ Databricks test

This project's existing reconcile setup (§11–§13) is Databricks-to-Databricks only. To test a
real Redshift source without touching that working config, a **fully separate** setup was built:

- Real Unity Catalog Connection `g14_redshift_conn` (`CREATE CONNECTION ... TYPE redshift`),
  verified live via `remote_query('g14_redshift_conn', query => 'SELECT COUNT(*) ...')`.
- Separate workspace install folder `/Users/.../.lakebridge_g14_redshift/` (not `.lakebridge/`),
  its own `reconcile.yml` (source dialect `redshift`, `uc_connection_name: g14_redshift_conn`)
  and `recon_config_redshift_g14_redshift_conn_all.json`.
- Separate job `LAKEBRIDGE_G14_Redshift_Reconciliation_Runner` (job_id `843454635342447`,
  reusing the same manual-serverless-job pattern from §12 — the existing job `<reconcile-job-id>`
  was never touched), reusing the existing `lakebridge_demo.reconcile_meta` metadata infra
  (purely additive, tagged by `recon_id`).
- All local files under `out/g14_redshift_reconcile/` (also untouched: everything under the
  original `out/recon_job_serverless.json`/existing config).

**Why the direct-Python route (used for §17.1) doesn't work for reconcile**: reconcile's real
source (`reconcile/connectors/redshift.py`) is built entirely on Spark DataFrames — no
`StatementExecutionBackend`-style fallback exists. It genuinely requires a live Spark Connect
session, which this workspace cannot provide (same wall as above). The only way reconcile can
run here is as an actual deployed **Job** on serverless job compute (native execution, no
outbound Connect session needed) — exactly the workaround already proven in §12.

**Four real runs, four real results:**

| # | Target state | `source_record_count` | `target_record_count` | `missing_in_target` | `absolute_mismatch` | `schema_comparison` | `run_metrics.status` |
|---|---|---|---|---|---|---|---|
| 1 | table doesn't exist | — | — | — | — | — | **job run fails outright**: `[TABLE_OR_VIEW_NOT_FOUND]` — reconcile queries the live target immediately, no graceful "0% match" path |
| 2 | table created from converted DDL, **no data** | 202 | 0 | 202 | 0 | **False** | False |
| 3 | table populated with real copied data | 202 | 202 | 0 | 2 (`venuename`) | **False** | False |
| 4 | new fixed-length-source table, converted + populated | 3 | 3 | 0 | 0 | **True** | **True** |

Run 2's `schema_comparison: False` root cause, found by direct comparison of live column types:
Redshift `venuename character varying(100)` was converted by Morpheus to Databricks
`CHAR(100)` — **fixed**-length, not `VARCHAR`/`STRING`. A real, semantic Convert-phase type
defect, distinct from (and unrelated to) the row-count mismatch. Run 4 used a source table with
genuinely fixed-length Redshift columns (`CHAR(5)`, `CHAR(3)`) — Morpheus converted these
correctly, and reconcile passed cleanly on every axis, confirming the CHAR/VARCHAR issue in Run 2
is real and specific to variable-length source columns, not a general defect or a reconcile bug.

**Run 5 (follow-up): does `schema_comparison` care about declared length within the same type
family, not just the type family itself?** Built a real Redshift `CHAR(10)` column vs a
manually-created Databricks `CHAR(20)` column (same 2 rows, `'ABC'`/`'XYZ'`, copied cleanly —
no apostrophe-bug risk this time). Result:
```
source_record_count=2  target_record_count=2  missing_in_target=0
absolute_mismatch=0     (data itself compared identical)
schema_comparison=False
```
**`CHAR(10)` and `CHAR(20)` do not match**, even though both are `CHAR` and the actual data
values compared equal. `schema_comparison` checks the exact type signature — base type *and*
declared length — not just "is this a compatible string type." Table of all real
`schema_comparison` outcomes observed:

| Source type | Target type | `schema_comparison` |
|---|---|---|
| `CHAR(5)` | `CHAR(5)` | ✅ True |
| `VARCHAR(100)` | `CHAR(100)` | ❌ False — different type family |
| `CHAR(10)` | `CHAR(20)` | ❌ False — same family, different length |

**Run 6 (follow-up): does clean, simple data (no apostrophes/special characters) reconcile
cleanly, isolating the schema issue as purely structural?** Built a real Redshift table
(`id INT`, `name VARCHAR(20)`, `amount INT`) with plain values (`'Alpha'`, `'Beta'`, `'Gamma'`),
converted it for real (again: `character varying(20)` → `CHAR(20)`, the same Morpheus behavior
as run 2/3 — now observed a third time, confirming it's consistent, not a one-off), created the
destination from that exact converted DDL, copied the same clean data. Result:
```
source_record_count=3  target_record_count=3  missing_in_target=0
absolute_mismatch=0     (perfect data match — no apostrophe-bug risk this time)
schema_comparison=False (same VARCHAR→CHAR defect as before)
```
Confirms the run 2/3 pattern precisely: **value-level data comparison is not the problem** —
clean data reconciles with zero mismatches every time. The `schema_comparison=False`/overall
`status=False` outcome is driven entirely by Morpheus's `VARCHAR`→`CHAR` conversion, independent
of data quality. Across every run in this investigation, the only clean `status=True` pass (run
4) was the one case where the source column was already fixed-length, so the converted DDL
happened to match exactly — meaning, based on everything tested here, **any Redshift
`VARCHAR`/`character varying` column will fail reconcile's schema check after going through
`transpile`, regardless of how clean the data is.**

**Run 7 (final): a genuine, full `SUCCESS` — built deliberately, not simulated.** Chose types
known from runs 1-6 to convert exactly: real Redshift source `id INTEGER`, `code CHAR(4)`,
`qty INTEGER` (no `VARCHAR` anywhere). Real `transpile --source-dialect redshift` converted it
to `id INT NOT NULL, code CHAR(4), qty INT` — an exact type match, zero correction needed.
Created the destination from that **real converted SQL verbatim** (only Redshift-specific
storage hints like `ENCODE`/`DISTSTYLE`, which Databricks doesn't understand, were stripped —
column type definitions are exactly what Lakebridge produced), copied identical simple data
(`AA01`/`BB02`/`CC03`, `10`/`20`/`30`), and ran the same real reconcile job:
```
source_record_count=3  target_record_count=3  missing_in_target=0
absolute_mismatch=0     mismatch_columns=""
schema_comparison=True
run_metrics.status=True   -- full pass, every axis
```
This closes the loop: reconcile itself is correct and reliable throughout — every failure in
runs 2/3/5/6 traced to one specific, reproducible Lakebridge conversion defect
(`VARCHAR`→`CHAR`), never to reconcile's own comparison logic. When the source type is one
Lakebridge converts correctly, and the destination is built from the real converted SQL with
matching clean data, reconcile passes cleanly on every axis at once — target existence, row
presence, schema/type match, and value-level data match.

Run 3's 2-row `absolute_mismatch` (`Dick's Sporting Goods Park` → `Dicks Sporting Goods Park`)
was traced to a **separate, real bug in this project's own** `databricks_target._sql_literal()`/
`insert_rows()` — reproduced directly: `SELECT 'Dick''s Sporting Goods Park'` returns
`Dicks Sporting Goods Park` via this project's `execute()` path, silently dropping the escaped
apostrophe. Not a Lakebridge defect — reconcile correctly caught a real data discrepancy that
this project's own tooling introduced. Worth a follow-up fix, tracked here rather than silently
ignored.

**What `reconcile` genuinely checks, confirmed against real behavior across all four runs:**
1. **Target existence** — not a soft check; a missing target hard-fails the whole run.
2. **Row-level presence** — `missing_in_source`/`missing_in_target`, via the configured
   `join_columns`.
3. **Schema/type match** — `schema_comparison`, a structural check fully independent of data
   (Run 2 proves this: failed with zero data present, purely on type mismatch).
4. **Value-level data match** — `column_comparison.absolute_mismatch`/`threshold_mismatch`, real
   per-row, per-column value comparison (Run 3 proves this: row counts matched, but 2 real value
   differences were still caught).

All four checks are independent axes, not a single pass/fail — a run can have correct row
counts and still fail (Run 3, data-level), or have zero data and still fail for a structural
reason unrelated to the missing rows (Run 2, schema-level).

**Left in place as reference** (not torn down): `g14_redshift_conn` connection, job
`843454635342447`, workspace folder `.lakebridge_g14_redshift/`, schema
`lakebridge_demo.g14_recon_test` (tables `venue`, `g14_fixed_char_test`), Redshift table
`public.g14_fixed_char_test`, and all local files under `out/g14_redshift_reconcile/`.
