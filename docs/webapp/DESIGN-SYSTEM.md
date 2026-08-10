# Lakebridge Web UI — Design System (G17)

**This file is the contract.** Every agent working on the frontend reads this before touching a
file, and appends to the "Change log" at the bottom when it lands something. It exists because
the previous redesign attempt drifted: tokens were added but components kept their old
structure, so the app still looked like the pre-redesign build. If a rule here conflicts with
what's in a component, the rule wins — change the component.

## Non-negotiables

1. **Never hardcode a colour.** No hex, `rgb()`, or `rgba()` outside the token block in
   `index.css`. Use `var(--…)`. If you need a translucent version of a token, use
   `color-mix(in srgb, var(--token) 16%, transparent)`.
2. **Dark is the authored default.** Light is a real designed theme, not a naive inversion.
   Both must be legible; check contrast on both grounds before calling a component done.
3. **Never unmount the section divs in `App.tsx`.** All sections stay mounted and are toggled
   with CSS `display`. Unmounting destroys tree fetch state — there is a standing comment in
   that file warning about it. Same rule now applies to the persistent Data Explorer panel.
4. **No new npm dependencies.** Icons are hand-rolled inline SVG (`Icon.tsx`). This project's
   own rule is no unverified packages.
5. **Motion respects `prefers-reduced-motion`.** Every transition/animation must be disabled
   under that query. Keyboard focus must stay visible everywhere.
6. **Don't fake capability in the UI.** Where a source system genuinely can't do something
   (Starburst/Trino has no stored procedures at all — `CREATE PROCEDURE` is a grammar-level
   `SYNTAX_ERROR`), the UI says so plainly. Never render a fake affordance to make the design
   look symmetrical, and never emit synthesised text that could be mistaken for retrieved text.
   *This rule was violated once and it matters:* the Starburst connector claimed
   "Trino has no SHOW CREATE FUNCTION" and shipped a `-- body not recoverable` stub to users.
   The claim was false — real source was available the whole time. Before concluding an engine
   can't do something, try the alternatives, and if a fallback is genuinely needed, label it
   unmistakably as reconstructed.
7. **A resize affordance does not replace a scrollbar.** `.data-panel-scroll` keeps
   `overflow: auto` on both axes regardless of pane width: the scrollbar handles one over-long
   row, the resizer handles many. Removing either is a regression.

## Theming contract

Tokens are defined three times, in this order, so an explicit user choice beats the OS:

```css
:root { /* light values — the base */ }
@media (prefers-color-scheme: dark) { :root { /* dark values */ } }
:root[data-theme="dark"]  { /* dark values again */ }
:root[data-theme="light"] { /* light values again */ }
```

`useTheme` stamps `data-theme` on `document.documentElement` and persists to `localStorage`
under key `lakebridge-theme`. Default when nothing is stored: **dark**.

Components style through tokens only — never inside a media query directly.

## Colour tokens

### Surfaces

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg-0` | `#0A0E1A` | `#FFFFFF` | app ground, rail |
| `--bg-1` | `#0E1424` | `#F7F9FE` | panels, top bar |
| `--bg-2` | `#131A2E` | `#EEF2FA` | cards, tree rows |
| `--bg-3` | `#1A2340` | `#E3EAF7` | hover / raised state |
| `--line` | `rgba(255,255,255,.07)` | `rgba(10,20,40,.10)` | hairline borders |
| `--line-2` | `rgba(255,255,255,.12)` | `rgba(10,20,40,.16)` | emphasised borders |

### Text

| Token | Dark | Light |
|---|---|---|
| `--text` | `#EDF1FA` | `#101828` |
| `--text-h` | `#FFFFFF` | `#000000` |
| `--muted` | `#93A0BF` | `#556076` |
| `--faint` | `#5A6782` | `#8792A8` |

### Source systems — semantic, use consistently everywhere

| Token | Value | Means |
|---|---|---|
| `--redshift` | `#FF6B3D` | Redshift (source) |
| `--redshift-soft` | `#FF8C5A` | |
| `--starburst` | `#A855F7` | Starburst / Trino (source) |
| `--starburst-soft` | `#C084FC` | |
| `--databricks` | `#22D3EE` | Databricks / Unity Catalog (target) |
| `--databricks-soft` | `#67E8F9` | |

