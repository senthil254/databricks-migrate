"""G3.2 — real migration execution.

Two genuinely separate mechanisms, per MEMORY.md's 2026-08-01 finding
(confirmed against the live CLI and Databricks' own docs):

1. DDL/code migration — via the real Lakebridge CLI. Deterministic
   `transpile` for Redshift (a real supported dialect); experimental,
   non-deterministic `llm-transpile` for Starburst (no deterministic
   transpiler exists for it). Every result records which `engine` produced
   it — the two must never look identical to a caller.
2. Table *data* migration — Lakebridge has no capability for this at all.
   Built here directly on the live source connectors (redshift.py /
   starburst.py) and the real Databricks SQL warehouse (databricks_target.py).
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

from . import databricks_target, starburst_ddl_translator, starburst_type_map
from .connectors import redshift as redshift_conn
from .connectors import starburst as starburst_conn
from .connectors.starburst import ConnectorError as StarburstError
from .executor import JOB_RUN_URL_RE as _JOB_RUN_URL_RE
from .executor import _databricks_binary, _subprocess_env, databricks_config, databricks_profile
from .executor import poll_job_run as _poll_job_run
from .models import (
    Batch,
    BatchStatus,
    Migration,
    MigrationEngine,
    RunStatus,
    batch_store,
    migration_store,
)
from .redact import redact, strip_ansi

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Lakebridge's llm-transpile staging area. The catalog follows the configured
# migration target (DATABRICKS_TARGET_CATALOG) so a workspace move doesn't
# leave this pointing at a catalog that only exists in the old workspace.
LLM_TRANSPILE_CATALOG = os.getenv("DATABRICKS_TARGET_CATALOG", "lakebridge_demo")
LLM_TRANSPILE_SCHEMA = "migration_lab"
LLM_TRANSPILE_VOLUME = "landing"
LLM_TRANSPILE_FOUNDATION_MODEL = "databricks-gpt-oss-120b"

# llm-transpile's --source-dialect is NOT free-form despite accepting
# arbitrary source SQL conceptually — it has its own fixed enum (confirmed
# live 2026-08-01), and "trino"/"starburst" is not in it:
#   airflow, custom_etl, informatica, mssql, mysql, netezza, oracle,
#   postgresql, pyspark, python, redshift, sas, scala, snowflake, synapse,
#   teradata, unknown_etl
# "postgresql" is used as the closest ANSI-SQL sibling — an approximation,
# not a real Trino dialect entry. Flagged as experimental in every response
# for exactly this reason.
LLM_TRANSPILE_SOURCE_DIALECT = "postgresql"


# Installed by `databricks labs lakebridge install-transpile`. Morpheus is the
# deterministic Redshift transpiler (Bladebridge is the LLM-assisted one);
# this project's Redshift path has always meant Morpheus.
_MORPHEUS_CONFIG = pathlib.Path.home() / (
    ".databricks/labs/remorph-transpilers/databricks-morph-plugin/lib/config.yml"
)


def _workspace_username() -> str:
    """The authenticated user's workspace home name, used to build
    `/Workspace/Users/<me>/...` paths. Resolved live rather than hardcoded so
    the app works in any workspace and for any identity."""
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(config=databricks_config()).current_user.me().user_name


def _morpheus_config_path() -> str:
    if not _MORPHEUS_CONFIG.exists():
        raise FileNotFoundError(
            f"Morpheus transpiler config not found at {_MORPHEUS_CONFIG}. "
            "Run `databricks labs lakebridge install-transpile`."
        )
    return str(_MORPHEUS_CONFIG)


def _run_lakebridge(argv_tail: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Runs a `databricks labs lakebridge ...` invocation directly (not via
    executor.run_command, which writes to the Run/Event store this module
    doesn't use) — same safety measures: argument array, JVM PATH fix."""
    # No profile configured -> omit `-p` and let the CLI authenticate from the
    # environment, the same rule executor.build_argv follows. See
    # executor.databricks_profile() for why empty means "no config file".
    profile = databricks_profile()
    argv = [_databricks_binary(), "labs", "lakebridge", *argv_tail]
    if profile:
        argv += ["-p", profile]
    proc = subprocess.run(
        argv, input="no\n", capture_output=True, text=True,
        timeout=timeout, env=_subprocess_env(),
    )
    return proc.returncode, strip_ansi(proc.stdout), strip_ansi(proc.stderr)


