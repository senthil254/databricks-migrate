# Unity Catalog Sandbox — Build Record

**Created:** 2026-07-27 · **Workspace:** `<old-workspace>` · **Metastore:** `d1b26481-6554-4eca-9d4d-77578124b759`
**Method:** Databricks CLI + SQL warehouse `Serverless Starter Warehouse` (2X-Small)

---

## Q: Is a new workspace mandatory?

**No — and it is neither possible nor useful on this account.**

**Not possible:** `databricks account workspaces list` → `Error: Not Found`. This
account has no account-console API access (Free/Express tier). Workspace creation is
an account-level operation and cannot be performed from inside a workspace by CLI,
API, or the UI.

**Not useful:** Unity Catalog permits **one metastore per region per account**.
Catalogs live in the *metastore*, not the workspace. A second workspace in
`us-east-2` would attach to this same metastore `d1b26481-…` and therefore see the
**same catalogs**. It would provide zero extra isolation for catalogs, schemas, or
tables.

### New workspace vs existing workspace + new catalog

| Dimension | New workspace | Existing ws + new catalog |
|---|---|---|
| Catalogs/schemas/tables visible | same (shared metastore) | same |
| Isolation of new objects | via catalog boundary | **via catalog boundary — identical** |
| Compute / jobs / notebooks | separate | shared |
| Billing & quota | separate | shared |
| Achievable on this account | ❌ no account API | ✅ yes |
| Time to stand up | N/A | ~5 min |

**Conclusion:** the catalog is the isolation boundary. `lakebridge_demo` is fully
isolated from `dbacademy`, `demo_catalog`, and `workspace`. If you want it *bound* to
this workspace specifically, set `isolation_mode = ISOLATED` (currently `OPEN`).

---

## Objects created (all verified to exist)

```
lakebridge_demo                                   MANAGED_CATALOG, isolation OPEN
└── migration_lab                                 schema
    ├── landing                                   VOLUME (MANAGED)
    │   ├── customers.csv
    │   ├── products.xlsx
    │   ├── orders.parquet
    │   └── products_from_excel.parquet
    ├── migration_metadata                        MANAGED table —  4 rows
    ├── customers_csv                             MANAGED table — 20 rows
    ├── products_excel                            MANAGED table — 15 rows
    └── orders_parquet                            MANAGED table — 50 rows
```

Row counts verified by `SELECT count(*)` and match the generated sources exactly.

### Integrity proof
A three-way join across all three import formats returns sensible aggregates:

| region | brand | orders | revenue |
|---|---|---|---|
| APAC | Globex | 14 | 19,383.45 |
| APAC | Acme | 9 | 11,630.45 |
| AMER | Initech | 6 | 8,810.05 |
| APAC | Initech | 7 | 8,487.70 |

CSV ⋈ Excel-derived ⋈ Parquet all join on real keys — the imports are genuinely usable.

---

## Findings

### 🟡 Finding 6 — REST API cannot create catalogs on Default Storage; SQL can

`POST /api/2.1/unity-catalog/catalogs` failed:
```
Metastore storage root URL does not exist. Default Storage is enabled in your
account. You can use the UI to create a new catalog using Default Storage, or
please provide a storage location for the catalog
```
The equivalent **SQL** succeeded immediately:
```sql
CREATE CATALOG IF NOT EXISTS lakebridge_demo COMMENT '...'
```
`CREATE CATALOG` resolves Default Storage automatically; the REST endpoint demands an
explicit `storage_root`. **Use SQL, not the catalogs REST API, on Default-Storage
accounts.**

### 🟡 Finding 7 — Databricks SQL has no Excel reader

```sql
SELECT * FROM read_files('.../products.xlsx', format => 'xlsx')
→ [CF_FAILED_TO_FIND_PROVIDER] Failed to find provider for xlsx  SQLSTATE 42000
```
`read_files` supports csv/json/parquet/avro/orc/text/binaryFile — **not xlsx**.
`.xlsx` was converted to Parquet locally (pandas + openpyxl) before load. The raw
`.xlsx` is still stored in the volume for provenance.

For a production pipeline, do the conversion in a notebook on compute (pandas/
`spark-excel`) rather than on a laptop, so it is reproducible in-platform.

---

## Import method by format

| Format | Native? | Path used |
|---|---|---|
| CSV | ✅ | `read_files(..., format => 'csv', header => true, inferSchema => true)` |
| Parquet | ✅ | `read_files(..., format => 'parquet')` |
| Excel | ❌ | local xlsx→parquet conversion, then `read_files(parquet)` |

---

## Outstanding

`configure-reconcile` — **not run.** The command was blocked by the local permission
classifier before execution. Nothing partial was created; the reconcile metadata
catalog/schema does not exist.

To run it yourself:
```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
export PATH="$JAVA_HOME/bin:$PATH"
databricks labs lakebridge configure-reconcile -p lakebridge-eval
```
It will prompt for a catalog and schema for reconcile metadata — point it at
`lakebridge_demo` / a new schema such as `reconcile_meta` to keep everything inside
this sandbox.

---

## Teardown (if you want the sandbox gone)

Destructive — review before running; not executed by me:
```sql
DROP CATALOG IF EXISTS lakebridge_demo CASCADE;
```
