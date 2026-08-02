# Lakebridge Evaluation — Results

**Run date:** 2026-07-27
**Host:** macOS 26.3.2 / arm64
**Workspace:** `<old-workspace>.cloud.databricks.com`
**Identity:** you@example.com
**Structured log:** `logs/run-20260727T194005.jsonl`

---

## Validation Checklist

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Network to GitHub / Maven Central / PyPI | ✅ PASS | all HTTP 200 |
| 2 | Databricks CLI installed | ✅ PASS | `Databricks CLI v1.9.0` |
| 3 | Java 21+ installed | ✅ PASS | `OpenJDK 21.0.12` |
| 4 | CLI authenticated | ✅ PASS | `current-user me` → you@example.com |
| 5 | Workspace reachable | ✅ PASS | 5 catalogs, 1 warehouse, 0 clusters |
| 6 | Lakebridge installed | ✅ PASS | `v0.14.2` |
| 7 | Labs venv Python in range | ✅ PASS | `3.12.13` (range 3.10.1–3.14.x) |
| 8 | Transpilers installed | ✅ PASS | Bladebridge 0.3.0, Morpheus 0.9.0, 11 dialects |
| 9 | **Analyzer runs** | ✅ **PASS** (after Rosetta 2) | `analysis.xlsx`, 8 sheets, engine 5.6.6 — see Finding 1 |
| 10 | Transpiler produces output | ✅ PASS | 4/4 files, 0 parse/generation errors |
| 11 | Reconcile validated | ⏸️ **GATED** | creates UC resources — awaiting approval |
| 12 | Structured logs written | ✅ PASS | 15-entry JSONL |
| 13 | No destructive operation performed | ✅ PASS | no DROP/DELETE/overwrite executed |

**Score: 12 pass / 0 fail / 1 gated.**

---

## Finding 1 — ✅ RESOLVED: Analyzer is x86_64-only, needed Rosetta 2

> **Status 2026-07-27 19:44 — RESOLVED.** User ran
> `softwareupdate --install-rosetta --agree-to-license`. Verified: `oahd` running,
> `/Library/Apple/usr/share/rosetta` present, binary now execs (exit 255 on a bad
> flag, no longer errno 86). Analyzer re-run **succeeded** — see Finding 5.
> The cosmetic `Package Authoring Error: 122-10397` in Apple's installer output is
> benign and did not affect the install.

Original diagnosis retained below for the record.

### (original) BLOCKER: Analyzer is x86_64-only, cannot run on Apple Silicon

**Command:**
```
databricks labs lakebridge analyze --source-directory samples/snowflake \
  --report-file out/analysis.xlsx --source-tech Snowflake
```

**Error:**
```
OSError: [Errno 86] Bad CPU type in executable:
.../site-packages/databricks/labs/bladespector/Analyzer/MacOS/analyzer
```

**Diagnosis (objective evidence):**
```
$ file .../Analyzer/MacOS/analyzer
Mach-O 64-bit executable x86_64      # <- not a universal binary
$ uname -m
arm64                                 # <- host is Apple Silicon
$ pgrep oahd
(no output)                           # <- Rosetta 2 not installed
```

Lakebridge 0.14.2 bundles the Bladespector analyzer as a **non-universal x86_64
Mach-O binary**. On an Apple Silicon Mac without Rosetta 2 the kernel refuses to
exec it. This is a packaging gap upstream, not a misconfiguration.

**Remediation — requires your password (I cannot run it):**
```bash
softwareupdate --install-rosetta --agree-to-license
```
Then re-run Step 11. Everything else is already in place.

**Impact:** the Analyzer (pre-migration complexity assessment) is unavailable
until Rosetta is installed. Transpile is unaffected — it is JVM-based.

---

## Finding 2 — 🟡 DEFECT: Morpheus misparses `user` as a JSON path key

**Severity:** Medium — produces silently wrong SQL, flagged only as a WARNING.

Snowflake input:
```sql
e.payload:user.id::STRING AS user_id
```
Databricks output:
```sql
CAST(e.payload/* SESSION_USER() */.id AS VARCHAR(16777216)) AS user_id
-- FIXME: Unsupported expression in a JSON path
```

The path key `user` is parsed as Snowflake's `USER` session function and replaced
with a **comment**, yielding structurally broken SQL.

**Isolated with a controlled probe** (`/tmp/lb_probe/`) — same statement, four keys:

| JSON path key | Result |
|---|---|
| `:user` | ❌ becomes `/* SESSION_USER() */` |
| `:customer` | ✅ correct |
| `:table` (reserved word) | ✅ correct |
| `:device` | ✅ correct |

So it is **not** general reserved-word handling — it is specific to the `USER`
function collision. Worth filing upstream against `databrickslabs/lakebridge`.

**Workaround:** bracket-quote the key in the source before transpiling —
`e.payload['user'].id` — or post-fix the emitted `-- FIXME` sites.

