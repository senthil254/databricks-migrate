import pytest

from app.executor import (
    ALLOWED_COMMANDS,
    DisallowedCommandError,
    _subprocess_env,
    build_argv,
    databricks_profile,
)
from app.executor import databricks_config
from app.redact import redact, strip_ansi


# --------------------------------------------------------------- deployment auth
# These cover the container/CI case: no ~/.databrickscfg exists, so naming a
# profile guarantees failure even with correct credentials. An empty
# DATABRICKS_PROFILE is the signal to authenticate from the environment instead.


def test_empty_profile_drops_the_p_flag(monkeypatch):
    """`-p ""` would be read as a profile literally named "", which resolves to
    nothing — the flag has to be absent entirely."""
    monkeypatch.setenv("DATABRICKS_PROFILE", "")
    argv = build_argv("describe-transpile", [])
    assert "-p" not in argv
    assert argv[-1] == "describe-transpile"


def test_named_profile_still_passes_the_p_flag(monkeypatch):
    monkeypatch.setenv("DATABRICKS_PROFILE", "some-profile")
    argv = build_argv("describe-transpile", [])
    assert "-p" in argv and "some-profile" in argv


def test_default_profile_is_unchanged(monkeypatch):
    """The original workspace's behaviour must survive every change here."""
    monkeypatch.delenv("DATABRICKS_PROFILE", raising=False)
    assert databricks_profile() == "lakebridge-eval"


def test_empty_profile_builds_env_based_config(monkeypatch):
    """With no profile, Config must come from the environment — this is what
    makes a PAT or service principal work where there is no config file."""
    monkeypatch.setenv("DATABRICKS_PROFILE", "")
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com")
    # Assembled, not a literal — see test_redact_masks_databricks_pat.
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi" + "0" * 34)
    cfg = databricks_config()
    assert cfg.host == "https://example.cloud.databricks.com"
    assert cfg.auth_type == "pat"


def test_allowlist_accepts_real_commands():
    for cmd in ALLOWED_COMMANDS:
        argv = build_argv(cmd, [])
        assert argv[:3][-2:] == ["labs", "lakebridge"] or "lakebridge" in argv
        assert argv[3] == cmd


def test_allowlist_rejects_unknown_command():
    with pytest.raises(DisallowedCommandError):
        build_argv("rm -rf", [])


def test_allowlist_rejects_shell_injection_attempt():
    with pytest.raises(DisallowedCommandError):
        build_argv("transpile; rm -rf /", [])


def test_build_argv_uses_arg_list_not_shell_string():
    argv = build_argv("describe-transpile", [])
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    # profile is always injected, never taken from unvalidated input.
    # Assert against the CONFIGURED profile, not a literal: the profile became
    # env-driven (DATABRICKS_PROFILE) for the paid-workspace move, so a
    # hardcoded "lakebridge-eval" passed alone but failed in the full suite,
    # where loading backend/.env sets the profile to the paid workspace.
    # What this test is actually for is the argv-list property, not the value.
    # Both configurations are legitimate, so pin the behaviour of each rather
    # than assuming one. `.env` now ships with an EMPTY profile (environment
    # auth, the container/CI path), which made the unconditional `-p` assertion
    # below fail — the flag is deliberately absent in that mode.
    profile = databricks_profile()
    if profile:
        assert "-p" in argv and profile in argv
    else:
        assert "-p" not in argv


def test_exactly_ten_real_commands():
    assert len(ALLOWED_COMMANDS) == 10


def test_redact_masks_token_kv():
    out = redact("token=abc123secret more text")
    assert "abc123secret" not in out
    assert "[REDACTED]" in out


def test_redact_masks_bearer_header():
    out = redact("Authorization: Bearer abcDEF123.xyz")
    assert "abcDEF123.xyz" not in out


def test_redact_masks_databricks_pat():
    # Assembled at runtime rather than written as a literal. The value is fake,
    # but it is token-SHAPED, and a literal here trips GitHub's push protection
    # (and every other secret scanner) on an entirely invented string — which
    # trains people to click "allow this secret", the one habit you never want.
    # redact() still receives the identical full string, so the test is unchanged.
    fake_pat = "dapi" + "1234567890abcdef" * 2
    out = redact(f"using {fake_pat} for auth")
    assert fake_pat not in out
    assert "[REDACTED]" in out


def test_redact_masks_connection_string_credentials():
    out = redact("jdbc:postgresql://user:hunter2@db.internal:5432/prod")
    assert "hunter2" not in out


def test_redact_leaves_normal_text_alone():
    out = redact("Processed file: 01_customer_dim.sql (errors: 0)")
    assert out == "Processed file: 01_customer_dim.sql (errors: 0)"


def test_redact_empty_string():
    assert redact("") == ""


def test_redact_masks_snake_case_secret_kv():
    """Regression: found by manual security review 2026-08-01. Plain \\b
    boundaries don't fire inside snake_case identifiers because underscore
    is a \\w character, so `aws_secret_access_key=...` and `ACCESS_TOKEN=...`
    silently passed through the original pattern. See redact.py's comment
    on _B_L/_B_R for the root cause."""
    out = redact("aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert "wJalrXUtnFEMI" not in out
    out2 = redact('ACCESS_TOKEN = "ya29.a0AfH6SMC_verysecret_1234567890"')
    assert "ya29" not in out2
    out3 = redact("DB_PASSWORD=hunter2hunter2")
    assert "hunter2hunter2" not in out3


def test_redact_masks_aws_access_key_id():
    out = redact("AKIAIOSFODNN7EXAMPLE in the log line")
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_strip_ansi_removes_color_codes():
    """Regression: found while building G3's log viewer — databricks-cli's
    rich-text logging emits ANSI codes into captured stdout/stderr, which
    were bleeding into the UI unreadably (e.g. '[90m01:25:44 [0m')."""
    raw = "\x1b[90m00:37:57\x1b[0m \x1b[1m\x1b[32m    INFO\x1b[0m plain text here"
    out = strip_ansi(raw)
    assert "\x1b" not in out
    assert "plain text here" in out
    assert "00:37:57" in out


def test_redact_masks_pem_private_key_block():
    block = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAA\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    out = redact(block)
    assert "b3BlbnNzaC1rZXktdjEAAAAA" not in out


def test_subprocess_env_resolves_a_working_java_for_morpheus():
    """Regression test: Morpheus's LSP server needs a JVM. openjdk@21 is
    keg-only (not auto-linked onto PATH) and macOS often has a broken
    `/usr/bin/java` stub that resolves but errors — so PATH-order matters,
    not just resolvability. See executor._subprocess_env's docstring."""
    import shutil
    import subprocess

    env = _subprocess_env()
    java = shutil.which("java", path=env.get("PATH"))
    assert java is not None, f"java not resolvable in built env; PATH={env.get('PATH')!r}"
    result = subprocess.run([java, "-version"], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