A Redshift thing is amber everywhere — tree dot, chip border, pipeline node, engine tag. Never
recolour a system per-component. (These names come from the reference material, which already
used violet-for-Starburst and amber-for-Redshift.)

### Status — separate from system colour, never reuse an accent for state

| Token | Dark | Light | State |
|---|---|---|---|
| `--ok` | `#34D399` | `#0F8A55` | completed / matched |
| `--running` | `#FBBF24` | `#B45309` | running / in progress |
| `--failed` | `#F87171` | `#C22B25` | failed / mismatch |
| `--queued` | `#5A6782` | `#8792A8` | queued / not started / skipped |

### Gradients

| Token | Value |
|---|---|
| `--grad` | `linear-gradient(135deg, var(--starburst) 0%, var(--redshift) 100%)` |
| `--grad-soft` | `linear-gradient(135deg, color-mix(in srgb, var(--starburst) 16%, transparent), color-mix(in srgb, var(--redshift) 16%, transparent))` |

Brand mark, active nav item, primary buttons, pipeline connector rail.

## Type

Both faces are already imported at the top of `index.css` — do not add another font import.

- `--font-display: "Space Grotesk"` — headings, nav labels, brand, stat numbers, card titles.
- `--font-body: "Inter"` — body, table content, descriptions.
- `--font-mono` — code blocks, DDL, identifiers, datatypes.

Scale: `11.5px` uppercase labels (`.14em` tracking, 700) · `13px` small/meta · `15px` body ·
`17px` card title · `clamp(20px,2.4vw,28px)` section title. Headings get
`letter-spacing:-.02em` and `text-wrap:balance`. Numeric columns get
`font-variant-numeric: tabular-nums`.

## Spacing / shape

- Radii: `10px` controls · `12px` icon tiles · `16px` cards · `18–20px` panels · `100px` pills.
- Layout uses flex/grid `gap` — not per-element margins.
- Any wide content (tables, code, diagrams) scrolls inside its own container. The page body
  never scrolls horizontally.

## Resizable panes

- A user-resizable pane publishes its width as a **CSS custom property that the existing layout
  rule already consumes** — here, inline `--rail-w-explorer` on `.shell`, read by
  `grid-template-columns: var(--rail-w-explorer) 1fr`. Never replace the layout rule with an
  inline `width`; that breaks the media-query overrides.
- The drag handle is positioned against the **non-scrolling** ancestor (`.shell`), never inside
  the scrolling pane. A handle inside a scroller cannot stay pinned across the full viewport
  height.
- Hit area ≥`10px` wide even when the visible grip is a `1–2px` line. A hairline grabbable only on
  its exact pixel is the classic failure of this control.
- Every drag control is also keyboard-operable: `role="separator"`, `aria-orientation`,
  `aria-valuenow`/`aria-valuemin`, `tabIndex={0}`, arrow keys for fine steps, Shift+arrow for
  coarse, plus a reset (Home and double-click).
- `preventDefault()` on pointer-down suppresses focus — call `.focus()` explicitly or the keyboard
  path is unreachable after a mouse grab.
- Clamp to a minimum **and** a viewport-relative maximum, and re-clamp on window resize. A width
  stored on a wide monitor must not strand the work area on a small one.
- Disable layout transitions while dragging (`.shell-resizing { transition: none }`) or the pane
  visibly lags the cursor. Set `user-select: none` app-wide for the duration.
- Persist the chosen size (`localStorage`), and tolerate storage being unavailable without
  breaking the drag.

## Repeating patterns

### Card

`background: var(--bg-2)`, `border: 1px solid var(--line)`, `border-radius: 16px`. On hover:
lift `translateY(-4px)`, `background: var(--bg-3)`, gradient border via `mask-composite`, and a
cursor-follow spotlight driven by `--mx`/`--my` (set by the `useSpotlight` hook). Applied to
`.migration-card`, `.batch-card`, `.chat-plan-card`, `.history-row`, `.reconcile-view`,
`.tree-panel`.

### Icon tile

`42px` square, `border-radius: 12px`, `background: var(--grad-soft)`, `1px solid var(--line)`,
SVG at `21px` in the relevant accent. Hover: scale `1.08`, rotate `-6deg`, background flips to
the solid accent, icon goes to `--bg-0`.

