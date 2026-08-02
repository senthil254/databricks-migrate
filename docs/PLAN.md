# Databricks Lakebridge — Evaluation & Validation Plan

**Date:** 2026-07-27
**Machine:** macOS 26.3.2, arm64 (Apple Silicon)
**Workspace:** `<old-workspace>.cloud.databricks.com` (org `7474645525776557`)
**Identity (via MCP):** you@example.com
**Primary source of truth:** https://databrickslabs.github.io/lakebridge/docs/installation/

---

## 1. Executive Summary

Lakebridge is a Databricks Labs toolkit for SQL/ETL migration, delivered as a
**Databricks CLI extension** (`databricks labs install lakebridge`). It has four
components:

| Component | Purpose | Touches workspace? |
|---|---|---|
| **Profiler** | Surveys source SQL estate, sizes/complexity, TCO estimate | No (local DuckDB) |
| **Analyzer** | Scans SQL/orchestration code for complexity & migration blockers | No (local report) |
| **Transpiler** | Converts source SQL → Databricks SQL (BladeBridge / Morpheus / Switch-LLM) | Only if validation enabled |
| **Reconciler** | Row/aggregate-level data validation source vs Databricks | Yes — creates UC tables |

**Objective of this exercise:** install, configure, and functionally validate
Lakebridge end-to-end using only read-only / non-destructive operations, with a
sample Snowflake→Databricks transpile as the functional proof.

**Verdict on feasibility:** Feasible. Three prerequisites are missing (Databricks
CLI, Java 21, a Python ≥3.10 on PATH) and all three are installable via Homebrew.
Authentication is not yet configured for the CLI (only the MCP server holds creds).

---

## 2. Environment Assessment

Measured on this machine, not assumed:

| Requirement | Required | Found | Status |
|---|---|---|---|
| OS / arch | — | macOS 26.3.2 / arm64 | ✅ |
| Python | 3.10.1 – 3.14.x | `/usr/bin/python3` = **3.9.6** (too old) | ⚠️ default too old |
| Python (alt) | — | Homebrew **3.14.6**; uv-managed **3.12.13**, **3.11.15** | ✅ usable |
| pip | — | 21.2.4 (bound to 3.9) | ⚠️ |
| uv | recommended | **0.11.29** | ✅ |
| Git | — | 2.53.0 | ✅ |
| **Java** | **21+** (Morpheus transpiler) | **not installed** | ❌ **BLOCKER** |
| **Databricks CLI** | required | **not installed** | ❌ **BLOCKER** |
| Homebrew | — | 6.0.10 | ✅ |
| Docker | not required | not installed | ➖ n/a |
| Terraform | not required | not installed | ➖ n/a |
| AWS CLI | not required by Lakebridge | 2.35.11 | ➖ |
| Azure CLI / gcloud | not required | not installed | ➖ n/a |
| Network to GitHub / Maven Central / PyPI | required | assumed OK, will verify | ⏳ |

### Workspace state (verified live via Databricks MCP, read-only)
- **Catalogs:** `dbacademy`, `demo_catalog`, `workspace`, `samples`, `system`
- **Metastore:** `metastore_aws_us_east_2` (AWS us-east-2)
- **Clusters:** **none** — workspace returns an empty cluster list
  → implies serverless-only (Free/Express edition). Any step needing a classic
  cluster will not work; transpile validation must use a SQL warehouse or be skipped.
- **CLI auth:** `~/.databrickscfg` **does not exist**; no `DATABRICKS_*` env vars in
  this shell. The MCP server authenticates out-of-band and its credentials are not
  reusable by the CLI.

---

## 3. Authentication Plan

Docs accept PAT or Service Principal. For an interactive single-user eval the
recommended and least-credential-exposing method is **OAuth U2M**:

```bash
databricks auth login --host https://<old-workspace>.cloud.databricks.com
```

This opens a browser, you approve, and the CLI stores an OAuth token — **no token
is ever typed into or visible to this session**. A PAT is the fallback if OAuth is
unavailable on this workspace tier.

> The browser approval step is yours to perform. I cannot complete an auth flow or
> handle a token on your behalf.

---

## 4. Dependency Matrix / Install Checklist

