---
name: OpenKerf
description: A browser interface for a laser cutter, built like a measuring instrument on the workbench.
colors:
  coolant-teal: "#0c7079"
  coolant-teal-ink: "#ffffff"
  stop-red: "#c93124"
  stop-red-solid: "#c62a1e"
  amber-caution: "#7f5900"
  amber-caution-solid: "#b8860b"
  ready-green: "#2a733f"
  floor-grey: "#f6f7f8"
  panel-white: "#ffffff"
  raised-grey: "#eef0f2"
  bed-white: "#ffffff"
  hairline: "#d6dade"
  hover-veil: "rgb(0 0 0 / 0.05)"
  edge-on-color: "rgb(0 0 0 / 0.22)"
  ink: "#1b1f24"
  ink-muted: "#5b6470"
  layer-1: "#E5484D"
  layer-2: "#F76B15"
  layer-3: "#FFC53D"
  layer-4: "#0F9B32"
  layer-5: "#12A594"
  layer-6: "#0090FF"
  layer-7: "#8E4EC6"
  layer-8: "#E93D82"
  layer-9: "#8D6E63"
  layer-10: "#607D8B"
typography:
  headline:
    fontFamily: "IBM Plex Mono, ui-monospace, SF Mono, monospace"
    fontSize: "24px"
    fontWeight: 400
    lineHeight: 1.1
    fontFeature: "'tnum'"
  figure:
    fontFamily: "IBM Plex Mono, ui-monospace, SF Mono, monospace"
    fontSize: "18px"
    fontFeature: "'tnum'"
  title:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  help:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.06em"
  value:
    fontFamily: "IBM Plex Mono, ui-monospace, SF Mono, monospace"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "'tnum'"
rounded:
  sharp: "2px"
  field: "6px"
  card: "10px"
  dot: "999px"
spacing:
  "1": "4px"
  1h: "6px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "6": "24px"
  "8": "32px"
components:
  button:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "8px 16px"
  button-hover:
    backgroundColor: "{colors.raised-grey}"
  button-primary:
    backgroundColor: "{colors.coolant-teal}"
    textColor: "{colors.coolant-teal-ink}"
    rounded: "{rounded.field}"
    padding: "8px 16px"
  button-danger:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.stop-red}"
    rounded: "{rounded.field}"
    padding: "8px 16px"
  button-danger-hover:
    backgroundColor: "{colors.stop-red-solid}"
    textColor: "{colors.coolant-teal-ink}"
  button-stop:
    backgroundColor: "{colors.stop-red-solid}"
    textColor: "{colors.coolant-teal-ink}"
    rounded: "{rounded.field}"
    padding: "8px 16px"
  button-ghost:
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "8px 16px"
  button-ghost-hover:
    backgroundColor: "{colors.hover-veil}"
  button-icon:
    rounded: "{rounded.field}"
    size: "32px"
  button-disabled:
    backgroundColor: "{colors.raised-grey}"
    textColor: "{colors.ink-muted}"
  button-mini:
    rounded: "{rounded.field}"
    padding: "6px 12px"
    height: "32px"
  button-big:
    rounded: "{rounded.field}"
    padding: "8px 16px"
    height: "44px"
  field:
    backgroundColor: "{colors.raised-grey}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "6px 8px"
    height: "32px"
  field-focus:
    backgroundColor: "{colors.panel-white}"
  number-field:
    backgroundColor: "{colors.raised-grey}"
    textColor: "{colors.ink}"
    typography: "{typography.value}"
    rounded: "{rounded.field}"
    height: "32px"
  segmented-on:
    backgroundColor: "{colors.coolant-teal}"
    textColor: "{colors.coolant-teal-ink}"
    rounded: "{rounded.field}"
    padding: "8px 12px"
  chip:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.dot}"
    padding: "0 12px"
    height: "26px"
  badge:
    backgroundColor: "{colors.raised-grey}"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.dot}"
    padding: "1px 8px"
  card:
    backgroundColor: "{colors.panel-white}"
    rounded: "{rounded.card}"
    padding: "16px"
  card-inset:
    backgroundColor: "{colors.raised-grey}"
    rounded: "{rounded.card}"
    padding: "12px"
  listrow:
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "6px 12px"
    height: "36px"
  notice:
    backgroundColor: "{colors.raised-grey}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "8px 12px"
  tab:
    textColor: "{colors.ink-muted}"
    height: "36px"
  tab-active:
    textColor: "{colors.ink}"
  tool-rail-item:
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.field}"
    size: "40px"
  menu:
    backgroundColor: "{colors.panel-white}"
    rounded: "{rounded.card}"
    padding: "4px"
  dialog:
    backgroundColor: "{colors.panel-white}"
    rounded: "{rounded.card}"
    padding: "16px"
  layer-swatch:
    rounded: "{rounded.field}"
    size: "26px"
