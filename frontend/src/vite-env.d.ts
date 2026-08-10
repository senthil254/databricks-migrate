/// <reference types="vite/client" />

// Typed so a mistyped variable name is a build error rather than a silent
// `undefined` that falls back to localhost and only shows up as a dead app in
// the browser.
interface ImportMetaEnv {
  /** Origin of the FastAPI adapter, e.g. https://<codespace>-8811.app.github.dev.
   *  Unset in local development, where apiBase.ts falls back to 127.0.0.1:8811. */
  readonly VITE_API_BASE?: string;
  /** "1" reveals the destructive testing tools in the Logs section.
   *  Anything else (including unset) hides them — the demo-safe default. */
  readonly VITE_TESTING_TOOLS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
