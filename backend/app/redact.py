"""Redact secret-shaped substrings from CLI output before it is stored or shown.

See MEMORY.md's 2026-08-01 entry for the snake_case boundary bug found and
fixed here by manual security review. (Hook-verification touch.)
"""
import re

# databricks-cli's rich-text logging emits ANSI colour codes even when
# stdout is captured non-interactively. Found while building G3's log
# viewer: raw `\x1b[90m`, `\x1b[1m` etc. were bleeding into the UI.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)

# `\b` is a \w/\W transition, and underscore IS a \w character — so `\bsecret\b`
# never fires inside "aws_secret_access_key" or "ACCESS_TOKEN" (no transition
# either side of "secret"/"token" there). Snake_case env-var-style names are
# the single most common real-world shape for these, so anchoring on \b alone
# silently let them through — found by independent security review, 2026-08-01.
# (?<![A-Za-z0-9]) / (?![A-Za-z0-9]) treat underscore as *not* part of the
# "word" for boundary purposes, which is what's actually needed here.
_B_L = r"(?<![A-Za-z0-9])"
_B_R = r"(?![A-Za-z0-9])"

_PATTERNS = [
    # generic key=value or key: value secrets (token, password, secret, key,
    # apikey...), including snake_case-embedded forms like aws_secret_access_key
    # or ACCESS_TOKEN.
    re.compile(
        rf"(?i){_B_L}(token|password|passwd|secret|api[_-]?key|access[_-]?key){_B_R}"
        r"\s*[:=]\s*(?P<val>[^\s,;]+)"
    ),
    # bearer / basic auth headers
    re.compile(rf"(?i){_B_L}(Bearer|Basic)\s+(?P<val>[A-Za-z0-9\-._~+/]+=*)"),
    # Databricks PAT-shaped tokens
    re.compile(r"\bdapi[a-f0-9]{32,}\b"),
    # AWS access key IDs — recognizable by shape, no keyword needed
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    # PEM-style private key blocks (SSH, RSA, EC, PGP, generic)
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
    ),
    # JDBC/ODBC-style connection strings with embedded credentials
    re.compile(r"(?i)\b\w+://[^:\s]+:[^@\s]+@[^\s]+"),
]

_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Return `text` with anything token/secret/connection-string shaped masked out."""
    if not text:
        return text
    out = text
    for pat in _PATTERNS:
        if "val" in pat.groupindex:
            out = pat.sub(lambda m: m.group(0).replace(m.group("val"), _REDACTED), out)
        else:
            out = pat.sub(_REDACTED, out)
    return out