def _already_migrated(
    source_system: str,
    object_type: str,
    schema: str,
    name: str,
    catalog: str | None = None,
    engine: MigrationEngine | None = None,
) -> Migration | None:
    """G19 — if the object is already in the target, say so instead of doing the
    work again. Re-reading the source and re-transpiling costs ~12s and ends in
    a CREATE OR REPLACE that changes nothing.

    Returns a COMPLETED Migration recording that no action was taken, or None if
    the object isn't there. Callers pass force=True to migrate anyway (e.g. the
    source definition changed).
    """
    target = databricks_target.target_object_name(source_system, schema, name, catalog)
    if not databricks_target.object_exists(target):
        return None
    # The engine must be the one the CALLER would have used. Deriving it from
    # source_system alone mislabelled every short-circuited llm-transpile
    # migration as starburst-custom-ddl — i.e. the record claimed a different
    # engine ran than the endpoint the user actually called.
    if engine is None:
        engine = (
            MigrationEngine.LAKEBRIDGE_TRANSPILE
            if source_system == "redshift"
            else MigrationEngine.STARBURST_CUSTOM_DDL
        )
    qualified = f"{catalog}.{schema}.{name}" if catalog else f"{schema}.{name}"
    mig = migration_store.create(source_system, object_type, qualified, engine)
    migration_store.update(
        mig.id,
        status=RunStatus.COMPLETED,
        output_ddl=(
            f"-- ALREADY MIGRATED: {databricks_target.TARGET_CATALOG}."
            f"{databricks_target.TARGET_SCHEMA}.{target} already exists.\n"
            "-- No action taken. Re-run with force=true to migrate it again."
        ),
        target_catalog=databricks_target.TARGET_CATALOG,
        target_schema=databricks_target.TARGET_SCHEMA,
        target_table=target if object_type in ("table", "view") else None,
        started=True,
        ended=True,
    )
    return migration_store.get(mig.id)


def migrate_redshift_ddl(object_type: str, schema: str, name: str, force: bool = False) -> Migration:
    """object_type: 'table' | 'view' | 'function' | 'procedure'."""
    if not force:
        existing = _already_migrated("redshift", object_type, schema, name)
        if existing is not None:
            return existing
    mig = migration_store.create("redshift", object_type, f"{schema}.{name}", MigrationEngine.LAKEBRIDGE_TRANSPILE)
    migration_store.update(mig.id, status=RunStatus.RUNNING, started=True)
    try:
        if object_type in ("table", "view"):
            ddl = redshift_conn.get_table_ddl(schema, name)
        elif object_type == "procedure":
            ddl = redshift_conn.get_procedure_ddl(schema, name)
        elif object_type == "function":
            ddl = redshift_conn.get_function_ddl(schema, name)
        else:
            raise ValueError(f"unsupported object_type: {object_type}")
        migration_store.update(mig.id, source_ddl=ddl)
    except Exception as exc:  # noqa: BLE001
        migration_store.update(mig.id, status=RunStatus.FAILED, error=redact(str(exc)), ended=True)
        return migration_store.get(mig.id)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()
        (input_dir / f"{name}.sql").write_text(ddl)

        rc, stdout, stderr = _run_lakebridge([
            "transpile",
            "--input-source", str(input_dir),
            "--output-folder", str(output_dir),
            "--source-dialect", "redshift",
            "--skip-validation", "true",
            # Name the transpiler explicitly. Redshift is claimed by BOTH
            # Morpheus and Bladebridge, so when the workspace has no saved
            # `.lakebridge/config.yml` the CLI prompts "Select the transpiler:"
            # — an interactive prompt in a server process, which dies with
            # `EOFError: EOF when reading a line`. Discovered moving to a fresh
            # workspace (the old one had the config, so the prompt never fired).
            # Passing the path makes the run deterministic and independent of
            # workspace-side state.
            "--transpiler-config-path", _morpheus_config_path(),
        ])

        output_file = output_dir / f"{name}.sql"
        if rc == 0 and output_file.exists():
            output_ddl = output_file.read_text()
            _apply_ddl_to_target(mig.id, "redshift", object_type, schema, name, output_ddl)
        else:
            migration_store.update(
                mig.id, status=RunStatus.FAILED,
                error=redact((stderr or stdout or "transpile produced no output")[:2000]), ended=True,
            )
    return migration_store.get(mig.id)


