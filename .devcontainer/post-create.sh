#!/usr/bin/env bash
# Codespaces / devcontainer bootstrap.
#
# Deliberately does NOT create or contain any credential. Secrets come from
# Codespaces Secrets at runtime (see README-CODESPACES.md); nothing here writes
# a token to disk.
set -euo pipefail

echo "==> installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "==> python env (backend/.venv)"
uv venv --python 3.12 backend/.venv
if [ -f backend/requirements.txt ]; then
  uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
else
  # No manifest exists in this repo yet; this is the known-good set.
  # NOTE: pyarrow is deliberately absent. Installing it makes the backend test
  # suite die with a segmentation fault (exit 139) in test_databricks_mcp_client
  # — it changes databricks-sql-connector's fetch path. Do not add it.
  uv pip install --python backend/.venv/bin/python \
    fastapi uvicorn httpx httpx2 python-dotenv pydantic \
    databricks-sql-connector databricks-sdk \
    redshift-connector trino mcp pytest
fi

echo "==> node deps"
npm --prefix frontend install

echo "==> databricks CLI"
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh

# A headless container has no OS keyring, so the CLI's default "secure" token
# storage cannot work — this is the real reason `databricks auth login` fails
# in a Codespace, and it surfaces as an unhelpful keyring error rather than
# anything about auth. File storage is the supported alternative.
echo "==> databricks CLI token storage -> file (no keyring in a container)"
if [ ! -f "$HOME/.databrickscfg" ]; then
  printf '[__settings__]\nauth_storage = file\n' > "$HOME/.databrickscfg"
  chmod 600 "$HOME/.databrickscfg"
elif ! grep -q 'auth_storage' "$HOME/.databrickscfg"; then
  printf '\n[__settings__]\nauth_storage = file\n' >> "$HOME/.databrickscfg"
fi

cat <<'EOF'

============================================================
Setup complete. Before running anything, set these as
Codespaces Secrets (Settings -> Secrets -> Codespaces) —
never commit them:

  DATABRICKS_HOST      https://<workspace>.cloud.databricks.com
  DATABRICKS_TOKEN     your PAT   (or DATABRICKS_CLIENT_ID/_SECRET
                                   for a service principal)
  REDSHIFT_PASSWORD
  STARBURST_CLIENT_SECRET
  STARBURST_PASSWORD
  LLM_API_KEY

DATABRICKS_PROFILE is set to empty on purpose: that tells the
app there is no ~/.databrickscfg and to authenticate from the
environment instead.

Run it:
  backend/.venv/bin/python -m uvicorn app.main:app --port 8811   # from backend/
  npm --prefix frontend run dev -- --port 5173

Then set, from the Ports panel URLs:
  ALLOWED_ORIGINS=https://<codespace>-5173.app.github.dev   (backend)
  VITE_API_BASE=https://<codespace>-8811.app.github.dev     (frontend)

Both ports must be reachable by the viewer's browser. Prefer
Organization visibility over Public — a public port here is
unauthenticated and this app writes real data.
============================================================
EOF