---

# Design System: OpenKerf

## Overview

**Creative North Star: "The Workshop Instrument"**

OpenKerf is built like a measuring instrument on a workbench, not like a creative app. It
has a quiet grey chassis, one teal for actions, and numbers set in monospace with tabular
figures so they can be read from a metre away without being misread. The design is the
precision. The interface steps back so that three things stand out: the bed with the
work on it, the machine's state, and the values that decide a burn.

The density is that of a tool you work in for hours: a 56px top bar, a 38px action bar
under it, a narrow tool rail on the left, a context panel on the right, and a stage in the
middle with the bed drawn to scale. Most decisions in the system were measured, usually as
a contrast ratio, a pixel size or a number of layers that stay visible. The reasoning is in
`frontend/src/lib/tokens.css`. That file is the only place where colours and sizes appear
as values, and since its component layer it is also the only place where the shared
patterns (field, label, help, card, list row, chip, badge, notice, empty state, icon,
button, fold, ask row) are drawn.

There is one theme, light. The system serves two scenes with it: the desk, with a mouse,
and the tablet beside the machine, possibly with gloves and in poor light. Below 1200px
the type scale moves up one step, and below 1200px or on a coarse pointer every target
becomes at least 44px.

**Key Characteristics:**
- Plain and precise: hairline borders, 6px corners, flat at rest.
- One accent (Coolant Teal) for actions and choices; red only for stopping and destroying.
- Numbers always in IBM Plex Mono with tabular figures; words in IBM Plex Sans.
- The bed is the brightest surface; the stage around it is decoration.
- Every shared pattern is drawn once, in `tokens.css`, and guard tests refuse a second
  drawing.
- Touch is first-class: 44px targets and a larger type scale on tablets.

## Colors

The palette is a cool, neutral light grey with one teal for actions, a red reserved for
stopping, and ten layer colours that work as identification, not decoration.

### Primary
- **Coolant Teal** (`coolant-teal`, `--accent`): the colour of an action, of a choice and
  of the machine at work. It is used for the primary button, the chosen segment, the
  active tool's icon, the underline of the current tab, focus rings, checkboxes, links,
  the caret, the busy machine dot and the bar of a running job. It is deep enough to be
  safe as text on every surface (5.09–5.82:1), so there is no separate text shade.
- **Accent tint and edge** (`--accent-tint`, 12% teal; `--accent-edge`, 45% teal into
  the hairline): the one strength of "chosen" for list rows, chips and the active tool.
  Text on a tint stays Ink.

### Secondary
- **Stop Red** (`stop-red` for text and borders, `stop-red-solid` for fills): the stop
  button, alarms, refusals and answers that destroy something. The solid fill reaches
  5.6:1 with white on top, because this is the button that stops the laser.

### Tertiary
- **Amber Caution** (`amber-caution` for text, `amber-caution-solid` for dots, bars and
  washes): paused, unplugged, warnings, `.help.warn`.
- **Ready Green** (`ready-green`): only for the machine being ready and for confirmed
  success.
- **Status tints and edges** (`--ok-tint` 8%, `--warn-tint` 10%, `--danger-tint` 7% over
  Panel White; edges at 40–45% into the hairline): the wash and the 1px border a notice
  or a badge lays under its sentence.

### Neutral
- **Floor Grey** (`floor-grey`, `--surface-0`): the page background.
- **Panel White** (`panel-white`, `--surface-1`): the top bar, action bar, rail, panel,
  status bar, cards, menus, dialogs and buttons.
- **Raised Grey** (`raised-grey`, `--surface-2`): input wells, inset cards, hover fills
  on bordered controls, and every disabled button.
- **Hover Veil** (`hover-veil`, `--hover`): the translucent hover for borderless things
  (ghost buttons, list rows, top-bar chips, stepper buttons), because it works on every
  surface.
- **Bed White** (`bed-white`, `--bed`): the bed; the canvas reads it to judge which layer
  colours come free of it.
- **Hairline** (`hairline`, `--line`): every border and divider.
- **Edge On Colour** (`edge-on-color`): the hairline around an arbitrarily coloured patch,
  such as a layer swatch.