def _apply_ddl_to_target(
    migration_id: str,
    source_system: str,
    object_type: str,
    schema: str,
    name: str,
    output_ddl: str,
    catalog: str | None = None,
) -> None:
    """G19 — run the transpiled DDL against Databricks so `migrate` actually
    creates the object, rather than only producing converted SQL text.

    Honesty contract: a transpile that succeeds but whose output the warehouse
    rejects is a FAILED migration carrying the real engine error. Reporting
    "completed" because the *text* was produced, while nothing exists in the
    target, is precisely the kind of hollow success this project forbids — and
    it is how the user discovers which object types Databricks genuinely
    supports, instead of us guessing on their behalf.
    """
    # Views are deliberately NOT executed. A view's body references its source
    # tables by their source-qualified names (e.g. mcp2ohio.test_writes.products),
    # which do not exist in Databricks — migrated tables land under the flat
    # `{system}_{schema}_{name}` convention, so the reference cannot resolve.
    # Verified against the live warehouse: TABLE_OR_VIEW_NOT_FOUND. Creating
    # views would need the body rewritten to the migrated names AND every
    # referenced table migrated first; until that exists, we say so plainly
    # rather than emit a guaranteed failure on every view.
    if object_type == "view":
        migration_store.update(
            migration_id,
            status=RunStatus.COMPLETED,
            output_ddl=(
                f"{output_ddl}\n\n-- NOT created in Databricks: a view body references its source "
                "tables by their original names, which don't exist in the target. Migrate the "
                "referenced tables first and create the view from this SQL by hand."
            ),
            ended=True,
        )
        return

    try:
        fq = databricks_target.create_object_from_ddl(output_ddl, source_system, schema, name, catalog)
    except Exception as exc:  # noqa: BLE001
        migration_store.update(
            migration_id,
            status=RunStatus.FAILED,
            output_ddl=output_ddl,
            error=redact(
                f"transpiled successfully, but creating the object in Databricks failed: {exc}"
            ),
            ended=True,
        )
        return

    migration_store.update(
        migration_id,
        status=RunStatus.COMPLETED,
        output_ddl=f"{output_ddl}\n\n-- created in Databricks as: {fq}",
        target_catalog=databricks_target.TARGET_CATALOG,
        target_schema=databricks_target.TARGET_SCHEMA,
        target_table=databricks_target.target_object_name(source_system, schema, name, catalog)
        if object_type in ("table", "view")
        else None,
        ended=True,
    )


def migrate_starburst_ddl(
    object_type: str, catalog: str, schema: str, name: str, force: bool = False
) -> Migration:
    """Experimental path — llm-transpile. object_type: 'table' | 'view'.
    UDF *logic* migration isn't attempted here: Trino's SHOW FUNCTIONS only
    exposes a UDF's signature, not its body (see connectors/starburst.py's
    get_udf_ddl docstring) — there is no real source to transpile.

    Two real defects found and worked around while building this (2026-08-01,
    not hidden — see MEMORY.md):
    1. llm-transpile's --source-dialect has its own fixed enum; "trino" is
       not a member. LLM_TRANSPILE_SOURCE_DIALECT documents the approximation
       used instead.
    2. llm-transpile's own CLI exits 0 even when it printed a real ERROR to
       stderr and did nothing (confirmed live: invalid dialect value still
       returned exit code 0). Success here is judged by the actual dispatched
       job's real terminal result_state, not the CLI's exit code alone —
       and stderr is also checked for an ERROR marker before even trusting
       that a job was dispatched at all.
    """
    # G20: this path had no already-migrated check at all, so it dispatched a
    # real (slow, LLM-backed) Databricks job every time even when the object was
    # already in the target.
    if not force:
        existing = _already_migrated(
            "starburst", object_type, schema, name, catalog,
            engine=MigrationEngine.LLM_TRANSPILE_EXPERIMENTAL,
        )
        if existing is not None:
            return existing
    mig = migration_store.create("starburst", object_type, f"{catalog}.{schema}.{name}", MigrationEngine.LLM_TRANSPILE_EXPERIMENTAL)
    migration_store.update(mig.id, status=RunStatus.RUNNING, started=True)
    try:
        ddl = starburst_conn.get_table_ddl(catalog, schema, name)
        migration_store.update(mig.id, source_ddl=ddl)
    except Exception as exc:  # noqa: BLE001
        migration_store.update(mig.id, status=RunStatus.FAILED, error=redact(str(exc)), ended=True)
        return migration_store.get(mig.id)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        (input_dir / f"{name}.sql").write_text(ddl)
        # Was hardcoded to one specific user's workspace home, which cannot
        # exist in any other workspace (or for any other user). Resolved from
        # the authenticated identity instead, with the old value only as a
        # last-resort fallback so behaviour never silently changes to "no path".
        ws_folder = f"/Workspace/Users/{_workspace_username()}/.lakebridge/g3_llm_transpile_out/{name}"

        rc, stdout, stderr = _run_lakebridge([
            "llm-transpile",
            "--accept-terms", "true",
            "--input-source", str(input_dir),
            "--output-ws-folder", ws_folder,
            "--source-dialect", LLM_TRANSPILE_SOURCE_DIALECT,
            "--catalog-name", LLM_TRANSPILE_CATALOG,
            "--schema-name", LLM_TRANSPILE_SCHEMA,
            "--volume", LLM_TRANSPILE_VOLUME,
            "--foundation-model", LLM_TRANSPILE_FOUNDATION_MODEL,
        ], timeout=60)

        # rc == 0 is NOT trusted alone — see docstring point 2.
        if "ERROR" in stderr:
            migration_store.update(
                mig.id, status=RunStatus.FAILED,
                error=redact(stderr[:2000]), ended=True,
            )
            return migration_store.get(mig.id)

        run_id_match = _JOB_RUN_URL_RE.search(stdout + stderr)
        if not run_id_match:
            migration_store.update(
                mig.id, status=RunStatus.FAILED,
                error=redact("no job run URL found in llm-transpile output; cannot verify real completion: "
                              + (stderr or stdout)[:1000]),
                ended=True,
            )
            return migration_store.get(mig.id)

        run_id = run_id_match.group(1)
        lifecycle, result = _poll_job_run(run_id)

        if lifecycle == "TERMINATED" and result == "SUCCESS":
            migration_store.update(
                mig.id, status=RunStatus.COMPLETED,
                output_ddl=f"(job {run_id} SUCCESS — real converted SQL written to workspace: {ws_folder})",
                ended=True,
            )
        else:
            migration_store.update(
                mig.id, status=RunStatus.FAILED,
                error=redact(f"Switch job {run_id} ended with lifecycle={lifecycle} result={result}"),
                ended=True,
            )
    return migration_store.get(mig.id)


