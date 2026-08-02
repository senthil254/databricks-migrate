# Running this in GitHub Codespaces

The app runs unchanged in a Codespace, but three things differ from a laptop and each one fails in a
way that looks like something else. All three are handled by config, not code edits.

## 1. There is no `~/.databrickscfg`, so don't name a profile

A fresh container has no Databricks config file. Naming a profile there fails **even when your
credentials are correct**, because the profile doesn't exist to be read.

Set `DATABRICKS_PROFILE` to **empty**. That is a deliberate signal, not an oversight: the app then
authenticates from environment variables via `executor.databricks_config()`.

| Variable | Value |
|---|---|
| `DATABRICKS_PROFILE` | *(empty)* — already set in `devcontainer.json` |
| `DATABRICKS_HOST` | `https://<workspace>.cloud.databricks.com` |
| `DATABRICKS_TOKEN` | your PAT |

For production prefer a **service principal**: set `DATABRICKS_CLIENT_ID` and
`DATABRICKS_CLIENT_SECRET` instead of `DATABRICKS_TOKEN`. It isn't tied to one person's account, so
it doesn't break when someone leaves or rotates their password.

## 2. Both ports must be reachable by the *viewer's* browser

The UI calls the backend **from the browser**, not from the server. If you forward only 5173, the
page loads and every request fails — the misleading "ADAPTER UNREACHABLE" banner.

Forward **8811 and 5173**, then set:

```
ALLOWED_ORIGINS=https://<codespace>-5173.app.github.dev     # backend reads this
VITE_API_BASE=https://<codespace>-8811.app.github.dev       # frontend build reads this
```

`VITE_API_BASE` is read at **build/dev-server start**, so set it before starting vite; changing it
later needs a restart.

Unset, both fall back to their previous localhost values, so a laptop needs neither.

`ALLOWED_ORIGINS` refuses `*` on purpose — this API has no auth model and performs real writes.

## 3. A container has no OS keyring

`databricks auth login` (OAuth) stores tokens in the OS keyring by default. A headless container has
none, and the failure message talks about the keyring rather than about auth. `post-create.sh`
writes `auth_storage = file` into `~/.databrickscfg` to avoid this. With a PAT in the environment you
don't need `auth login` at all.

## Secrets

Set every credential as a **Codespaces Secret** (Settings → Secrets and variables → Codespaces).
`backend/.env` is gitignored and will not exist in the Codespace, so Redshift, Starburst and the LLM
are unconfigured until you do:

```
DATABRICKS_HOST  DATABRICKS_TOKEN
REDSHIFT_PASSWORD
STARBURST_CLIENT_SECRET  STARBURST_PASSWORD
LLM_API_KEY
```

Never commit these. Never paste them into chat or an issue.

## Port visibility — read before making anything public

A **public** Codespaces port is unauthenticated. Anyone with the URL can drive this app, which
creates real Databricks objects, copies real row data, and spends a live LLM key.

Prefer **Organization** visibility and share with named people. If you do go public, treat it as a
live demo you are watching, and stop the Codespace afterwards.

## Two things this can't fix from inside the container

- **Redshift/Starburst network access.** Your Redshift cluster likely has an IP allowlist; a
  Codespace's egress IP will not be on it. Sort that out before a live demo.
- **Idle timeout.** A Codespace stops after ~30 minutes idle and takes your `uvicorn`/`vite`
  processes with it. Restart both after a resume.

## Start

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8811
npm --prefix frontend run dev -- --port 5173
```

## Forwarded ports (dev tunnels / Codespaces): use the same-origin proxy

Forward **one** port — 5173 — and run the frontend with:

```
VITE_API_BASE=/api
npm --prefix frontend run dev -- --port 5173 --host 0.0.0.0
```

Vite proxies `/api` to the backend (`vite.config.ts`; override with
`BACKEND_ORIGIN`). The browser then only ever contacts the host serving the
page, so no second tunnel, no CORS, and no `ALLOWED_ORIGINS` change is needed.

**Why not forward the backend separately.** Publishing 8811 on its own tunnel
looks like it works — `curl https://<id>-8811.../explore/redshift/schemas`
returns 200 — while the app sits on "Loading…" forever. Three reasons, none of
which is visible from a terminal:

1. **Mixed content.** The tunnel is HTTPS; the default API base is
   `http://127.0.0.1:8811`. A browser refuses that call outright.
2. **The anti-phishing interstitial.** A *browser* request to a forwarded port
   is answered with an HTML warning page until a human clicks through it. `curl`
   never sees it, so the API appears healthy while every `fetch` gets HTML
   instead of JSON.
3. **Two public surfaces instead of one**, doubling what has to be secured.

Measured through a live dev tunnel: with a separate 8811 tunnel, Starburst
timed out at 90s; through the same-origin proxy the same call returned in 2.0s.

Keep the tunnel **Private/Organization** unless you are actively demoing — a
public tunnel is unauthenticated and this app performs real writes.