### Status pill

`display:inline-flex`, `gap:8px`, `padding:6px 14px`, `border-radius:100px`,
`border:1px solid color-mix(in srgb, var(--state) 32%, transparent)`,
`background: color-mix(in srgb, var(--state) 12%, transparent)`, text in the state colour,
`11.5px/600`, uppercase, `.04em`. Live states (`running`) carry a `7px` dot with the `pulse`
animation; terminal states carry a static dot.

**One pill implementation for the whole app.** Before G17 there were four competing ones
(`statusMeta.ts`, `MigrationCard`'s own classes, `BatchCard`'s `batch-pill-*`,
`HistoryList.normalizeStatus`). They collapse into `StatusPill.tsx` + `statusMeta.ts`.

### Pipeline node (the flow the user singled out)

Circular `54px` node, `background: var(--bg-2)`, `1px` border in the stage's state colour,
centred icon. Connector between nodes is a `2px` rail using `--grad` at `.35` opacity; the
completed portion is full-opacity. Active node pulses. Stage states map to `--ok` / `--running` /
`--failed` / `--queued`.

### Context menu

`ContextMenu.tsx` exports `useNodeMenu(items: ContextMenuItem[])` returning
`{ onContextMenu, menuElement }`. `useRefreshMenu(onRefresh)` is a thin wrapper for the
Refresh-only case.

- A right-click menu offers the **same actions** as the row's inline buttons, calling the **same
  handlers**, under the **same guard conditions**. A menu item that appears when its button would
  not is a defect.
- Menus are **additive**. Never remove an inline control because a menu now offers it.
- `onContextMenu` goes on the **outer** row element (`.tree-leaf-row`), not the inner label
  (`.tree-leaf`). The action buttons are siblings of the inner element, so a handler on it misses
  half the row's clickable area and the event bubbles to the panel root.
- `useNodeMenu`'s handler calls both `preventDefault()` and `stopPropagation()`. The
  `stopPropagation` is load-bearing: without it a leaf-row menu also opens the panel root's menu
  behind it.
- `ContextMenu`'s item `onClick` calls `stopPropagation()` too, because the menu renders inside a
  row whose own `onClick` opens the preview pane.
- The menu clamps to the viewport — measured in `useLayoutEffect`, then repositioned. A
  `position: fixed` menu at raw `clientX`/`clientY` runs off-screen when opened near an edge.
- `ContextMenuItem` has no `disabled`, no separators, no submenus. If an action does not apply,
  omit the item.

### Card fold

`CardFold.tsx` — the collapse/expand affordance in a card's top-right corner. Used by `BatchCard`
and the chat plan card.

- **One shared control across surfaces.** Two differently-shaped toggles doing the same job is
  worse than shipping neither. A new foldable card reuses this, it does not grow its own.
- Positioned **absolutely, top-right**, so the card must be `position: relative` and its head needs
  `padding-right` (34px) — otherwise a long title runs underneath the button.
- Hit area **28px** around a 14px glyph. The glyph is not the target.
- An icon-only control **must** carry a real accessible name that flips with state
  (`"Collapse batch batch_84"` ↔ `"Expand …"`) plus `aria-expanded`. A bare chevron is a mystery
  glyph to a screen reader.
- Caret points **down when open, right when closed** — the same convention as the explorer's tree
  carets. Do not invert it per-surface.
- **A collapsed card still tells the truth.** Fold a card that reports failures and the failure
  count stays visible in the summary line. Collapsing must never turn a partial failure into
  something that reads as fine.
- Fold state is **view-local** — not persisted, not lifted. It is a reading preference, unlike the
  rail width, which is a deliberate layout choice worth remembering.
- Body is **display-toggled, not unmounted**, so folding never discards fetched content or restarts
  a poll.

## Icons

`Icon.tsx` exports a single `<Icon name="…" />`, inline SVG, `currentColor`, default `18px`,
`stroke-width: 1.75`, `aria-hidden="true"` unless given a label.

Required names: `database`, `table`, `view`, `function`, `chevron`, `refresh`, `eye`, `code`,
`migrate`, `chat`, `spark`, `catalog`, `logs`, `check`, `x`, `dot`, `warning`, `arrow-right`,
`sun`, `moon`, `panel`.

