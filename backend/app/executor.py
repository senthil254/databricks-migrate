"""Safe execution of `databricks labs lakebridge <cmd>` — argument arrays only, allowlisted."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from .models import EventType, RunStatus, store
from .redact import redact, strip_ansi

# The 10 real subcommands, from `databricks labs lakebridge --help`
# (verified 2026-08-01 against the installed CLI — see PLAN.md).
ALLOWED_COMMANDS = frozenset(
    {
        "analyze",
        "transpile",
        "describe-transpile",
        "install-transpile",
        "configure-reconcile",
        "reconcile",
        "aggregates-reconcile",
        "configure-database-profiler",
        "execute-database-profiler",
        "test-profiler-connection",
    }
)


class DisallowedCommandError(ValueError):
    pass


def _databricks_binary() -> str:
    path = shutil.which("databricks")
    if not path:
        raise RuntimeError("databricks CLI not found on PATH")
    return path


# Lakebridge's Morpheus transpiler shells out to a JVM-based LSP server.
# openjdk@21 is a Homebrew keg-only formula (not auto-linked onto PATH), so
# subprocesses launched without an interactive shell's exports can't find a
# JVM even though one is installed. Build an explicit env for our child
# process rather than assuming the caller's shell state.
_JAVA_HOME_CANDIDATES = ("/opt/homebrew/opt/openjdk@21", "/usr/local/opt/openjdk@21")


def _subprocess_env() -> dict[str, str]:
    """Build a subprocess env with a working JVM on PATH and unambiguous auth.

    `shutil.which("java")` is not enough to decide this: on macOS,
    `/usr/bin/java` frequently exists and is executable but is only a stub
    that errors with "Unable to locate a Java Runtime" when no JDK is
    installed system-wide. Existence on PATH does not mean it works, so we
    unconditionally prefer a known-good Homebrew keg-only JDK by prepending
    it — that's a no-op if none of the candidates exist.

    G21 — the auth half. `databricks labs <x>` is a Go wrapper that spawns the
    labs project's own Python venv, and it injects `DATABRICKS_AUTH_TYPE=
    databricks-cli` into that child. The child SDK then resolves auth through
    the CLI's stored OAuth session and *ignores a perfectly valid
    `DATABRICKS_TOKEN` sitting in the same environment*. When the OAuth refresh
    token expires, every Lakebridge call dies with

        default auth: databricks-cli: cannot get access token:
        ... the refresh token is invalid ... auth_type=databricks-cli

    while the app's own SQL/browse paths keep working, because those build a
    Config() directly from the env PAT and never go through the CLI. That
    split is exactly why this looks like "Databricks is down" when it isn't.

    So: when we are in the no-profile/PAT configuration (see
    databricks_profile()), say so explicitly. `auth_type=pat` is the SDK's own
    documented selector; pinning it stops the wrapper from downgrading us to a
    stale OAuth session. Verified live: with it unset the transpile above
    fails, with it set the same command transpiles with 0 errors.

    A configured profile is left completely alone — that path is *supposed* to
    use the config file's credentials, OAuth included.
    """
    env = dict(os.environ)
    for candidate in _JAVA_HOME_CANDIDATES:
        java_bin = f"{candidate}/bin"
        if pathlib.Path(java_bin, "java").exists():
            env["JAVA_HOME"] = candidate
            env["PATH"] = f"{java_bin}:{env.get('PATH', '')}"
            break
    if not databricks_profile() and env.get("DATABRICKS_TOKEN"):
        env.setdefault("DATABRICKS_AUTH_TYPE", "pat")
    return env


# G4: `reconcile` (and, discovered separately in migrate.py's llm-transpile
# path — see MEMORY.md's G3.2 entry) only *dispatches* a real Databricks job;
# the CLI's own exit code 0 means "triggered", never "finished". Confirmed
# live 2026-08-01: `reconcile`'s stdout/stderr contains the exact same
# `/jobs/<id>/runs/<run_id>` URL shape llm-transpile already used this regex
# for, so it's reused rather than re-derived. migrate.py imports this (not
# vice versa) to avoid a circular import.
JOB_RUN_URL_RE = re.compile(r"/jobs/\d+/runs/(\d+)")

# Metadata tables deployed by a prior `configure-reconcile` run (see
# docs/RECONCILE.md) — the real, only place reconcile's actual comparison
# result lives; the CLI/job itself never prints it.
_RECONCILE_METADATA_SCHEMA = "lakebridge_demo.reconcile_meta"


def poll_job_run(job_run_id: str, timeout_s: int = 480, interval_s: int = 10) -> tuple[str, str]:
    """Poll a real Databricks job run to actual completion. Returns
    (life_cycle_state, result_state). See JOB_RUN_URL_RE's comment — exit
    code 0 from the CLI only ever means "dispatched"."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        proc = subprocess.run(
            [_databricks_binary(), "jobs", "get-run", job_run_id, "-p", databricks_profile(), "-o", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            state = json.loads(proc.stdout).get("state", {})
            lifecycle = state.get("life_cycle_state", "")
            if lifecycle == "TERMINATED":
                return lifecycle, state.get("result_state", "")
        time.sleep(interval_s)
    return "TIMEOUT", ""


def _fetch_reconcile_result(job_run_id: str, lifecycle: str, result_state: str, dispatched_at: datetime) -> dict:
    """Real reconcile output shape, discovered live 2026-08-01 by running a
    real reconcile to completion and inspecting the actual metadata tables
    `configure-reconcile` deploys (lakebridge_demo.reconcile_meta.{main,
    metrics}) — the job itself prints no result, and `jobs get-run-output`
    doesn't work for this job's multi-task shape ("Retrieving the output of
    runs with multiple tasks is not supported"). The metadata row is matched
    by `start_ts` falling after this run's real dispatch time (a small
    negative buffer absorbs clock skew between this process and the job
    cluster) — there is no shared run/recon id to join on directly, since the
    CLI never surfaces the recon_id it generates.
    """
    from . import databricks_target as dt  # lazy: avoid importing the SQL driver for non-reconcile commands

    result: dict = {
        "job_run_id": job_run_id,
        "lifecycle_state": lifecycle,
        "result_state": result_state,
    }
    if not (lifecycle == "TERMINATED" and result_state == "SUCCESS"):
        return result

    window_start = (dispatched_at - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        main_rows = dt.execute(
            f"SELECT recon_table_id, recon_id, source_table, target_table, report_type, start_ts, end_ts "
            f"FROM {_RECONCILE_METADATA_SCHEMA}.main "
            f"WHERE start_ts >= TIMESTAMP'{window_start}' ORDER BY start_ts ASC LIMIT 1"
        )
        if not main_rows:
            result["detail_error"] = "no reconcile_meta.main row found after real dispatch time"
            return result
        main = main_rows[0]
        metrics_rows = dt.execute(
            f"SELECT recon_metrics, run_metrics FROM {_RECONCILE_METADATA_SCHEMA}.metrics "
            f"WHERE recon_table_id = {main.recon_table_id}"
        )
        result.update(
            {
                "recon_id": main.recon_id,
                "source_table": json.loads(main.source_table),
                "target_table": json.loads(main.target_table),
                "report_type": main.report_type,
                "started_at": str(main.start_ts),
                "ended_at": str(main.end_ts),
            }
        )
        if metrics_rows:
            recon_metrics = json.loads(metrics_rows[0].recon_metrics)
            run_metrics = json.loads(metrics_rows[0].run_metrics)
            result["metrics"] = recon_metrics
            # run_metrics.status is the real business-level "did source and
            # target actually match" verdict — deliberately kept distinct
            # from the Run's own COMPLETED/FAILED status, which reflects
            # whether the job *executed* successfully, not whether it found
            # zero differences (a real reconcile mismatch is a legitimate
            # successful run, not a technical failure).
            result["reconciliation_passed"] = run_metrics.get("status")
            if run_metrics.get("exception_message"):
                result["exception_message"] = redact(run_metrics["exception_message"])
    except Exception as exc:  # noqa: BLE001 — job succeeded technically even if we can't fetch its detail
        result["detail_error"] = redact(str(exc))
    return result


def databricks_profile() -> str:
    """The CLI profile every `databricks ...` invocation runs under.

    Env-driven so pointing the app at a different workspace is a config change,
    not a code edit; the default preserves the original eval workspace's
    behaviour.

    Setting `DATABRICKS_PROFILE=` (explicitly empty) means "there is no config
    file" — the deployment case. A container built from this repo has no
    ~/.databrickscfg at all, so naming a profile there guarantees failure even
    when the credentials are correct. Empty makes every caller fall back to the
    SDK's own environment-variable auth instead. See `databricks_config()`.
    """
    return os.getenv("DATABRICKS_PROFILE", "lakebridge-eval").strip()


def databricks_config():
    """The single place Databricks auth is resolved, for the SQL warehouse, the
    MCP client, the workspace client and the provisioning script alike.

    - profile set  -> Config(profile=...)   — a named entry in ~/.databrickscfg,
      whether it holds an OAuth session or a PAT; both look identical here.
    - profile empty -> Config()             — the SDK reads DATABRICKS_HOST plus
      either DATABRICKS_TOKEN (PAT) or DATABRICKS_CLIENT_ID/_SECRET (service
      principal). This is the path that works in CI and in a container, where
      no config file exists.

    Imported lazily so this module keeps working without the SDK installed.
    """
    from databricks.sdk.core import Config

    profile = databricks_profile()
    return Config(profile=profile) if profile else Config()


def build_argv(command: str, args: list[str], profile: str | None = None) -> list[str]:
    """Build a safe argv list. Never returns a shell string."""
    if command not in ALLOWED_COMMANDS:
        raise DisallowedCommandError(
            f"command {command!r} is not in the allowlist of real Lakebridge subcommands"
        )
    profile = profile if profile is not None else databricks_profile()
    # No profile -> omit `-p` entirely rather than passing an empty value, and
    # let the CLI authenticate from the same env vars the SDK uses. `-p ""`
    # would be read as a profile literally named "", which resolves to nothing.
    profile_flag = ["-p", profile] if profile else []
    # args are pre-validated flag/value pairs supplied by our own API layer,
    # never raw user text concatenated into a shell string.
    return [_databricks_binary(), "labs", "lakebridge", command, *profile_flag, *args]


def run_command(run_id: str, command: str, args: list[str]) -> None:
    """Execute a run synchronously in the calling thread; records events to the store."""
    try:
        argv = build_argv(command, args)
    except DisallowedCommandError as exc:
        store.add_event(run_id, EventType.STDERR, redact(str(exc)))
        store.set_status(run_id, RunStatus.FAILED, exit_code=None)
        return

    store.set_status(run_id, RunStatus.RUNNING)
    store.add_event(run_id, EventType.STATUS, f"starting: {' '.join(argv[:4])} ...")

    dispatched_at = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            argv,
            input="no\n",  # `reconcile` interactively asks to open the job run
            # URL in a browser; feeding "no" answers that without a real TTY.
            # Harmless no-op for commands that don't prompt.
            capture_output=True,
            text=True,
            timeout=600,  # reconcile dispatches a real remote job run, which
            # is slower than the local transpile/analyze commands.
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        store.add_event(run_id, EventType.STDERR, "command timed out after 300s")
        store.set_status(run_id, RunStatus.FAILED, exit_code=None)
        return
    except Exception as exc:  # noqa: BLE001 — surface any spawn failure as a failed run
        store.add_event(run_id, EventType.STDERR, redact(str(exc)))
        store.set_status(run_id, RunStatus.FAILED, exit_code=None)
        return

    if proc.stdout:
        for line in proc.stdout.splitlines():
            store.add_event(run_id, EventType.STDOUT, redact(strip_ansi(line)))
    if proc.stderr:
        for line in proc.stderr.splitlines():
            store.add_event(run_id, EventType.STDERR, redact(strip_ansi(line)))

    if command == "reconcile" and proc.returncode == 0:
        _finish_reconcile_run(run_id, proc, dispatched_at)
        return

    status = RunStatus.COMPLETED if proc.returncode == 0 else RunStatus.FAILED
    store.set_status(run_id, status, exit_code=proc.returncode)


def _finish_reconcile_run(run_id: str, proc: "subprocess.CompletedProcess[str]", dispatched_at: datetime) -> None:
    """G4: `reconcile`'s CLI exit code 0 only means the job was *triggered*
    (see JOB_RUN_URL_RE's comment / MEMORY.md's G2 entry) — this closes that
    gap by polling the real dispatched job to an actual terminal state before
    the Run is reported COMPLETED, and attaches the real comparison result
    once available. The Run's status stays RUNNING (already set above, in
    run_command) for the entire duration of this function — a client polling
    GET /runs/{run_id} sees an honest intermediate state, not a premature
    "completed"."""
    combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = JOB_RUN_URL_RE.search(combined_output)
    if not match:
        store.add_event(
            run_id, EventType.STDERR,
            "reconcile CLI exited 0 but no job run URL found in its output; "
            "cannot verify real completion",
        )
        store.set_status(run_id, RunStatus.FAILED, exit_code=proc.returncode)
        return

    job_run_id = match.group(1)
    store.add_event(
        run_id, EventType.STATUS,
        f"reconcile job {job_run_id} dispatched; polling for real completion "
        "(this run stays 'running' until the job reaches a real terminal state)",
    )

    lifecycle, result_state = poll_job_run(job_run_id)
    store.add_event(
        run_id, EventType.STATUS,
        f"reconcile job {job_run_id} reached lifecycle={lifecycle} result={result_state}",
    )

    result = _fetch_reconcile_result(job_run_id, lifecycle, result_state, dispatched_at)
    store.set_result(run_id, result)

    if lifecycle == "TERMINATED" and result_state == "SUCCESS":
        if "reconciliation_passed" in result:
            store.add_event(
                run_id, EventType.STATUS,
                f"real reconcile result: reconciliation_passed={result['reconciliation_passed']} "
                f"metrics={result.get('metrics')}",
            )
        store.set_status(run_id, RunStatus.COMPLETED, exit_code=proc.returncode)
    else:
        store.add_event(
            run_id, EventType.STDERR,
            f"reconcile job {job_run_id} did not reach TERMINATED/SUCCESS "
            f"(lifecycle={lifecycle}, result={result_state})",
        )
        store.set_status(run_id, RunStatus.FAILED, exit_code=proc.returncode)


def run_command_async(run_id: str, command: str, args: list[str]) -> None:
    thread = threading.Thread(target=run_command, args=(run_id, command, args), daemon=True)
    thread.start()