- **Ink** and **Muted Ink** (`ink`, `ink-muted`): reading text and secondary text, both
  at 4.5:1 or more on every surface. Muted Ink is also the placeholder colour.
- **Stage** (`--stage`): a radial gradient behind the bed. It is the only gradient in the
  system, and nothing is measured against it.

The browser's own surfaces wear the palette too: selection is a 22% teal wash with Ink,
the caret and `accent-color` are teal, and the scrollbar thumb is Muted Ink at 45%.

### Layer colours
Ten fixed colours (`layer-1` … `layer-10`) follow the RDWorks/LightBurn convention. They
have been graded for colour-vision deficiencies: the smallest simulated distance between
two layers is at least 28. `readable()` and `inkOn()` in `design.svelte.ts` decide the ink
on top of each.

### Material colours
`--mat-wood`, `--mat-acrylic`, `--mat-leather`, `--mat-cardboard` and `--mat-metal` are
the base colours for material textures. They are material colours, not interface colours.

### Named Rules
**The One Teal Rule.** Coolant Teal means "this is an action", "this is chosen" or "the
machine is working". Do not use it for headings, decoration or reported states such as
"measured" or "in use"; a badge takes its colour from the state, never from the accent.
The colour-for-new-work ring is in Ink because it shows a state, not an action.

**The Stop Wins Rule.** Stop Red never loses contrast, size or position to anything else.
The stop button is the strongest thing in the top bar, keeps its word at every width, and
sits above every dialog.

**The No Grey Lies Rule.** Grey means "nothing to report", so it is only for offline and
unknown. Every other machine state has a colour, defined once in `.machinedot`. The one
deliberate grey on a job is "Last known state": when the controller link is lost, the job
card's phase turns Muted Ink and its bar stops, grey, because the app no longer knows.

## Typography

**Interface font:** IBM Plex Sans (with system-ui, -apple-system, sans-serif)
**Value font:** IBM Plex Mono (with ui-monospace, SF Mono, monospace)

**Character:** Engineering typefaces, with sans for words and mono for numbers. They are
self-hosted from the build (Sans 400/500/600/700, Mono 400/500, 128 KB together), because
a workshop PC often has no network.

### Hierarchy
- **Headline** (Mono 400, 24px, 1.1, tabular): the time remaining on the job in the
  queue. Rare.
- **Figure** (Mono, 18px, tabular): the job percentage in the job card, the number read
  from a distance.
- **Title** (600, 16px, 1.3, −0.01em, balanced): window, card and step titles (`.title`),
  dialog headers, the empty state's line.
- **Body** (400, 14px, 1.45): the base size of the whole app.
- **Help** (400, 12px, 1.5, Muted Ink, max 62ch): a sentence of help (`.help`); the
  caution form is Amber text. Field labels (`.field-label`) are 12px Muted Ink above the
  field.
- **Label** (600, 12px, 0.06em, UPPERCASE, Muted Ink): section headings such as "LAYERS"
  (`.label-section`). Labels are for sections, not for controls.
- **Value** (Mono 400, 14px, tabular figures): every number, unit and coordinate. The
  `.mono` class does this, and number inputs get it automatically.

The scale runs 12 / 14 / 16 / 18 / 24px. Below 1200px it moves one step up (13 / 15 / 18 /
24), with the same steps assigned differently. 12px is by far the most used size; the app
is dense.

### Named Rules
**The Mono Is For Values Rule.** Set a label in mono only when the label is a value: a
number, a coordinate, or somebody's own name (a saved jog position). Set verbs such as
Unlock, Earlier or Cancel in Sans. The status bar follows the same split: X, Y and
percentages in mono, the words around them in the interface face.

**The Fold Is Not A Heading Rule.** Fold lines use sentence case at weight 500 in the
reading colour, with a triangle marker. Uppercase and letter-spacing are only for section
labels.

## Layout

The app is a fixed frame around a stage:

- the **top bar** (56px) for document- and machine-wide things, left to right: brand,
  machine chip (state dot, name, state word), material chip (quiet; dashed and muted
  while empty), a spacer, the project menu (a ghost button holding Import… and Export as
  SVG), a divider, Frame, Stop, Pause or Resume, and the language picker;
- the **action bar** (38px) with frequent verbs as ghost icon buttons in groups split by
  20px dividers;
- the **tool rail** on the left (56px; 84px with a word under each icon below 1200px):
  the modes group at the top, then the windows group pushed to the bottom below a
  hairline divider;