Replaces every text glyph currently in use (`⟳ ▤ ◫ ƒ 👁 ▸ ▾ ⛁ ⚠ ○ ◐ ✓ ✗ ⠿ ← →`). Keep the
`aria-hidden` attributes that are already on those spans.

## Shell layout

```
.shell (grid: auto auto 1fr)
├── .rail        56px collapsed / 208px expanded — brand mark, 5 nav items, footer (theme toggle)
├── .data-panel  320px — persistent Data Explorer, collapsible to a strip
└── .main        .topbar (section title + subtitle + live status + actions)
                 .content (5 always-mounted section divs, display-toggled)
```

Rail items, in order, each mapped to functionality that genuinely exists:

| Label | Icon | Section |
|---|---|---|
| Migrations | `migrate` | drag-drop + `/migrate/*` job cards |
| AI Command | `chat` | `/chat/plan` → confirm → `/chat/execute` |
| Intelligence | `spark` | transpile / analyze / reconcile runs + verdicts |
| Unity Catalog | `catalog` | `/explore/databricks/*` |
| Logs | `logs` | `/history` + run event logs |

The Data Explorer is **not** a rail item — it is the persistent panel serving both the
Migrations (drag source) and AI Command (data view) surfaces.

Responsive: under `1180px` the data panel collapses to a strip (toggleable); under `860px` the
rail collapses to icons only.

## Change log

Append one line per landed change: date · agent/stage · what changed.

- 2026-08-02 · G17 planning · Initial design system authored. Tokens, patterns, shell layout and
  icon set defined. No components migrated yet.
- 2026-08-02 · G17 shell · `theme.css` created with the four-block theming contract; `Icon.tsx`
  (22 inline-SVG glyphs), `useTheme` (localStorage, dark default), `useSpotlight` (rAF-coalesced
  `--mx`/`--my`) added. `index.css`'s old `:root`/dark token blocks deleted — tokens live in
  `theme.css` only. Shell rebuilt in `App.tsx`: left rail + persistent data panel + main column,
  five sections still always-mounted and display-toggled.
- 2026-08-02 · G17 structure · Trees lifted out of `Explorer.tsx` and `ChatDataExplorer.tsx` into
  a single `DataExplorerPanel.tsx` mounted in the shell; job/batch state extracted to
  `MigrationActions.tsx` (context). `ChatDataExplorer.tsx` deleted — the trees were previously
  mounted twice with divergent state.
- 2026-08-02 · G17 components · `PipelineFlow.tsx` rebuilt as circular nodes with gradient
  connectors and a hero variant. All three trees migrated to `<Icon>` (zero literal glyphs left).
  `DatabricksTree` gained column expansion + UC function listing + source view, reaching parity
  with Redshift. Legacy `.status-pill` restyled onto the new pill language rather than left as a
  second visual system.