| # | Item | Method (official) | Non-destructive? |
|---|---|---|---|
| D1 | Databricks CLI | `brew tap databricks/tap && brew install databricks` | ✅ new install |
| D2 | Java 21 (Temurin) | `brew install --cask temurin@21` | ✅ new install |
| D3 | Python 3.12 on PATH for labs venv | `uv python install 3.12` (already present) | ✅ |
| D4 | CLI auth | `databricks auth login --host <host>` | ✅ (creates `~/.databrickscfg`) |
| D5 | Lakebridge | `databricks labs install lakebridge` | ⚠️ creates labs dir in workspace |
| D6 | Transpilers | `databricks labs lakebridge install-transpile` | ⚠️ downloads artifacts |
| D7 | Reconcile *(optional)* | `databricks labs lakebridge configure-reconcile` | ⚠️ **creates UC catalog/schema/tables** |

---

## 5. Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| **No clusters in workspace** — free tier, serverless only | High | Skip anything requiring a classic cluster; use `--skip-validation` on transpile; use SQL warehouse if one exists |
| `configure-reconcile` **creates UC catalog/schema/metadata tables** | Medium | **Gated — will not run without your explicit go-ahead.** Not needed for core validation |
| Java 21 install via cask needs `sudo` password | Medium | You run it; I cannot enter your password |
| Python 3.9 is the default `python3` — labs venv may pick the wrong interpreter | Medium | Verify which Python the labs venv resolved; force 3.12 if wrong |
| `databricks labs install` writes to the workspace `/Users/<you>/.lakebridge` dir | Low | Additive only, no existing resource touched |
| Morpheus/Switch pull from Maven Central + GitHub | Low | Verify network reachability first; proxy vars documented if needed |
| Token/secret leakage in logs | High | OAuth flow only; no token echoed; logs scrubbed |
| Version drift between docs and GitHub | Low | Docs are authoritative per instruction |

### Hard safety boundaries for this run
No `DROP`, no `DELETE`, no overwrite of existing catalogs/schemas/tables, no cluster
deletion, no destructive migration command. Every workspace-modifying step is either
purely additive or explicitly gated on your approval.

---

## 6. Execution Plan

Each step: purpose → command → expected → verify → rollback → est.

---

**Step 1 — Preflight: network reachability**
*Purpose:* confirm GitHub / Maven Central / PyPI are reachable before installs.
*Command:* HTTPS HEAD to `github.com`, `repo1.maven.org`, `pypi.org`
*Expected:* HTTP 200/301 from all three
*Verify:* exit codes 0
*Rollback:* n/a (read-only)
*Est:* <1 min

**Step 2 — Install Databricks CLI (D1)**
*Purpose:* Lakebridge is a CLI extension; nothing works without it.
*Command:* `brew tap databricks/tap && brew install databricks`
*Expected:* `databricks --version` prints `Databricks CLI v0.2xx.x`
*Verify:* `databricks --version` exits 0
*Rollback:* `brew uninstall databricks`
*Est:* 2–4 min

**Step 3 — Install Java 21 (D2)**
*Purpose:* required by the Morpheus transpiler.
*Command:* `brew install --cask temurin@21` *(may prompt for your password)*
*Expected:* `java -version` reports 21.x
*Verify:* `java -version` exits 0 and shows ≥21
*Rollback:* `brew uninstall --cask temurin@21`
*Est:* 3–5 min

**Step 4 — Authenticate CLI (D4)** ← *requires you*
*Purpose:* establish workspace identity for the CLI.
*Command:* `databricks auth login --host https://<old-workspace>.cloud.databricks.com`
*Expected:* browser opens, you approve, profile written to `~/.databrickscfg`
*Verify:* `databricks current-user me` returns you@example.com
*Rollback:* `databricks auth logout` / remove the profile
*Est:* 2 min

**Step 5 — Verify workspace access (read-only)**
*Purpose:* prove connectivity, identity, catalog and warehouse visibility.
*Command:* `databricks current-user me`, `databricks catalogs list`, `databricks warehouses list`, `databricks clusters list`
*Expected:* identity matches; 5 catalogs listed; cluster list empty (known)
*Verify:* all exit 0
*Rollback:* n/a
*Est:* 1 min

