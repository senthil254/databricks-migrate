"""G5 backend security hardening — independent checker pass.

See MEMORY.md's 2026-08-01 G5 entry for the full itemized report. This file
holds the two concrete, previously-untested regressions found during that
review:

1. `backend/.env` must never become tracked by git — a manual grep before
   every commit has been the process so far (see README.md); this makes it
   an automated, permanent check instead of relying on memory.
2. `copy_redshift_table_data` (the `/migrate/redshift/data/{schema}/{table}`
   path) previously interpolated `schema`/`table` straight from the URL
   into a Redshift `SELECT ... FROM "{schema}"."{table}"` string and into a
   Databricks target table name used in unguarded `DROP TABLE`/`CREATE
   TABLE` statements — no `_ident()` guard, unlike every other DDL path.
   Fixed by reusing `redshift_conn._ident()` before either identifier is
   interpolated anywhere. This is a real, no-network regression test: it
   proves an injection-shaped identifier is rejected as a normal FAILED
   migration (via ConnectorError) before any SQL is ever built, without
   needing a live Redshift/Databricks connection.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_backend_env_is_gitignored_and_not_tracked():
    """Automated version of the manual "grep before every commit" check
    this project has relied on since backend/.env was created (see
    MEMORY.md's G3.1 entry: real credentials were pasted into chat, moved
    here, and must never regress into being tracked)."""
    env_path = REPO_ROOT / "backend" / ".env"

    # This checkout may not be a git repo at all (the paid-workspace fork is an
    # rsync copy, not a clone). `git check-ignore` then exits 128 — "not a git
    # repository" — which is NOT the same as "the file is unignored". Asserting
    # on it regardless turned a non-git checkout into a fake security failure.
    # Skip loudly instead: there is no tracking risk without a repo, and the
    # .gitignore rule itself is still asserted below.
    in_git_repo = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
    ).returncode == 0
    if not in_git_repo:
        gitignore = (REPO_ROOT / "backend" / ".gitignore")
        assert gitignore.exists() and ".env" in gitignore.read_text().split(), (
            "not a git repo, and backend/.gitignore does not list .env — "
            "the moment this folder becomes a repo, credentials would be committable"
        )
        pytest.skip("not a git repository; .gitignore rule asserted directly instead")

    # `git check-ignore` exits 0 if the path IS ignored.
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(env_path)],
        cwd=REPO_ROOT, timeout=10,
    )
    assert ignored.returncode == 0, "backend/.env is NOT covered by any .gitignore rule"

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(env_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
    )
    assert tracked.returncode != 0, "backend/.env IS tracked by git — this must never happen"


@pytest.mark.parametrize(
    "bad_identifier",
    [
        'evil" ; DROP TABLE x --',
        "../../etc/passwd",
        "x`; DROP TABLE lakebridge_demo.g3_migrations.evil; --",
        "public.venue; SELECT 1",
    ],
)
def test_copy_redshift_table_data_rejects_injection_shaped_identifiers(bad_identifier):
    """No live Redshift/Databricks connection needed: `redshift_conn._ident()`
    rejects the identifier before `_connect()` is ever reached, and the
    surrounding try/except in `copy_redshift_table_data` turns that into a
    normal FAILED migration — never a raw SQL string built from untrusted
    input. This is the regression test for the G5 fix described in this
    module's docstring."""
    from app.migrate import copy_redshift_table_data

    mig = copy_redshift_table_data("public", bad_identifier)
    assert mig.status.value == "failed"
    assert mig.error is not None
    assert "invalid identifier" in mig.error.lower()


def test_ident_guard_rejects_injection_shaped_schema_too():
    from app.migrate import copy_redshift_table_data

    mig = copy_redshift_table_data('public"; DROP TABLE x; --', "venue")
    assert mig.status.value == "failed"
    assert mig.error is not None
    assert "invalid identifier" in mig.error.lower()
