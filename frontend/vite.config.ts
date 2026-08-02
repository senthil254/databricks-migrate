import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies /api -> the FastAPI adapter, so the browser only ever
// talks to ONE origin (whatever serves this page).
//
// Why this exists: when the UI is reached through a forwarded port (VS Code dev
// tunnels, Codespaces), calling the backend on its own public URL means every
// request is cross-origin AND crosses a second tunnel host. Two things then
// break that look nothing like themselves:
//
//   * mixed content — an HTTPS page cannot call http://127.0.0.1:8811 at all;
//   * the tunnel's anti-phishing interstitial — a *browser* request to a
//     forwarded port is answered with an HTML warning page until someone
//     clicks through it. curl never sees this, so the API looks healthy from a
//     terminal while the app hangs "loading" in the browser.
//
// Same-origin /api sidesteps both: only the page's own host is ever contacted,
// so only that one port needs forwarding.
//
// Set VITE_API_BASE=/api to use it (see README-CODESPACES.md). Unset, the app
// keeps calling http://127.0.0.1:8811 directly, so plain local dev is unchanged.
const BACKEND = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8811'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
    // Forwarded-port hosts (dev tunnels / Codespaces) are not localhost, and
    // Vite rejects unknown Host headers by default.
    allowedHosts: ['.devtunnels.ms', '.app.github.dev', 'localhost', '127.0.0.1'],
  },
})