def copy_redshift_table_data(
    schema: str, table: str, preexisting: bool | None = None
) -> Migration:
    """The genuinely separate data-copy path — no Lakebridge command is
    involved at any point here.

    G5 security fix (2026-08-01, backend security review): `schema`/`table`
    here come directly from the URL path of `POST
    /migrate/redshift/data/{schema}/{table}` — unlike get_table_ddl/
    get_procedure_ddl (which already ran `redshift_conn._ident()` before
    interpolating into a `SHOW ...` statement), this function previously
    interpolated them unvalidated into both a real Redshift `SELECT ... FROM
    "{schema}"."{table}"` string (schema/table SQL injection into the
    *source* system) and a Databricks target table name subsequently used
    unvalidated in `DROP TABLE IF EXISTS`/`CREATE TABLE` statements
    (injection into the *target* warehouse). Neither had any guard. Fixed by
    reusing the same `_ident()` alnum(+underscore) check the DDL paths
    already rely on, applied before either identifier is interpolated
    anywhere. A caller passing a non-identifier-shaped schema/table now gets
    a normal FAILED migration (ConnectorError caught below), the same
    failure shape already used for e.g. "function not found" — not a 500,
    not a silently-accepted injection.
    """
    mig = migration_store.create("redshift", "table-data", f"{schema}.{table}", MigrationEngine.DATA_COPY)
    migration_store.update(mig.id, status=RunStatus.RUNNING, started=True)
    try:
        schema = redshift_conn._ident(schema)
        table = redshift_conn._ident(table)

        columns = redshift_conn.list_columns(schema, table)
        # A table that doesn't exist returns zero columns, which used to build
        # the invalid `SELECT  FROM "s"."t"` and surface as a Redshift *syntax*
        # error — telling the user nothing about the actual problem. Fail with
        # the real reason instead. (Seen in a batch: the DDL item correctly said
        # 'relation does not exist' while its data item said 'syntax error'.)
        if not columns:
            raise redshift_conn.ConnectorError(
                f'relation "{schema}.{table}" does not exist, or has no columns readable '
                f"by this user — nothing to copy"
            )
        col_specs = [(c.name, c.data_type) for c in columns]

        conn = redshift_conn._connect()
        try:
            cur = conn.cursor()
            col_list_sql = ", ".join(f'"{redshift_conn._ident(c.name)}"' for c in columns)
            cur.execute(f'SELECT {col_list_sql} FROM "{schema}"."{table}"')
            rows = cur.fetchall()
        finally:
            conn.close()

        target_table_name = f"redshift_{schema}_{table}"
        # G20: a copy is a full refresh (create_target_table does DROP+CREATE),
        # so an existing target is NOT a reason to skip — skipping would leave
        # stale rows, which is the opposite of what a copy is for. We record
        # that it already existed so the UI can say so, and refresh it anyway.
        # `preexisting` is supplied by migrate_and_copy_*, which checked BEFORE
        # its own DDL step ran. Without it, a first-ever table-and-data
        # migration reports "ALREADY MIGRATED" against the table its own DDL
        # half created moments earlier — verified against a confirmed-absent
        # target, so this was a real mis-report, not a theoretical one.
        already_existed = (
            databricks_target.object_exists(target_table_name)
            if preexisting is None
            else preexisting
        )
        fq = databricks_target.create_target_table(target_table_name, col_specs)
        inserted = databricks_target.insert_rows(fq, [c.name for c in columns], [tuple(r) for r in rows])

        verify_rows = databricks_target.execute(f"SELECT COUNT(*) FROM {fq}")
        target_count = verify_rows[0][0] if verify_rows else -1

        migration_store.update(
            mig.id, status=RunStatus.COMPLETED, row_count=inserted,
            output_ddl=(
                ("-- ALREADY MIGRATED (rows refreshed): the target already existed and was replaced.\n"
                 if already_existed else "")
                + f"target table: {fq}\nsource rows read: {len(rows)}\n"
                f"target rows after insert (verified via SELECT COUNT(*)): {target_count}"
            ),
            target_catalog=databricks_target.TARGET_CATALOG,
            target_schema=databricks_target.TARGET_SCHEMA,
            target_table=target_table_name,
            ended=True,
        )
    except Exception as exc:  # noqa: BLE001
        migration_store.update(mig.id, status=RunStatus.FAILED, error=redact(str(exc)), ended=True)
    return migration_store.get(mig.id)