- the **context panel** on the right (360px; `clamp(280px, 38vw, 324px)` on the tablet)
  with a real tablist (Edit · Layers · Job). Prepare job lives only in the Job tab, as
  that tab's single primary;
- a colour strip and the **status bar** (28px) along the bottom.

The bed sits in the middle, drawn to scale with rulers in mm.

Spacing uses a 4px grid: 4 · 6 · 8 · 12 · 16 · 24 · 32. The 6px half-step exists for
fields, chips and list rows. Cards pad 16px (12px inset); bars pad 12px horizontally;
button rows use 8px gaps. Help text stops at a 62ch measure.

Dialogs take one of four widths by what they hold: a question (420px), a form (560px), a
workspace (860px) or a workshop (1120px), never wider than the viewport minus 48px.

**Responsive behaviour.** Desktop is 1200px and up; below 1200px, or on a coarse pointer,
is the tablet layout. On the tablet the top-bar labels collapse to icons except the ones
that drive the machine (Stop, Pause, Resume keep their word; Frame keeps a short one), the
brand mark goes, the action bar wraps onto a second row instead of scrolling, the rail
gets its words and 12px between targets, and the pointer readout leaves the status bar.
Between 1200 and 1499px the wordmark hides and the material name truncates at 10ch. Below
900px the status bar wraps rather than hiding a fact; below 880px the project menu moves
into the rail's menu with its word; below 850px Frame loses its word. Below 720px the
panel folds under the canvas. The top bar never scrolls a button out of reach.

Every question answered with buttons uses one row order (`.ask-actions`): the way out
first, the destructive answer in the middle with 24px of air on both sides, the primary
last and right-aligned.

## Elevation & Depth

Depth comes from tonal layering plus hairlines. Surfaces are flat at rest. There are three
surface steps (floor → panel → raised), and every panel also carries its 1px hairline.
Shadows only appear where something sits on the page as its own object or floats above
the app.

### Shadow Vocabulary
- **Lift 1** (`--lift-1`: `0 1px 2px rgb(16 20 26 / 0.06)`): a barely visible shadow on
  cards that are part of the page (notification cards, the test-grid cards, the setup
  frame).
- **Lift 2** (`--lift-2`: `0 8px 24px rgb(16 20 26 / 0.12)`): dialogs and banners that
  cover part of the app.
- **Float** (`--shadow-float`: `0 8px 24px rgb(0 0 0 / 0.12)`): menus, submenus and pills
  floating on the stage (zoom, camera strip, camera error).
- **Scrim** (`--scrim`: `rgb(16 20 26 / 0.40)`): the veil behind a dialog.

Stacking order is a safety matter: dialog (100) < menu (110) < transport/stop (150) <
alarm (200). The stop button is never covered by a dialog; `tests/stop-reach.test.ts`
measures it.

### Named Rules
**The Flat At Rest Rule.** Nothing lifts on hover. A target that moves while you aim at it
shifts under the cursor. Hover changes fill, border colour or underline thickness only.

## Shapes

Corners are small and functional. 6px (`field`) is used on buttons, inputs, list rows,
notices, swatches and tool items; 10px (`card`) on cards, menus and dialogs; 2px (`sharp`)
on checkboxes and on bars that are not buttons, such as the tab underline; full round
(`dot`) only on status dots, chips, badges and progress bars. All borders are 1px
Hairline. A dashed border means "something belongs here and is not": the empty material
chip and the stop button when there is no machine to stop.

Grouped controls (Segmented, the number stepper) share one outer border, with hairlines
between the parts, and read as one object. Checkboxes and radios are our own drawing,
with a clipped hook rather than a glyph, so there is no OS accent colour anywhere. Icons
are drawn, not typed: one 1.75 stroke with round caps and joins on a 24 grid, at 16px in
text and small buttons and 20px in a toolbar or beside a title (`Icon.svelte`).

The signature motif is the kerf line: a dashed stroke that slowly marches (2s linear). It
runs only on the progress of a running job (`.kerf-anim.job-progress`) and never as
decoration, not on the logo and not under the tabs. It is the one animation that keeps
running with reduced motion, because it reports that the machine is still working.

Motion is otherwise short: 150ms ease-out for state changes, 200ms
`cubic-bezier(0.2, 0, 0, 1)` for panels and dialogs, and 900ms (`--duration-slow`) for
the two things seen across the room, the job start moment and one turn of the machine-
search spinner. Filled buttons change fill and letter in one step, without a background
transition.

