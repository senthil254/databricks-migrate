// The single source of truth for where the FastAPI adapter lives.
//
// This used to be a `const BASE = "http://127.0.0.1:8811"` copied into five
// api modules. That works only when the browser and the backend are the same
// machine: served from anywhere else — a Codespace, a staging host, a
// colleague's laptop — `127.0.0.1` resolves to the *viewer's* machine, so every
// request fails and the app shows "ADAPTER UNREACHABLE" with nothing wrong on
// the server.
//
// Vite inlines `import.meta.env.VITE_API_BASE` at build time. Unset, the
// fallback is the previous hardcoded value, so local development is unchanged.
//
// Trailing slashes are stripped because every caller builds `${BASE}${path}`
// with a leading-slash path; "…:8811/" + "/runs" would request "//runs".
const configured = import.meta.env.VITE_API_BASE?.trim();

export const API_BASE = (configured || "http://127.0.0.1:8811").replace(/\/+$/, "");
