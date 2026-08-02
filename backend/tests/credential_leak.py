"""Shared helper for the "no credentials in responses" tests.

Why this exists: those tests used to assert on the *literal* password strings,
copied straight out of the environment file. That works, but it hardcodes live
credentials into the test suite, so the secret ships with the source. Publishing
the repository would have published the Redshift password — inside a file whose
entire purpose is proving passwords don't escape.

Reading the values from the environment keeps the assertion exactly as strong
(it still checks the real, current secret) while keeping the secret in
`backend/.env`, which is git-ignored.

If a variable isn't set, its check is skipped rather than silently passing on an
empty string — `"" in body` is always True and would turn this into a test that
can never fail.
"""
from __future__ import annotations

import os

# Every env var whose value must never appear in an HTTP response body.
_SECRET_VARS = (
    "REDSHIFT_PASSWORD",
    "STARBURST_PASSWORD",
    "STARBURST_CLIENT_SECRET",
    "DATABRICKS_TOKEN",
    "LLM_API_KEY",
)


def _assert_no_real_credentials_in(body: str) -> None:
    checked = 0
    for var in _SECRET_VARS:
        value = (os.getenv(var) or "").strip()
        if len(value) < 6:          # unset, or too short to be a meaningful match
            continue
        checked += 1
        assert value not in body, f"{var} leaked into a response body"
    assert checked > 0, (
        "no credentials were available to check — set backend/.env so this test "
        "asserts something real instead of passing vacuously"
    )