- 2026-08-02 · G17 fixes found by real browser testing (not by an agent's self-report):
  `display:none` on the data panel left `.main` inheriting a 0-width grid track — the template
  must drop to two columns when the panel is hidden. Topbar title and status pill collided at
  narrow widths (both intrinsically sized; needed `flex-wrap` + `flex-shrink:0`).
  `.history-row-summary` clipped its status pill; now wraps.

- 2026-08-02 · G17 verification fixes · An independent checker **rejected** the phase on two real
  failures, both fixed and re-verified:
  (a) `DatabricksTree` was still mounted twice — in `DataExplorerPanel` and again in the Unity
  Catalog section — reintroducing the exact duplication Stage 3 removed. The panel's section-open
  state is now controlled from the shell, and the Unity Catalog section renders
  `UnityCatalogView.tsx` (real catalog list + a button that reveals Databricks in the one tree)
  instead of a second tree.
  (b) 13 hardcoded colours remained in `index.css`, including `.object-chip-redshift` painting a
  *Redshift* chip blue. All replaced with tokens; new `--on-accent` covers `#fff`-on-gradient.
  `grep` for hex/`rgb(` in `index.css` now returns nothing.
  Also: last literal glyphs removed from `HistoryList.tsx`; stale "limit fixed at 10" comments
  corrected in both source trees.

- 2026-08-02 · G18 routine chips · `ObjectChips.tsx` now lists routines as well as tables for both
  source systems. Routine chips are visually distinct (boxed `function` glyph on
  `.type-glyph-routine`, dashed border, mono label, no system dot) and have a different click
  contract: they call `onShowSource` instead of `onPick`, so they never send a migrate instruction.
  `ChatPanel` gained a `source` message kind rendering the real fetched body in the existing
  `.code-block .source-code-block` styling — no new code style, and deliberately no
  create-in-destination button. Starburst routine chips are only ever labelled "function" (Trino has
  no stored procedures); `source_available: false` is stated plainly rather than shown as a body.

- 2026-08-02 · G18 · Data Explorer moved out of the shell into the Migrations section (still one
  mount). Rail reduced to Migrations / AI Command / Logs via `HIDDEN_SECTIONS` — hidden, not
  deleted. Logs filters given their own `.history-filters` class after `.batch-toolbar`'s
  `flex-direction: column` collided with them. Chat gained an in-transcript working indicator,
  elapsed counter and surfaced poll failures. Starburst UDF source is now real
  (`SHOW CREATE FUNCTION`) instead of a fabricated stub. Routine chips added; they show source
  only — no create-in-destination affordance, by explicit user decision.
- 2026-08-02 · G18 fixes found while wiring · `StarburstUdf.argument_types` was typed `string[]`
  but the API returns a `str`, so `StarburstTree` called `.join()` on a string — a guaranteed
  runtime crash on expanding the UDFs node. Also: obsolete `.data-panel` responsive rules from
  G17 survived the layout move and, being later in the file, kept the stacked panel at 216px.
  Delete a component's old layout rules when you move it; still-matching CSS is not inert.

- 2026-08-02 · G18 verification · Independent checker PASSED the phase with one concrete
  objection, now fixed: the false "UDF bodies aren't recoverable" claim survived — paraphrased —
  inside a user-facing HTTP 400 body in `main.py`, where a grep for the original phrase didn't
  reach it. When retiring a false claim, search for the *claim*, not the wording, and check
  emitted strings as well as comments.

## G19 — requested design changes (planned, not built)

Recorded 2026-08-02. These are binding intent for the next phase, not current behaviour.

- **Data Explorer belongs in the left rail**, nested under "Migrations" and above "AI Command", as
  an expand/collapse nav item. It is not a column and not a panel. The single-mount rule still
  applies — moving it must not create a second tree instance.
- **Preview is a centre-pane view, never a drawer inside the explorer.** It contains SQL and table
  data as *independently* collapsible parts, with both scrollbars, and must not interfere with
  drag-and-drop. The Logs section's collapse behaviour is the reference.
- **One pipeline on screen at a time.** It currently renders in both the Migrations hero and every
  migration card.
- **Row actions share one line** (`migrate` / `copy data` / eye). `batch migrate schema` sits apart
  from its schema row with refresh beside it.
- **Action labels must be consistent across systems.** Redshift's `migrate` vs Starburst's
  `migrate (fast)` differ only because Starburst has a second, slower LLM path — an implementation
  detail that should not surface as inconsistent button text.

Open design question to answer with a recommendation rather than build: whether chat should list
already-migrated Databricks objects as view-only chips, given migration is always source→Databricks
and the result view already appears after a migration completes.

## Known gaps (do not claim these are done)

- The pre-G17 component rules still sitting above the "G17 component treatment" block in
  `index.css` are overridden rather than deleted. They should be removed as each component is
  fully migrated, otherwise the file keeps growing two competing rule sets.
- `statusMeta.ts` still carries its own `✓ ✗ ○ ◐` text icons for run status; those pills are
  visually unified but not yet on `Icon.tsx`.
- Starburst UDF source remains genuinely unavailable (Trino exposes signatures only). This is an
  upstream limit and must stay surfaced honestly, not faked for symmetry.
- The Databricks explore routes return **502** for an invalid identifier, where **400** would be
  correct. Left alone on purpose: it matches the existing Redshift/Starburst convention, and
  changing one surface in isolation would make the API less consistent, not more.

## G19 — data explorer in the rail, preview in the centre pane (built)

**Data explorer.** Now a `.rail-subitem` nav item rendered inside the Migrations
`<li>`, so it always sits between "Migrations" and "AI Command". The rail widens
`--rail-w` (208px) → `--rail-w-explorer` (372px) while open. Display-toggled,
never unmounted; still the app's only `DataExplorerPanel` mount.

**Preview.** Moved out of the three trees into one centre-pane component,
`PreviewPane.tsx`, mounted once in `.content` above the section content and
driven by a `PreviewProvider` context. The per-tree `PreviewPanel` copies and
the tree-local `SourcePanel` mounts are deleted, not merely bypassed.

- Tables → two independently collapsible sections, **Structure** (real columns +
  types) and **Data** (real rows). Routines → **Source SQL**.
- Both scrollbars live on `.pv-scroll`, never on the page. `.pv-table` uses
  `width: max-content; min-width: 100%` so it scrolls horizontally inside its
  own box; headers are `position: sticky`.
- Esc closes. Carets animate; `prefers-reduced-motion` disables it.

**Honesty note.** The table view shows the real column list, not a reconstructed
`CREATE TABLE`. No backend route returns a source table's DDL, and inventing one
would present fabricated SQL as if the source system had emitted it.

**Build gotcha worth remembering.** `npx tsc --noEmit` in `frontend/` is a no-op:
`tsconfig.json` is a solution file (`"files": []` + project references), so it
type-checks nothing and exits 0. The real check is `npx tsc -b`, which is what
`npm run build` runs.

### G19 follow-ups (built)

- **Refresh parity.** `DatabricksTree` had no refresh control at any level while
  the other two trees had one everywhere. Added at root / catalog / schema, same
  `RefreshControl` + `useRefreshMenu` contract. Its root effect was
  fetch-once (`[]` deps); now guarded on `catalogs === null` so refresh works.
- **Row click opens the preview.** Clicking a table, view, function or procedure
  row opens `PreviewPane` — data for relations, source SQL for routines. The eye
  button is unchanged; this is an additional way in. Carets `stopPropagation`, so
  expanding columns never opens a preview. Drag is unaffected (a real drag
  suppresses the click).
- **Caret hit area** enlarged to ~22×20 with negative margins, so the glyph does
  not move. `.tree-leaf` cursor is `pointer` (`grabbing` while dragging) — the
  old permanent `grab` implied the row was drag-only.
- **Preview data caps at ~5 visible rows** (`.pv-scroll-rows`), rest scroll. All
  fetched rows stay in the DOM, so the "N rows" count remains truthful.
- **Chat fold control** was an unstyled `<button>` rendering as a full-width
  native block. Now a quiet caret + label matching the `▾ Output` disclosure.
  Note: `display: inline-flex` was not enough — the card is a stretched flex
  column, so it needed `align-self: flex-start; width: fit-content`.
- 2026-08-10 · G20 context menus · `ContextMenu.tsx` generalised to
  `useNodeMenu(items)`; `useRefreshMenu` kept as a wrapper so no call site
  changed. Right-click now offers a row's real actions (batch migrate on a
  schema; migrate / view data / copy data on a table) calling the same handlers
  as the inline buttons, which all remain. Menu clamps to the viewport. Four
  bugs fixed — handler moved to `.tree-leaf-row`, item clicks no longer bubble
  into the row's preview `onClick`, the root menu escaped the `display: none`
  `<h3>`, and menu items gained the `!selectMode` guard their buttons have.
- 2026-08-10 · G21 resizable rail · `RailResizer.tsx` + `useRailWidth.ts`. The
  rail publishes an inline `--rail-w-explorer` consumed by the existing grid
  rule; handle is anchored to `.shell`, not the scrolling `.rail`. Drag, arrow
  keys (Shift = coarse), double-click/Home reset, 240px…min(900px, 70vw) clamp,
  `localStorage` persistence. `.data-panel-scroll` deliberately untouched — the
  scrollbar and the resizer solve different problems.
- 2026-08-10 · G22 card fold · `CardFold.tsx` — one shared collapse/expand control in the top-right
  of both `.batch-card` and `.chat-plan-card` (both now `position: relative`, heads padded 34px).
  Icon-only with a state-flipping `aria-label` + `aria-expanded`, 28px hit area. A folded batch card
  keeps its real counts including failures. Fold state is view-local. The chat card's pre-existing
  footer `Collapse` is unchanged; the corner control additionally works on a still-pending plan.