# ---------------------------------------------------------------- G15
# Thin sequential wrappers: drag-drop of a table/view should create the
# destination object *and* copy its data in one motion (no separate "copy
# data" step), per G15 Phase A. Not new architecture — this is exactly the
# same DDL-then-data sequence `run_batch`'s include_data path already runs
# (see build_redshift_schema_batch_items / run_starburst_schema_batch
# above), just exposed as one call instead of two batch items. Reuses the
# existing DDL and data-copy functions verbatim; no new Lakebridge
# invocation shape, no new Migration fields.


def migrate_and_copy_redshift_table(schema: str, name: str, object_type: str = "table") -> Migration:
    """table/view only (object_type in {"table", "view"} — validated by the
    calling route; this function trusts its caller the same way
    migrate_redshift_ddl already does). Runs migrate_redshift_ddl, then —
    only if that succeeded — copy_redshift_table_data. If DDL fails,
    returns the DDL failure and never attempts the data copy. If DDL
    succeeds but the data copy fails, returns the data-copy Migration
    record, which itself always carries its own real error — the DDL's own
    (separate, already-completed) Migration record is left in
    migration_store exactly as migrate_redshift_ddl produced it, so its
    success is never discarded, just not the record returned to this call's
    caller."""
    # Check BEFORE the DDL step: afterwards the target always exists, so the
    # copy half could never distinguish "already migrated" from "just created".
    preexisting = databricks_target.object_exists(f"redshift_{schema}_{name}")
    ddl_mig = migrate_redshift_ddl(object_type, schema, name)
    if ddl_mig.status != RunStatus.COMPLETED:
        return ddl_mig
    return copy_redshift_table_data(schema, name, preexisting=preexisting)


def migrate_and_copy_starburst_table(catalog: str, schema: str, name: str, object_type: str = "table") -> Migration:
    """Same pattern as migrate_and_copy_redshift_table, using G7's fast
    deterministic Starburst DDL path (migrate_starburst_ddl_custom) and
    copy_starburst_table_data — not the experimental llm-transpile path."""
    # See migrate_and_copy_redshift_table — must be sampled before the DDL step.
    preexisting = databricks_target.object_exists(f"starburst_{catalog}_{schema}_{name}")
    ddl_mig = migrate_starburst_ddl_custom(object_type, catalog, schema, name)
    if ddl_mig.status != RunStatus.COMPLETED:
        return ddl_mig
    return copy_starburst_table_data(catalog, schema, name, preexisting=preexisting)


