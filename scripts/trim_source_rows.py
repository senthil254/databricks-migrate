"""Cap every source table at 10 rows.

Why: a whole-schema Redshift batch over `public` was measured at 15 of 27 items
in ~25 minutes, entirely because it copies real rows from the TICKIT sample set.
Ten rows exercises exactly the same code path — real DDL, real data copy, real
COUNT(*) verification — in seconds.

THIS DELETES REAL DATA AND CANNOT BE UNDONE. Defaults to --dry-run for that
reason; pass --apply to actually run.

Scope is an ALLOWLIST, deliberately:

    Redshift  : schema `public` only
    Starburst : catalog `mcp2ohio` only

Starburst's federated_mysql / federated_postgres / federated_s3 catalogs are
federation connectors — a DELETE through them removes rows from the EXTERNAL
MySQL, Postgres and S3 systems behind them, not from Starburst. They are not
reachable from this script at all, and that is not an oversight.

Idempotent: a table already at <= 10 rows is skipped, so re-running does nothing.

    backend/.venv/bin/python scripts/trim_source_rows.py            # dry run
    backend/.venv/bin/python scripts/trim_source_rows.py --apply
"""
from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.connectors import redshift as rs  # noqa: E402
from app.connectors import starburst as sb  # noqa: E402

KEEP = 10

REDSHIFT_SCHEMAS = ("public",)          # allowlist
STARBURST_CATALOG = "mcp2ohio"          # allowlist


# ---------------------------------------------------------------- reporting
class Report:
    def __init__(self) -> None:
        self.trimmed: list[tuple[str, int, int]] = []
        self.skipped: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    def summary(self, dry: bool) -> int:
        verb = "would trim" if dry else "trimmed"
        print(f"\n{'='*66}")
        print(f"{verb}: {len(self.trimmed)}   skipped: {len(self.skipped)}   failed: {len(self.failed)}")
        for fq, before, after in self.trimmed:
            print(f"  {verb:10} {fq:52} {before} -> {after}")
        if self.failed:
            print("\nFAILED:")
            for fq, err in self.failed:
                print(f"  {fq}: {err}")
        return 1 if self.failed else 0


# ---------------------------------------------------------------- Redshift
def trim_redshift(rep: Report, dry: bool) -> None:
    print("=== Redshift ===")
    conn = rs._connect()
    try:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(REDSHIFT_SCHEMAS))
        cur.execute(
            f"""SELECT table_schema, table_name FROM information_schema.tables
                WHERE table_schema IN ({placeholders}) AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name""",
            REDSHIFT_SCHEMAS,
        )
        targets = cur.fetchall()

        for schema, table in targets:
            schema, table = rs._ident(schema), rs._ident(table)
            fq = f'"{schema}"."{table}"'
            label = f"redshift {schema}.{table}"
            cur.execute(f"SELECT COUNT(*) FROM {fq}")
            before = cur.fetchone()[0]
            if before <= KEEP:
                rep.skipped.append((label, f"already {before} rows"))
                print(f"  skip  {schema}.{table:34} {before} rows")
                continue
            if dry:
                rep.trimmed.append((label, before, KEEP))
                print(f"  DRY   {schema}.{table:34} {before} -> {KEEP}")
                continue
            try:
                # Replace contents, keep the table definition: a temp copy of the
                # rows to keep, delete all, put the copy back. DELETE ... LIMIT
                # does not exist in Redshift.
                cur.execute(f"DROP TABLE IF EXISTS _trim_keep")
                cur.execute(f"CREATE TEMP TABLE _trim_keep AS SELECT * FROM {fq} LIMIT {KEEP}")
                cur.execute(f"DELETE FROM {fq}")
                cur.execute(f"INSERT INTO {fq} SELECT * FROM _trim_keep")
                cur.execute("DROP TABLE _trim_keep")
                conn.commit()
                cur.execute(f"SELECT COUNT(*) FROM {fq}")
                after = cur.fetchone()[0]
                # 0 rows means the copy-back silently failed — that is a failure,
                # not a very successful trim.
                if after == 0 or after > KEEP:
                    rep.failed.append((label, f"ended at {after} rows (expected 1..{KEEP})"))
                    print(f"  FAIL  {schema}.{table:34} {before} -> {after}")
                else:
                    rep.trimmed.append((label, before, after))
                    print(f"  ok    {schema}.{table:34} {before} -> {after}")
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                rep.failed.append((label, str(exc)[:160]))
                print(f"  FAIL  {schema}.{table:34} {str(exc)[:80]}")
    finally:
        conn.close()