---

## Finding 3 — 🟢 Transpilation quality is good

Verified correct rewrites on the sample corpus:

| Snowflake | → Databricks | |
|---|---|---|
| `NVL` | `COALESCE` | ✅ |
| `IFF` | `IF` | ✅ |
| `DATEADD` | `DATE_ADD` | ✅ |
| `LATERAL FLATTEN(input => ...)` | `LATERAL VARIANT_EXPLODE(...)` | ✅ |
| `OBJECT_CONSTRUCT` | `STRUCT(... AS ...)` | ✅ |
| `IS_NULL_VALUE` | `IS_VARIANT_NULL` | ✅ |
| `QUALIFY ROW_NUMBER()` | preserved, `NULLS FIRST` made explicit | ✅ |
| `MERGE` multi-`WHEN` | preserved | ✅ |
| `DIV0`, `TRY_CAST`, `LISTAGG` | handled | ✅ |

---

## Finding 4 — 🟡 Workspace is serverless-only

`databricks clusters list` returns **empty**; the only compute is
`Serverless Starter Warehouse` (2X-Small, **STOPPED**).

Consequences:
- Transpile **validation** (`--skip-validation false`) needs a running warehouse.
- `reconcile` runs jobs — feasibility on this tier is unverified.
- Your identity does hold `allow-cluster-create`, so a cluster could be created if
  a workflow demands one.

---

## Finding 5 — 🟢 Analyzer output verified

`out/analysis.xlsx` (16 KB, real XLSX), Analyzer engine **5.6.6 build 20251204**,
run duration 0h 0m 0s. Eight sheets produced: Summary, SQL Programs, SQL Script
Categories, UNKNOWN SQL Category, SQL Special Patterns, Functions, Functions by
Script, Referenced Objects / Xrefs.

Code-base summary it derived from the sample corpus:

| Metric | Value |
|---|---|
| Total SQL scripts | 4 |
| Total CTAS scripts | 1 |
| Total views | 1 |
| Total tables referenced | 1 |
| Total DDLs / MVs / indices / packages | 0 |

Per-script classification — all four correctly categorised, all rated `LOW` complexity:

| Script | Lines | Category | Complexity |
|---|---|---|---|
| `01_customer_dim.sql` | 19 | `TABLE_DDL_AS_SELECT` | LOW |
| `02_orders_agg.sql` | 34 | `CTE_TABLE` | LOW |
| `03_semi_structured.sql` | 21 | `CREATE_VIEW` | LOW |
| `04_merge_scd2.sql` | 24 | `MERGE` | LOW |

Function inventory extracted (top): `CURRENT_TIMESTAMP` ×3, `COUNT` ×2, `SUM` ×2,
`TO_VARCHAR` ×2, `DATEADD` ×2, and single calls to `FLATTEN`, `DATE_TRUNC`,
`LISTAGG`, `RANK`, `ROW_NUMBER`, `DIV0`, `TRY_CAST`.

The Snowflake-specific constructs I planted (`FLATTEN`, `DIV0`, `LISTAGG`,
`TRY_CAST`) were all detected — the analyzer's function census is working correctly.

> Note: `analyze` writes `.tmp` scratch files into the **report file's directory**
> (`out/`) during the run and cleans them up afterwards. Point `--report-file` at a
> writable scratch dir, not a shared location.

---

## Environment (final state)

| Component | Version | Location |
|---|---|---|
| Databricks CLI | 1.9.0 | `/opt/homebrew/bin/databricks` |
| Lakebridge | 0.14.2 | `~/.databricks/labs/lakebridge` |
| Bladebridge | 0.3.0 | `~/.databricks/labs/remorph-transpilers/bladebridge` |
| Morpheus | 0.9.0 | `~/.databricks/labs/remorph-transpilers/databricks-morph-plugin` |
| Java | OpenJDK 21.0.12 | `/opt/homebrew/opt/openjdk@21` |
| Labs venv Python | 3.12.13 | `~/.databricks/labs/lakebridge/state/venv` |
| CLI profile | `lakebridge-eval` | `~/.databrickscfg` (OAuth) |
| Lakebridge config | — | `/Workspace/Users/you@example.com/.lakebridge/config.yml` |

`~/.zshrc` gained `JAVA_HOME` + PATH entries for openjdk@21.

---

## Next Actions

1. ~~Install Rosetta 2 and re-run the Analyzer~~ — ✅ **done 2026-07-27 19:44.**
2. **You (decision):** approve `configure-reconcile` if you want the reconciler
   validated. It **creates** a UC catalog/schema + metadata tables — additive, but
   it does modify your workspace, so it stays gated until you say so.
3. **Optional:** start the Serverless Starter Warehouse to exercise transpile with
   validation enabled (`--skip-validation false`).
4. **Optional:** file Finding 2 upstream at `databrickslabs/lakebridge`.