# ---------------------------------------------------------------- G7
# Custom, deterministic Starburst pipeline — genuinely separate from
# migrate_starburst_ddl above (the llm-transpile path, untouched, still
# fully live). No Lakebridge CLI invocation, no LLM job, anywhere below —
# see starburst_ddl_translator.py's module docstring for how that's
# verified by construction, not just by convention.


def migrate_starburst_ddl_custom(
    object_type: str, catalog: str, schema: str, name: str, force: bool = False
) -> Migration:
    """object_type: 'table' | 'view'. Same real-source, real-verification
    Migration lifecycle as migrate_starburst_ddl, but delegates to the
    pure-Python starburst_ddl_translator instead of dispatching any
    Databricks-managed conversion/LLM job — this is the fast, deterministic
    sibling path (MigrationEngine.STARBURST_CUSTOM_DDL), not a replacement
    for the experimental one."""
    if not force:
        existing = _already_migrated("starburst", object_type, schema, name, catalog)
        if existing is not None:
            return existing
    mig = migration_store.create(
        "starburst", object_type, f"{catalog}.{schema}.{name}", MigrationEngine.STARBURST_CUSTOM_DDL
    )
    migration_store.update(mig.id, status=RunStatus.RUNNING, started=True)
    try:
        if object_type == "table":
            source_ddl = starburst_conn.get_table_ddl(catalog, schema, name)
            migration_store.update(mig.id, source_ddl=source_ddl)
            output_ddl, _columns = starburst_ddl_translator.translate_table_ddl(catalog, schema, name)
        elif object_type == "view":
            source_ddl = starburst_conn.get_view_ddl(catalog, schema, name)
            migration_store.update(mig.id, source_ddl=source_ddl)
            output_ddl = starburst_ddl_translator.translate_view_ddl(catalog, schema, name)
        else:
            raise ValueError(f"unsupported object_type: {object_type}")

        # G19: same as the Redshift path — actually create the object, don't
        # stop at producing text. Starburst's schema name is used for the flat
        # target name so it stays consistent with copy_starburst_table_data.
        _apply_ddl_to_target(mig.id, "starburst", object_type, schema, name, output_ddl, catalog=catalog)
    except Exception as exc:  # noqa: BLE001
        migration_store.update(mig.id, status=RunStatus.FAILED, error=redact(str(exc)), ended=True)
    return migration_store.get(mig.id)


def copy_starburst_table_data(
    catalog: str, schema: str, table: str, preexisting: bool | None = None
) -> Migration:
    """Exact mirror of copy_redshift_table_data's real structure and G5
    identifier-guard fix — see that function's docstring for the full
    injection-hardening rationale, applied here from the start rather than
    as a later patch. Target table name: starburst_{catalog}_{schema}_{table}."""
    mig = migration_store.create("starburst", "table-data", f"{catalog}.{schema}.{table}", MigrationEngine.DATA_COPY)
    migration_store.update(mig.id, status=RunStatus.RUNNING, started=True)
    try:
        catalog = starburst_conn._ident(catalog)
        schema = starburst_conn._ident(schema)
        table = starburst_conn._ident(table)

        columns = starburst_conn.list_columns(catalog, schema, table)
        col_specs = [(c.name, c.data_type) for c in columns]
        col_names = [starburst_conn._ident(c.name) for c in columns]

        rows = starburst_conn.read_table_rows(catalog, schema, table, col_names)

        target_table_name = f"starburst_{catalog}_{schema}_{table}"
        # See copy_redshift_table_data — warn, then refresh; `preexisting` is
        # sampled by the caller before its DDL step for the same reason.
        already_existed = (
            databricks_target.object_exists(target_table_name)
            if preexisting is None
            else preexisting
        )
        fq = databricks_target.create_target_table(
            target_table_name, col_specs, type_mapper=starburst_type_map.databricks_type_for_trino
        )
        inserted = databricks_target.insert_rows(fq, col_names, rows)

        verify_rows = databricks_target.execute(f"SELECT COUNT(*) FROM {fq}")
        target_count = verify_rows[0][0] if verify_rows else -1

        migration_store.update(
            mig.id, status=RunStatus.COMPLETED, row_count=inserted,
            output_ddl=(
                ("-- ALREADY MIGRATED (rows refreshed): the target already existed and was replaced.\n"
                 if already_existed else "")
                + f"target table: {fq}\nsource rows read: {len(rows)}\n"
                f"target rows after insert (verified via SELECT COUNT(*)): {target_count}"
            ),
            target_catalog=databricks_target.TARGET_CATALOG,
            target_schema=databricks_target.TARGET_SCHEMA,
            target_table=target_table_name,
            ended=True,
        )
    except Exception as exc:  # noqa: BLE001
        migration_store.update(mig.id, status=RunStatus.FAILED, error=redact(str(exc)), ended=True)
    return migration_store.get(mig.id)


