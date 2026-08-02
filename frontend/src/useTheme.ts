import { useCallback, useEffect, useState } from "react";

// G17 — explicit theme control. Before this, the app was light-only with an
// undesigned `prefers-color-scheme: dark` block; dark is now the authored
// default and the user's explicit choice must beat the OS preference in both
// directions (see docs/webapp/DESIGN-SYSTEM.md's theming contract).

export type Theme = "dark" | "light";

const STORAGE_KEY = "lakebridge-theme";

function readStored(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "dark" || v === "light" ? v : null;
  } catch {
    // Private mode / storage disabled — fall back to the default, don't crash.
    return null;
  }
}

export function useTheme() {
  // Default is dark when nothing is stored. We deliberately do NOT read the OS
  // preference here: the CSS already handles the no-explicit-choice case via
  // the media query, and stamping data-theme from JS on first paint would
  // override it. We only stamp once the user has actually chosen.
  const [theme, setThemeState] = useState<Theme>(() => readStored() ?? "dark");
  const [explicit, setExplicit] = useState<boolean>(() => readStored() !== null);

  useEffect(() => {
    const root = document.documentElement;
    if (explicit) {
      root.setAttribute("data-theme", theme);
    } else {
      // No stored choice: default to dark by stamping it, since dark is the
      // authored default for this app rather than "whatever the OS says".
      root.setAttribute("data-theme", "dark");
    }
  }, [theme, explicit]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    setExplicit(true);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Non-fatal — the in-memory choice still applies for this session.
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggleTheme };
}