**Step 6 — Install Lakebridge (D5)**
*Purpose:* install the labs extension.
*Command:* `databricks labs install lakebridge`
*Expected:* venv created under `~/.databricks/labs/lakebridge`, deps resolved
*Verify:* `databricks labs lakebridge --help` lists subcommands
*Rollback:* `databricks labs uninstall lakebridge`
*Est:* 3–6 min

**Step 7 — Confirm the labs venv Python is ≥3.10**
*Purpose:* guard against the 3.9.6 default being picked.
*Command:* inspect `~/.databricks/labs/lakebridge/.venv/bin/python --version`
*Expected:* 3.10–3.14
*Verify:* version in range; if not, reinstall pinned to 3.12
*Rollback:* reinstall
*Est:* 1 min

**Step 8 — Version & capability check**
*Command:* `databricks labs lakebridge --help`, `describe-transpile`
*Expected:* subcommand list incl. analyze/transpile/reconcile; transpiler inventory
*Verify:* exit 0, non-empty output
*Est:* 1 min

**Step 9 — Install transpilers (D6)**
*Purpose:* fetch BladeBridge/Morpheus so `transpile` can run.
*Command:* `databricks labs lakebridge install-transpile`
*Expected:* artifacts downloaded; `describe-transpile` now lists installed transpilers
*Verify:* `describe-transpile` shows ≥1 transpiler
*Rollback:* remove the labs install dir / `databricks labs uninstall lakebridge`
*Est:* 3–8 min

**Step 10 — Create a sample Snowflake SQL corpus (local only)**
*Purpose:* give analyzer + transpiler real input; nothing proprietary.
*Command:* write 3–4 small Snowflake-dialect `.sql` files to `samples/snowflake/`
*Expected:* files on disk
*Verify:* `ls samples/snowflake/`
*Rollback:* delete the sample dir
*Est:* 1 min

**Step 11 — Run Analyzer (read-only, local)**
*Command:* `databricks labs lakebridge analyze --source-directory samples/snowflake --report-file out/analysis.xlsx --source-tech Snowflake`
*Expected:* report file produced
*Verify:* report exists and is non-empty
*Rollback:* delete report
*Est:* 1–3 min

**Step 12 — Run Transpile (local, validation skipped)**
*Command:* `databricks labs lakebridge transpile --input-source samples/snowflake --output-folder out/transpiled --source-dialect snowflake --skip-validation true --error-file-path out/errors.log`
*Expected:* Databricks-SQL output files in `out/transpiled/`
*Verify:* output files exist; diff reviewed; error log inspected
*Rollback:* delete `out/`
*Est:* 2–5 min

**Step 13 — Reconcile (GATED — not run by default)**
*Purpose:* would validate the reconciler, but `configure-reconcile` **creates UC
catalog/schema/metadata tables** in your workspace.
*Command:* `databricks labs lakebridge configure-reconcile`
*Decision:* **skipped unless you explicitly approve.** I will surface exactly what
it would create before running anything.

**Step 14 — Structured log + final report**
*Purpose:* deliverable.
*Output:* `logs/run-<ts>.jsonl` (timestamp, action, command, status, duration) and
`docs/RESULTS.md` with the validation checklist filled in from real evidence.

---

## 7. Verification Checklist

- [ ] Network to GitHub / Maven Central / PyPI reachable
- [ ] Databricks CLI installed, version captured
- [ ] Java 21+ installed, version captured
- [ ] CLI authenticated; `current-user me` matches expected identity
- [ ] Workspace reachable; catalogs enumerated; warehouse/cluster inventory captured
- [ ] Lakebridge installed; `--help` works
- [ ] Labs venv Python in supported range
- [ ] Transpilers installed; `describe-transpile` non-empty
- [ ] Analyzer produced a report on sample input
- [ ] Transpiler produced Databricks SQL output; errors reviewed
- [ ] Reconcile: **intentionally gated**, decision recorded
- [ ] Structured logs written
- [ ] No destructive operation performed

---

## 8. Steps Requiring You

1. **Step 3** — Homebrew cask install of Java may prompt for your macOS password.
2. **Step 4** — OAuth browser approval. I cannot authenticate on your behalf.
3. **Step 13** — Explicit approval if you want reconcile validated.

Everything else proceeds automatically.