# ---------------------------------------------------------------- Starburst
def trim_starburst(rep: Report, dry: bool) -> None:
    print("\n=== Starburst ===")
    catalog = sb._ident(STARBURST_CATALOG)
    try:
        schemas = [s.name for s in sb.list_schemas(catalog) if s.name != "information_schema"]
    except Exception as exc:  # noqa: BLE001
        rep.failed.append((f"starburst {catalog}", str(exc)[:160]))
        return

    conn = sb._connect()
    try:
        cur = conn.cursor()
        for schema in schemas:
            if schema in ("system",):
                continue
            try:
                objs = sb.list_tables(catalog, schema)
            except Exception as exc:  # noqa: BLE001
                rep.failed.append((f"starburst {catalog}.{schema}", str(exc)[:160]))
                continue

            for o in objs:
                # Skip by TYPE, never by name — a view has no rows of its own.
                if getattr(o, "type", "table") != "table":
                    rep.skipped.append((f"{catalog}.{schema}.{o.name}", "view"))
                    continue
                name = sb._ident(o.name)
                sch = sb._ident(schema)
                fq = f'"{catalog}"."{sch}"."{name}"'
                label = f"starburst {catalog}.{schema}.{o.name}"
                cur.execute(f"SELECT COUNT(*) FROM {fq}")
                before = cur.fetchone()[0]
                if before <= KEEP:
                    rep.skipped.append((label, f"already {before} rows"))
                    print(f"  skip  {schema}.{o.name:34} {before} rows")
                    continue
                if dry:
                    rep.trimmed.append((label, before, KEEP))
                    print(f"  DRY   {schema}.{o.name:34} {before} -> {KEEP}")
                    continue

                after, err = _trim_trino_table(cur, catalog, sch, name, fq)
                if err:
                    rep.failed.append((label, err))
                    print(f"  FAIL  {schema}.{o.name:34} {err[:80]}")
                elif after == 0 or after > KEEP:
                    rep.failed.append((label, f"ended at {after} rows (expected 1..{KEEP})"))
                    print(f"  FAIL  {schema}.{o.name:34} {before} -> {after}")
                else:
                    rep.trimmed.append((label, before, after))
                    print(f"  ok    {schema}.{o.name:34} {before} -> {after}")
    finally:
        conn.close()


def _trim_trino_table(cur, catalog: str, schema: str, name: str, fq: str):
    """Returns (row_count_after, error_or_None).

    Trino's DELETE support is connector-dependent, so try the non-destructive
    path first and only fall back to recreating the table if the connector
    refuses it.
    """
    # Path 1 — DELETE the rows outside the first N, keyed on the first column.
    try:
        cur.execute(f"SELECT * FROM {fq} LIMIT 1")
        first_col = cur.description[0][0]
        col = sb._ident(first_col)
        cur.execute(
            f'DELETE FROM {fq} WHERE "{col}" NOT IN '
            f'(SELECT "{col}" FROM {fq} ORDER BY "{col}" LIMIT {KEEP})'
        )
        cur.fetchall()
        cur.execute(f"SELECT COUNT(*) FROM {fq}")
        after = cur.fetchone()[0]
        if after <= KEEP:
            return after, None
        # DELETE ran but duplicates in the key column left more than KEEP rows.
    except Exception as exc:  # noqa: BLE001
        delete_err = str(exc)[:120]
    else:
        delete_err = f"DELETE left {after} rows (duplicate key column?)"

    # Path 2 — recreate. More invasive, so only after DELETE has actually failed.
    tmp = f"{name}__trim_tmp"
    try:
        cur.execute(f'DROP TABLE IF EXISTS "{catalog}"."{schema}"."{tmp}"')
        cur.fetchall()
        cur.execute(f'CREATE TABLE "{catalog}"."{schema}"."{tmp}" AS SELECT * FROM {fq} LIMIT {KEEP}')
        cur.fetchall()
        cur.execute(f"DROP TABLE {fq}")
        cur.fetchall()
        cur.execute(f'ALTER TABLE "{catalog}"."{schema}"."{tmp}" RENAME TO "{name}"')
        cur.fetchall()
        cur.execute(f"SELECT COUNT(*) FROM {fq}")
        return cur.fetchone()[0], None
    except Exception as exc:  # noqa: BLE001
        return -1, f"DELETE failed ({delete_err}); recreate also failed: {str(exc)[:120]}"


def main() -> int:
    dry = "--apply" not in sys.argv
    print(f"Trim all source tables to <= {KEEP} rows   [{'DRY RUN' if dry else 'APPLYING'}]")
    print(f"Scope: redshift {list(REDSHIFT_SCHEMAS)}  |  starburst catalog '{STARBURST_CATALOG}'")
    if dry:
        print("(no changes will be made — pass --apply to execute)\n")
    rep = Report()
    trim_redshift(rep, dry)
    trim_starburst(rep, dry)
    return rep.summary(dry)


if __name__ == "__main__":
    raise SystemExit(main())