# ---------------------------------------------------------------- G3.4
# Batch/whole-schema migration — pure orchestration over the three real
# functions above. No new Lakebridge invocation shape is introduced here;
# a batch is just "run N of the existing real per-object migrations,
# sequentially, without letting one failure stop the rest."


def build_redshift_schema_batch_items(schema: str, include_data: bool = False) -> list[dict]:
    """Enumerates REAL objects in a Redshift schema via the existing
    connector (never a hardcoded list) and builds the item specs
    `run_batch` will execute. include_data=True additionally queues a
    real data-copy for every real base table (not views — copying a
    view's *definition* is already covered by the DDL item; a view has no
    rows of its own to copy)."""
    items: list[dict] = []
    for t in redshift_conn.list_tables(schema):
        items.append({"source_system": "redshift", "object_type": t.type, "schema": schema, "name": t.name})
        if include_data and t.type == "table":
            items.append({"source_system": "redshift", "object_type": "table-data", "schema": schema, "name": t.name})
    for r in redshift_conn.list_routines(schema):
        object_type = "function" if r.type == "FUNCTION" else "procedure"
        items.append({"source_system": "redshift", "object_type": object_type, "schema": schema, "name": r.name})
    return items


def _run_single_batch_item(item: dict) -> Migration:
    """Dispatches one batch item spec to the correct existing real
    migration function — no logic duplicated from migrate_redshift_ddl /
    migrate_starburst_ddl / copy_redshift_table_data above."""
    source_system = item["source_system"]
    object_type = item["object_type"]
    if source_system == "redshift":
        if object_type == "table-data":
            return copy_redshift_table_data(item["schema"], item["name"])
        return migrate_redshift_ddl(object_type, item["schema"], item["name"])
    if source_system == "starburst":
        if object_type == "table-data":
            return copy_starburst_table_data(item["catalog"], item["schema"], item["name"])
        # G19: was migrate_starburst_ddl (the experimental llm-transpile path),
        # which is the slow, error-prone one — a batch of it took minutes per
        # item. Batches now use the same deterministic path the single-object
        # "migrate" button uses.
        return migrate_starburst_ddl_custom(object_type, item["catalog"], item["schema"], item["name"])
    raise ValueError(f"unsupported source_system: {source_system}")


def expand_batch_items(items: list[dict], include_data: bool) -> list[dict]:
    """G19 — batch select mode used to migrate DDL only, so selecting tables
    produced converted SQL and no rows. Each real base table now also gets a
    `table-data` item, matching what drag-and-drop does for a single object.

    Views are deliberately excluded: their rows are a query result, not stored
    data, and the data-copy path targets base tables. Functions and procedures
    have no rows at all — they get their DDL created and nothing else.
    """
    if not include_data:
        return list(items)
    expanded: list[dict] = []
    for item in items:
        expanded.append(item)
        if item.get("object_type") == "table":
            expanded.append({**item, "object_type": "table-data"})
    return expanded


def run_batch(batch_id: str, items: list[dict]) -> None:
    """Runs every item in `items` sequentially, reusing the real
    per-object migration functions, and never aborts the remaining items
    because one failed — the whole point of G3.4's "don't hide a partial
    failure" requirement. Meant to run on a background thread (see
    main.py's batch endpoints), matching the existing dispatch-then-poll
    shape already used for reconcile/llm-transpile rather than blocking
    the triggering HTTP request."""
    batch_store.set_status(batch_id, BatchStatus.RUNNING, started=True)
    any_failed = False
    for item in items:
        try:
            mig = _run_single_batch_item(item)
            if mig is None or mig.status == RunStatus.FAILED:
                any_failed = True
        except Exception as exc:  # noqa: BLE001 — one bad item must not kill the batch
            any_failed = True
            engine = (
                MigrationEngine.DATA_COPY
                if item.get("object_type") == "table-data"
                else MigrationEngine.LAKEBRIDGE_TRANSPILE
                if item.get("source_system") == "redshift"
                else MigrationEngine.LLM_TRANSPILE_EXPERIMENTAL
            )
            mig = migration_store.create(
                item.get("source_system", "unknown"),
                item.get("object_type", "unknown"),
                f"{item.get('schema', '?')}.{item.get('name', '?')}",
                engine,
            )
            migration_store.update(
                mig.id, status=RunStatus.FAILED, error=redact(str(exc)), started=True, ended=True,
            )
        batch_store.add_migration(batch_id, mig.id)

    final_status = BatchStatus.COMPLETED_WITH_ERRORS if any_failed else BatchStatus.COMPLETED
    batch_store.set_status(batch_id, final_status, ended=True)


