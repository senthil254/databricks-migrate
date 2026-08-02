"""Package init — loads backend/.env before any submodule reads the environment.

This exists because of a real bug, not for tidiness.

`databricks_target` resolves its configuration at *module level*
(`_WAREHOUSE_HOSTNAME`, `_WAREHOUSE_HTTP_PATH`, `_DATABRICKS_PROFILE`,
`TARGET_CATALOG`, `TARGET_SCHEMA` are module constants). `load_dotenv()` used to
run only inside `app.main`. So the values those constants took depended on
whether `app.main` happened to be imported first:

    from app.databricks_target import TARGET_CATALOG   # .env NOT loaded yet
    from app.main import app                           # .env loads — too late

On that order every default applied, which silently pointed the process at the
*original free-tier workspace* (`<old-workspace>...`, profile `lakebridge-eval`)
instead of the configured one. It surfaced as `Invalid access token` from tests
that had nothing to do with auth — an error naming the wrong cause entirely.

Import order should never decide which Databricks workspace gets written to.
Loading here fixes it for every entry point — app, tests and scripts — because
nothing under `app.` can be imported without running this first.

`app.main` still calls `load_dotenv` too; that is harmless (idempotent, and it
does not override already-set variables) and is left in place so deleting this
file cannot quietly reintroduce the bug.
"""
import pathlib

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")
