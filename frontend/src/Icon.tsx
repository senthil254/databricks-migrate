// G17 — the app's only icon source. Hand-rolled inline SVG on purpose: this
// project forbids adding unverified npm packages, and every icon before G17
// was a text glyph (⟳ ▤ ◫ ƒ 👁 ▸ ⛁ ⚠ ○ ◐ ✓ ✗) which rendered inconsistently
// across platforms and couldn't be coloured or sized reliably.
//
// All paths draw on a 24x24 viewBox and inherit `currentColor`, so colour is
// controlled entirely by CSS (see docs/webapp/DESIGN-SYSTEM.md).

import type { ReactElement } from "react";

export type IconName =
  | "database"
  | "table"
  | "view"
  | "function"
  | "chevron"
  | "refresh"
  | "eye"
  | "code"
  | "migrate"
  | "chat"
  | "spark"
  | "catalog"
  | "logs"
  | "check"
  | "x"
  | "dot"
  | "warning"
  | "arrow-right"
  | "sun"
  | "moon"
  | "panel"
  | "drag";

// Stroke-drawn unless noted. Kept deliberately simple — these render at 14-22px
// in tree rows, so fine detail is wasted and just muddies at small sizes.
// ReactElement, not the global JSX namespace — under this project's
// react-jsx transform the global `JSX` namespace does not exist, so
// `npm run build` (which runs `tsc -b`) failed on it.
const PATHS: Record<IconName, ReactElement> = {
  database: (
    <>
      <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
      <path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13" />
      <path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3" />
    </>
  ),
  table: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M9 9.5V20" />
    </>
  ),
  view: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18" />
      <path d="M12.5 13.5h5M12.5 16.5h3" />
    </>
  ),
  function: (
    <>
      <path d="M14 4.5h-1.2A2.8 2.8 0 0 0 10 7.3V19" />
      <path d="M7.5 11h6.5" />
      <path d="M16 13.5l3.5 5M19.5 13.5L16 18.5" />
    </>
  ),
  chevron: <path d="M9 5.5l7 6.5-7 6.5" />,
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20 4v5h-5" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  code: <path d="M8.5 8L4 12l4.5 4M15.5 8L20 12l-4.5 4M13.5 5l-3 14" />,
  migrate: (
    <>
      <path d="M3 8h13" />
      <path d="M12 4l4 4-4 4" />
      <path d="M21 16H8" />
      <path d="M12 12l-4 4 4 4" />
    </>
  ),
  chat: (
    <>
      <path d="M20.5 11.5a7.5 7.5 0 0 1-10.9 6.7L4 19.5l1.4-5.2A7.5 7.5 0 1 1 20.5 11.5z" />
      <path d="M9 11.5h6M9 8.5h4" />
    </>
  ),
  spark: (
    <>
      <path d="M12 3l1.9 5.3L19 10l-5.1 1.7L12 17l-1.9-5.3L5 10l5.1-1.7L12 3z" />
      <path d="M18.5 16.5l.7 1.9 1.8.7-1.8.7-.7 1.9-.7-1.9-1.8-.7 1.8-.7.7-1.9z" />
    </>
  ),
  catalog: (
    <>
      <rect x="3" y="3.5" width="7.5" height="7.5" rx="1.6" />
      <rect x="13.5" y="3.5" width="7.5" height="7.5" rx="1.6" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6" />
    </>
  ),
  logs: (
    <>
      <rect x="3.5" y="3.5" width="17" height="17" rx="2.5" />
      <path d="M7.5 8.5h9M7.5 12h9M7.5 15.5h5" />
    </>
  ),
  check: <path d="M4.5 12.5l5 5 10-11" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  dot: <circle cx="12" cy="12" r="4.5" fill="currentColor" stroke="none" />,
  warning: (
    <>
      <path d="M12 3.8L21.2 20H2.8L12 3.8z" />
      <path d="M12 9.5v4.5" />
      <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  "arrow-right": <path d="M4 12h15M13 6l6 6-6 6" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" />
    </>
  ),
  moon: <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4 8.2 8.2 0 1 0 20 14.2z" />,
  panel: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.2" />
      <path d="M10 4.5v15" />
    </>
  ),
  drag: (
    <>
      <circle cx="9" cy="6" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="15" cy="6" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="9" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="15" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="9" cy="18" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="15" cy="18" r="1.4" fill="currentColor" stroke="none" />
    </>
  ),
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
  /** Give a label only when the icon is the sole content of a control.
   *  When there's adjacent text, leave it off so it stays aria-hidden. */
  label?: string;
}

export function Icon({ name, size = 18, className, label }: IconProps) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