def start_batch(items: list[dict]) -> Batch:
    """Creates the Batch record and dispatches `run_batch` on a daemon
    background thread, returning immediately — same async-dispatch shape
    `executor.run_command_async` already uses for /runs/* (see
    executor.py), not a new mechanism."""
    import threading

    batch = batch_store.create(len(items))
    thread = threading.Thread(target=run_batch, args=(batch.id, items), daemon=True)
    thread.start()
    return batch


# ---------------------------------------------------------------- G9 / relocated from chat.py (G8)
# Starburst whole-schema batch. Deliberately NOT built on top of
# run_batch/start_batch above: `_run_single_batch_item` dispatches Starburst
# DDL items to the OLD `migrate_starburst_ddl` (llm-transpile) path, not
# G7's fast deterministic path. Reusing run_batch/start_batch here would
# silently reintroduce exactly what G7 was built to avoid. This is a
# small, self-contained mirror of run_batch/start_batch's orchestration
# shape, built only from real store objects (batch_store, migration_store)
# and G7's two custom functions (migrate_starburst_ddl_custom,
# copy_starburst_table_data). Originally written in chat.py for G8's
# batch-migrate-schema chat intent; moved here in G9 so the new
# `POST /migrate/starburst/catalog/{catalog}/schema/{schema}/batch` REST
# route in main.py can call the exact same code chat.py already exercises
# — not a second implementation.

def run_starburst_schema_batch(batch_id: str, catalog: str, schema: str, include_data: bool) -> None:
    """Self-contained mirror of `run_batch`'s orchestration shape
    (sequential, one failure never aborts the rest), built only from real
    store objects and G7's custom fast-path functions — see this
    section's header comment for why `start_batch`/`run_batch` is NOT
    reused here."""
    batch_store.set_status(batch_id, BatchStatus.RUNNING, started=True)
    any_failed = False
    try:
        tables = starburst_conn.list_tables(catalog, schema)
    except StarburstError:
        batch_store.set_status(batch_id, BatchStatus.COMPLETED_WITH_ERRORS, ended=True)
        return

    for t in tables:
        try:
            mig = migrate_starburst_ddl_custom(t.type, catalog, schema, t.name)
        except Exception as exc:  # noqa: BLE001 -- one bad item must not kill the batch
            any_failed = True
            mig = migration_store.create(
                "starburst", t.type, f"{catalog}.{schema}.{t.name}", MigrationEngine.STARBURST_CUSTOM_DDL
            )
            migration_store.update(
                mig.id, status=RunStatus.FAILED, error=redact(str(exc)), started=True, ended=True
            )
        if mig is None or mig.status == RunStatus.FAILED:
            any_failed = True
        batch_store.add_migration(batch_id, mig.id)

        if include_data and t.type == "table":
            try:
                data_mig = copy_starburst_table_data(catalog, schema, t.name)
            except Exception as exc:  # noqa: BLE001
                any_failed = True
                data_mig = migration_store.create(
                    "starburst", "table-data", f"{catalog}.{schema}.{t.name}", MigrationEngine.DATA_COPY
                )
                migration_store.update(
                    data_mig.id, status=RunStatus.FAILED, error=redact(str(exc)), started=True, ended=True
                )
            if data_mig is None or data_mig.status == RunStatus.FAILED:
                any_failed = True
            batch_store.add_migration(batch_id, data_mig.id)

    final_status = BatchStatus.COMPLETED_WITH_ERRORS if any_failed else BatchStatus.COMPLETED
    batch_store.set_status(batch_id, final_status, ended=True)


def start_starburst_schema_batch(catalog: str, schema: str, include_data: bool) -> Batch:
    """Same async-dispatch shape as `start_batch` (real Batch record
    created synchronously, real work runs on a daemon background thread)."""
    import threading

    tables = starburst_conn.list_tables(catalog, schema)
    expected = len(tables) + (sum(1 for t in tables if t.type == "table") if include_data else 0)
    batch = batch_store.create(expected)
    thread = threading.Thread(
        target=run_starburst_schema_batch, args=(batch.id, catalog, schema, include_data), daemon=True
    )
    thread.start()
    return batch