## Components

Every component below is plain and precise, and defined once in `tokens.css` or one
shared Svelte component. A component may say where a thing sits, how wide it is and what
it holds; it may not redraw its face.

### Buttons
There is one definition (`.btn`), and `tests/one-button.test.ts` refuses a second.
- **Shape:** 6px corners, a 1px Hairline border, 8px × 16px padding, weight 500, 8px gap
  to an icon. Height comes from the padding on a desk and from `--target-min` (44px)
  beside the machine.
- **Default:** Panel White with Ink text; on hover, Raised Grey.
- **Primary:** a Coolant Teal fill with white ink; on hover `brightness(1.06)`. One per
  surface.
- **Danger (at rest):** Stop Red text with a 45% red border and no fill; on hover the
  solid red fill with white.
- **Stop:** the solid Stop Red fill, white, weight 600, with 16px extra margin so its
  neighbour is 24px away. Without a job it rests as a white button with a red border and
  a red square; with no machine it becomes a dashed, muted button that says where the
  stop is.
- **Ghost:** no border and no fill at rest, the Hover Veil on hover. For verbs that are
  available but not the point of the screen.
- **Icon:** a square of `--icon-btn` (32px desk, 44px touch) holding a 16px icon; its
  name lives in `aria-label` and the tooltip.
- **Disabled:** drained rather than faded: Raised Grey surface and Muted Ink, no brand
  colour left, never `opacity`.
- **Variants:** `mini` (32px, 6×12 padding, 12px text, only where the room is really
  gone), `big` (44px with 16px text, for buttons that start a burn) and `mono` (for labels
  that are values).

### Fields
- **Well:** every text, number and choice input is drawn once under `:where()`: Raised
  Grey, 1px Hairline, 6px corners, 6px × 8px padding, 32px high (44px touch). Number and
  decimal inputs are set in Mono.
- **Hover / Focus:** the border darkens toward Muted Ink on hover; focus gives a 2px teal
  outline at 1px offset, a teal border and a Panel White well.
- **Invalid / Disabled:** `aria-invalid` turns the border Stop Red; disabled turns the
  text Muted Ink.
- **Number field:** a stepper, − [value] + in one well, with hairlines between the parts,
  the value centred in Mono, and the stepper buttons at least 32px square with the Hover
  Veil. The compact form puts a one-letter Mono label beside it and the unit inside it.
  Fields collapse to `min-width: 0` so they never overflow a narrow panel.

### Segmented control
One bordered object with hairline dividers and 12px Muted Ink text. The chosen segment is
filled with Coolant Teal, weight 500, not outlined, so nothing moves when it changes and it
can be seen from a metre away. A disabled chosen segment keeps a Muted Ink fill.

### Chips and badges
- **Chip:** a small choice switched on and off. A 26px Hairline pill on Panel White with
  12px Ink text; on, it takes the accent tint and accent edge while the letter stays Ink.
- **Badge:** a word that reports a state. A Raised Grey pill with 12px/500 Muted Ink; the
  `ok`, `warn` and `danger` forms take their tint, edge and text colour. No hover, never
  the accent.

### Cards, rows and notices
- **Card:** Panel White, 1px Hairline, 10px corners, 16px padding. The inset card is
  Raised Grey without a border at 12px, for a block inside a card. Never a card in a card.
- **List row:** a 36px row (44px touch) at 6px × 12px with 6px corners; the Hover Veil on
  hover; chosen is the accent tint with a 1px inset accent edge and Ink text.
- **Notice:** a sentence about the state of things, boxed so it is not mistaken for help
  (`Notice.svelte`): Raised Grey or a status tint, a 1px border all the way round in the
  status edge, 6px corners, 8px × 12px, 12px text, and a 16px status icon so colour is
  never the only signal. It replaces coloured stripes on the left side.
- **Empty state:** what is missing, why, and the one thing that fills it
  (`EmptyState.svelte`): a 20px muted icon, a Title line, a help sentence and one action,
  left-aligned or centred, within the 62ch measure.
- **Why?:** the reasoning behind a control waits one press away in a fold (`Why.svelte`),
  as a help sentence, so it does not push Start and Stop down the panel.
- **Link:** a text button in teal with a 1px underline at 3px offset that thickens to 2px
  on hover; disabled, Muted Ink without underline.

### Navigation
- **Tabs:** the right panel's tabs share the width equally, 36px high (44px touch), weight
  500 Muted Ink; the current tab is Ink with a solid 2px Coolant Teal underline sitting on
  the row's hairline, inset 16px from the tab's edges. Focus ring sits inside.
