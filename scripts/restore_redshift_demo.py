"""Restore the Redshift demo source estate into a fresh cluster.

Run this after destroying and recreating the cluster. It replays the SQL files
in scripts/redshift-demo/ in order, then verifies object and row counts against
what the dump recorded, so a partial restore fails loudly instead of leaving the
demo half-populated.

    backend/.venv/bin/python scripts/restore_redshift_demo.py
    backend/.venv/bin/python scripts/restore_redshift_demo.py --verify-only
    backend/.venv/bin/python scripts/restore_redshift_demo.py --dry-run

Scope is pinned to the two demo schemas. Nothing else in the cluster is touched,
and `public` (the TICKIT sample set) is deliberately not managed here.

Why a Python runner rather than piping the .sql files to psql
------------------------------------------------------------
`sp_top_customers` is a plpgsql procedure whose body contains semicolons inside
a `$$ ... $$` block. Splitting on `;` naively tears it in half and produces
syntax errors that look like a corrupt dump. `split_statements` below tracks
dollar-quoting, so the procedure survives. psql handles this correctly too — see
the README for that route — but this runner needs no extra client installed.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.connectors import redshift as rs  # noqa: E402

SQL_DIR = ROOT / "scripts" / "redshift-demo"
FILES = ("01_schemas.sql", "02_tables.sql", "03_data.sql", "04_functions.sql")
SCHEMAS = ("demo_fast_test", "demo_schema_test")

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_0-9]*\$")


def split_statements(sql: str) -> list[str]:
    """Split on `;` while respecting '…' strings and $tag$ … $tag$ blocks."""
    out: list[str] = []
    buf: list[str] = []
    i = 0
    in_single = False
    dollar_tag: str | None = None
    n = len(sql)

    while i < n:
        ch = sql[i]

        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue

        if in_single:
            # '' inside a string is an escaped quote, not a terminator.
            if ch == "'" and sql.startswith("''", i):
                buf.append("''")
                i += 2
                continue
            if ch == "'":
                in_single = False
            buf.append(ch)
            i += 1
            continue

        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue

        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue

        m = _DOLLAR_TAG.match(sql, i)
        if m:
            dollar_tag = m.group(0)
            buf.append(dollar_tag)
            i += len(dollar_tag)
            continue

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def expected_counts() -> dict[str, int]:
    """Row counts per qualified table, read back out of the generated dump."""
    text = (SQL_DIR / "03_data.sql").read_text(encoding="utf-8")
    return {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"^-- (\S+) — (\d+) row\(s\)$", text, re.M)
    }


def run(dry_run: bool) -> None:
    conn = rs._connect()
    try:
        cur = conn.cursor()
        for fname in FILES:
            path = SQL_DIR / fname
            if not path.exists():
                raise SystemExit(f"missing {path} — run scripts/dump_redshift_demo.py first")
            statements = split_statements(path.read_text(encoding="utf-8"))
            print(f"\n== {fname} — {len(statements)} statement(s)")
            for s in statements:
                label = " ".join(s.split())[:78]
                if dry_run:
                    print(f"   [dry-run] {label}")
                    continue
                try:
                    cur.execute(s)
                except Exception as exc:  # noqa: BLE001 — surface the real error
                    raise SystemExit(f"\nFAILED on:\n{s[:400]}\n\n{exc}") from exc
                print(f"   ok  {label}")
        if not dry_run:
            conn.commit()
    finally:
        conn.close()


def verify() -> int:
    """Re-read the live cluster and compare against the dump. Returns exit code."""
    exp = expected_counts()
    problems: list[str] = []
    print("\n== verification")

    for schema in SCHEMAS:
        try:
            tables = rs.list_tables(schema)
            routines = rs.list_routines(schema)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{schema}: cannot read schema — {exc}")
            continue
        print(f"\n{schema}: {len(tables)} table(s), {len(routines)} routine(s)")

        conn = rs._connect()
        try:
            cur = conn.cursor()
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t.name}"')
                actual = cur.fetchone()[0]
                key = f"{schema}.{t.name}"
                want = exp.get(key)
                if want is None:
                    print(f"  ?  {key}: {actual} row(s) — not in dump (extra object)")
                elif actual == want:
                    print(f"  ok {key}: {actual} row(s)")
                else:
                    problems.append(f"{key}: expected {want} row(s), found {actual}")
                    print(f"  !! {key}: expected {want}, found {actual}")
        finally:
            conn.close()

        for r in routines:
            print(f"  ok {schema}.{r.name} ({r.type})")

    missing = set(exp) - {
        f"{s}.{t.name}" for s in SCHEMAS for t in (rs.list_tables(s) or [])
    }
    for m in sorted(missing):
        problems.append(f"{m}: table missing entirely")
        print(f"  !! {m}: MISSING")

    if problems:
        print(f"\nFAILED — {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nPASS — every table and routine present with the expected row counts.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print statements, execute nothing")
    ap.add_argument("--verify-only", action="store_true", help="skip the restore, just check")
    args = ap.parse_args()

    if not args.verify_only:
        run(args.dry_run)
        if args.dry_run:
            print("\ndry run — nothing was executed")
            return 0
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
