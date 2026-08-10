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
// When VITE_API_BASE is unset we choose at *runtime* from the page's own host,
// so one running dev server serves both localhost and a forwarded-port URL:
//
//   * localhost / 127.0.0.1  -> talk to the backend directly on 8811. Unchanged
//     local development, and it still works if vite is not the page's server.
//   * anything else (a dev tunnel, a Codespace, a LAN IP) -> "/api", the
//     same-origin proxy defined in vite.config.ts. Only the page's own host is
//     ever contacted, so only port 5173 needs forwarding and neither mixed
//     content nor the tunnel interstitial can fire.
//
// This is deliberately host-based rather than protocol-based: a LAN IP over
// plain http has no mixed-content problem but 127.0.0.1 is still wrong there,
// because it resolves to the *viewer's* machine, not the server's.
//
// An explicit VITE_API_BASE always wins, so a real deployment can point at a
// separately hosted adapter.
function defaultBase(): string {
  if (typeof window === "undefined") return "http://127.0.0.1:8811";
  const host = window.location.hostname;
  const isLocal = host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  return isLocal ? "http://127.0.0.1:8811" : "/api";
}

const configured = import.meta.env.VITE_API_BASE?.trim();

export const API_BASE = (configured || defaultBase()).replace(/\/+$/, "");