- **Tool rail:** 40px items at 6px corners in Muted Ink; hover Raised Grey with Ink. The
  active item gets the accent tint and a teal icon while its word stays Ink for contrast.
  Disabled items are mixed toward the panel. On the tablet the rail is 84px wide with
  76px items, a word under each icon and 12px between targets.
- **Action bar:** groups of ghost icon buttons with 1px gaps, split by hairline dividers,
  and a selection summary in 12px Muted Ink that hides on the tablet.
- **Top-bar chips:** the machine and material chips are borderless 40px targets with the
  Hover Veil; the machine chip stacks name (500) over its state word (12px muted) beside
  an 8px machine dot.
- **Menu:** Panel White, 10px corners, Float shadow, 4px padding, 232–320px wide. Rows are
  32px (44px touch) at 6px × 8px with 6px corners; the keyboard row is Raised Grey; a
  destroying row is Stop Red and its highlight the danger tint; shortcuts sit right in
  12px Muted Ink.

### Dialog
A Panel White window with 10px corners, Lift 2 and a scrim behind it, sized by its `size`
prop (s/m/l/xl). It has a header under a rule (12px × 16px) with a Title and an icon close
button, a body that scrolls at 16px, and a footer under a rule holding the `.ask-actions`
row. The footer is always visible however long the question is.

### Fold
`details.fold`: a CSS triangle marker on the left that turns 90° when open, sentence case,
weight 500, 12px, Ink, and teal on hover. It is 44px high on the tablet.
`tests/one-fold.test.ts` refuses a sixth drawing.

### Machine dot
`.machinedot`: an 8px dot in bars. The colour comes from one shared list of states: grey
for offline and unknown, green for ready, teal for busy, amber for paused or unplugged,
red for alarm. `tests/machine-dot.test.ts` refuses a second list.

### Job card (signature)
The "now" card in the Job tab: a card with the phase as a 16px/600 title, an 8px round
progress bar on Raised Grey and the figures in Mono below. Burning takes the accent edge,
the teal phase word and a teal bar; paused takes the warn tint, edge, amber word and amber
bar. When the controller link is lost the card reads "Last known state" in Muted Ink at
500, the bar turns static grey, and a help line says how long ago it was heard.

### Layer swatch (signature)
A 26px rounded square in the layer colour, with its number on it in ink chosen by
`inkOn()`. Unused swatches show at 55% opacity, so the strip shows at a glance which
colours the design uses. The colour for new work gets a 1px Ink ring outside a 2px Panel
White gap. The swatch never lifts.

## Do's and Don'ts

### Do:
- **Do** take every colour, size, radius and duration from a token in `tokens.css`, and
  measure the contrast before you add one. `tests/one-system.test.ts` refuses a component
  that reads an undefined token or writes a raw value.
- **Do** use the shared faces as they are (`.btn`, the field well, `.field-label`,
  `.label-section`, `.title`, `.help`, `.link`, `.card`, `.listrow`, `.chip`, `.badge`,
  `Notice`, `EmptyState`, `Why`, `Icon`, `details.fold`, `.ask-actions`, `.machinedot`)
  and only say where they sit and how wide they are. `one-system.test.ts` and
  `one-button.test.ts` fail on a local redrawing.
- **Do** set every number in IBM Plex Mono with tabular figures, and format it through
  `Intl`.
- **Do** give a control with its own height `min-height: max(<its own>, var(--target-min))`
  so it reaches 44px under 1200px or on a coarse pointer.
- **Do** keep Stop and Pause labelled at every width.
- **Do** pick a dialog width from `--dialog-s/m/l/xl` through the `size` prop.
- **Do** pair every status colour with an icon or a word.

### Don't:
- **Don't** use Coolant Teal for headings, decoration or reported states.
- **Don't** lift, scale or shift anything on hover or focus.
- **Don't** fade a disabled control with opacity. Drain it to Raised Grey and Muted Ink.
- **Don't** show any machine state other than offline or unknown in grey.
- **Don't** let a dialog or anything else cover the stop button.
- **Don't** run the kerf animation anywhere but the progress of a running job.
- **Don't** put a coloured stripe on the side of a box; use a notice with its tint, edge
  and icon.
- **Don't** type an icon as a glyph (×, ⋯, ›, +); draw it with `Icon.svelte`.
- **Don't** load fonts from the network, and don't let the OS draw a checkbox or accent
  colour.
