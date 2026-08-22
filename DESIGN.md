---
name: مقال (Maghal)
description: A calm, right-to-left Persian research tool that turns a chosen source into evidence-grounded lessons.
colors:
  # Normative values below are theme `cobalt`, the default. Three sibling themes
  # (wood, olive, slate) redefine every key. The ROLE is normative, not the hex.
  canvas: "#e3d9cc"
  paper: "#f6efe6"
  paper-raised: "#fffaf3"
  paper-muted: "#f0e7db"
  paper-strong: "#e7dac9"
  ink: "#221f1c"
  ink-soft: "#443c34"
  muted: "#6d6157"
  muted-light: "#776b5f"
  disabled: "#9d9083"
  border: "#d8ccbc"
  border-strong: "#c4b6a4"
  brand: "#1d4268"
  brand-strong: "#14304c"
  header: "#14304c"
  brand-soft: "#a8c1d8"
  brand-line: "#9db2c6"
  brand-wash: "#e1eaf1"
  accent: "#1b3fd0"
  accent-wash: "#e7ebff"
  success: "#35644c"
  success-wash: "#e4eee7"
  warning: "#8d621e"
  warning-wash: "#f4ead4"
  danger: "#8b3728"
  danger-wash: "#f7e3da"
  info: "#315b7d"
  info-wash: "#e2edf4"
  focus: "#1b3fd0"
typography:
  display:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "clamp(24px, 3vw, 35px)"
    fontWeight: 800
    lineHeight: 1.35
    letterSpacing: "-0.045em"
  headline:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "clamp(20px, 2.4vw, 26px)"
    fontWeight: 800
    lineHeight: 1.3
    letterSpacing: "-0.045em"
  title:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.5
  input-large:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.9
  body:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.75
  dense:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  control:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.2
  label:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    lineHeight: 1.5
  caption:
    fontFamily: "Vazirmatn, Tahoma, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "0.03em"
  data:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  control: "6px"
  panel: "8px"
  card: "9px"
  surface: "12px"
  pill: "999px"
  dot: "50%"
spacing:
  tight: "7px"
  row: "11px"
  card: "17px"
  sheet: "22px"
  page: "34px"
components:
  app-header:
    backgroundColor: "{colors.header}"
    textColor: "{colors.paper}"
    height: "66px"
  button-primary:
    backgroundColor: "{colors.brand}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.brand-strong}"
    textColor: "{colors.paper}"
  button-secondary:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    height: "44px"
  input-field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "44px"
  chip-choice:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: "0 13px"
    height: "44px"
  chip-choice-selected:
    backgroundColor: "{colors.brand-wash}"
    textColor: "{colors.brand-strong}"
    rounded: "{rounded.pill}"
  card-surface:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "{spacing.card}"
  notice-panel:
    backgroundColor: "{colors.paper-muted}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "15px 17px"
---

# Design System: مقال (Maghal)

## Overview

**Creative North Star: "میز کار مصحح" — The Editor's Desk**

The interface is a working desk, not a dashboard. Separate sheets of warm paper rest on a tinted surface; each sheet holds one part of the work, and the desk itself is calm enough that the sheets are what you look at. Depth is real but shallow — a sheet sits *on* the desk, it does not float above it — and the only things that genuinely float are the ones the reader summoned.

The tone is calm, literary, research-oriented, and precise. This should feel closer to a serious reading and listening tool than to a SaaS analytics template, and it never advertises "AI" as decoration. The product's job is to refuse when the evidence is thin, so the interface has to make a block read as a considered finding rather than a failure: blocking states get the same typographic care as successful ones.

Persian, right-to-left, is the native direction of this system — not a translation layer applied to a Latin layout. Line length, rhythm, and the placement of every affordance are chosen for RTL first.

**Key Characteristics:**

- Warm tinted neutrals, never pure gray or pure white
- Four peer themes; roles are fixed, hues are not
- Sheets on a desk: hairline borders, one shallow ambient shadow, restrained corners
- One shell for every mode — density may change, colour never does
- Dense information carried by type weight and rules, not by containers inside containers

## Colors

Warm tinted neutrals throughout, with a single reserved accent per theme and a semantic set that never doubles as decoration.

The system ships **four peer themes** — `cobalt`, `wood`, `olive`, `slate` — selected by the reader and stored client-side under `maqaal-theme`. They are equals, not a default plus three skins. Every token below exists in all four; only the values differ. Light is the only colour scheme: there is no dark mode and `color-scheme: light` is declared on every theme.

### Primary
- **Brand** (`#1d4268` in cobalt): the committing action and the active state. Solid primary buttons, the current step in a rail, the focused field's border.
- **Brand Strong** (`#14304c`): the pressed and hovered form of Brand; also link text on paper.
- **Header** (`#14304c` in cobalt, `#4a2a12` in wood): the application shell's ground. Its own role rather than a reuse of Brand Strong, so the shell can be tuned per theme without moving link colour. Wood deliberately runs a burnt brown deeper than its Brand Strong.
- **Brand Wash** (`#e1eaf1`): the quiet fill behind a selected chip or an active row.

### Secondary
- **Accent** (`#1b3fd0`): reserved for *running* — the live pulse on a stage that is executing right now — and for the focus ring. It is not a second brand colour and never appears decoratively.

### Neutral
- **Canvas** (`#e3d9cc`): the desk. The outermost ground, always darker than the sheets on it.
- **Paper** (`#f6efe6`) and **Paper Raised** (`#fffaf3`): the sheets. Raised is the lifted surface of a card; Paper is the page and the inside of a field.
- **Paper Muted** (`#f0e7db`) / **Paper Strong** (`#e7dac9`): quiet fills for notices and for the row that is currently active.
- **Ink** (`#221f1c`): body text.
- **Ink Soft** (`#443c34`): secondary headings and field labels.
- **Muted** (`#6d6157`) / **Muted Light** (`#776b5f`) / **Disabled** (`#9d9083`): supporting copy, metadata, and unreachable states, in that order of recession.
- **Border** (`#d8ccbc`) / **Border Strong** (`#c4b6a4`): the hairline vocabulary. Border separates; Border Strong encloses something interactive.

### Semantic
Each state carries a text-weight colour and a wash: **Success** `#35644c`, **Warning** `#8d621e`, **Danger** `#8b3728`, **Info** `#315b7d`, each with a matching `-wash` fill. These are separate from Brand and Accent and are never borrowed for emphasis. Muted Light and Warning are both darkened from their original theme-extraction values to clear the 4.5:1 AA floor against paper and warning-wash respectively — the audit finding this fixes.

### Named Rules

**The Role, Not the Hue Rule.** Never write a hex in a component. Every colour comes from a role token, because the same component renders in four themes: `--brand` is deep blue in cobalt, warm brown in wood, olive green in olive, and near-black in slate. A design that only reads correctly in cobalt is broken, not themed. The only sanctioned literals are the four theme swatches in the theme picker, which must show each theme's own colour regardless of the active theme.

**The One Shell Rule.** The application shell is identical in every mode. Density may change — the header is shorter in operator mode — but no colour may shift with `data-mode`. Before this rule the header swapped grounds between modes, quiet text swapped hue with it, and header hairlines fell back to a hardcoded brown that ignored the theme entirely; the palette appeared to scramble on every toggle.

**The Reserved Accent Rule.** Accent means *running now*. If a screen shows Accent on something that is not actively executing, either the state is wrong or the colour is.

## Typography

**Body Font:** Vazirmatn (with Tahoma, sans-serif)
**Data Font:** ui-monospace / SFMono-Regular / Menlo — identifiers, hashes, durations, costs, model names

**Character:** One Persian family carries the whole system. Its weight range does the work that a second family would do elsewhere: 400 for reading, 700 for labels and controls, 800 for page titles. The family ships in discrete steps — 400/500/600/700/800 — and 650 is not one of them; a browser silently rounds it to 700, so the system names 700 directly rather than a weight it never actually renders. Digits are `tabular-nums` everywhere, so numbers in a column stay in a column.

### Hierarchy
The ladder is 35 → 26 → 17 → 16 → 15 → 14 → 13 → 12 → 11, and every step below the display size earns its place by carrying a different kind of content.

- **Display** (800, `clamp(24px, 3vw, 35px)`, 1.35, tracking `-0.045em`): the page title, capped at `34ch` and balanced. One per view.
- **Headline** (800, `clamp(20px, 2.4vw, 26px)`, 1.3): the title of one piece of content inside a page — the script's own title, the audio piece, the coverage verdict. Distinct from Display, which names the page itself.
- **Input Large** (400, 17px, 1.9): the composition field where the reader writes the Research Brief. The one place typing gets more room than reading.
- **Title** (700, 16px, 1.5): section headings inside a page.
- **Body** (400, 15px, 1.75): running Persian text.
- **Dense** (400, 14px, 1.6): table cells and stage-row names — the reading size for scanned rather than read content.
- **Control** (700, 13px, 1.2): buttons, header navigation, field hints and field errors. Anything the reader acts on or is corrected by.
- **Label** (700, 12px): field labels, status labels, chips.
- **Caption** (600, 11px, tracking `0.03em`): kickers and peripheral metadata. The floor.
- **Data** (mono, 12px): anything that is an identifier rather than a sentence.

### Named Rules

**The Bidi Isolation Rule.** Identifiers, filenames, timestamps, costs, model names, phone numbers, OTP values, hashes, and URLs are Latin content inside Persian sentences. They carry `dir="ltr"` and bidi isolation, or they will visually reorder the sentence around them.

**The Persian Floor Rule.** Persian script needs more vertical room than Latin at the same nominal size. 11px is the floor of the whole system and it is reserved for genuinely peripheral metadata; anything the reader acts on or is corrected by sits at Control (13px) or above, and running text stays at 15px. *Two declarations currently sit below the floor at 10px — the wordmark's subtitle and the small text inside a status label. Both are findings.*

**The One Display Rule.** A view has one Display, and it names the page. Everything else that wants to be large is a Headline, and Headline has exactly one value. Four separate display-scale clamps once coexisted here, plus a fixed mobile override that fought the clamp; they are now one Display and one Headline.

**The One Family Rule.** Do not introduce a display face. Hierarchy comes from weight, size, and colour. A second Persian family in this system reads as decoration.

## Layout

The document is RTL at the root. The shell is `min(1180px, 100% - 32px)`, centred, with page content padded `30px 34px 42px` and a narrow reading variant of `min(760px, 100%)` for text-heavy views.

Structure comes from whitespace and hairline rules before it comes from containers. A section is separated by a rule and a heading, not by wrapping it in a box; rows in a list share a bottom hairline rather than each becoming a card. Every view keeps one primary action.

Breakpoints are `980px`, `760px`, and `470px`. Below 760px the header navigation moves to its own full-width row and a fixed bottom navigation appears. Because the entire workflow must be completable on a phone, no layout may push a required action off-screen or behind a horizontal scroll — wide content, especially tables, scrolls inside its own `overflow-x: auto` container while the page body never does.

Spacing has recurring steps rather than a formal scale: `7px` inside a control, `11px` between related rows, `17px` inside a card, `22px` inside a form sheet, `34px` at the page edge. *No enforced scale exists yet; the observed set is wider than these five steps and would benefit from consolidation.*

## Elevation & Depth

The system is nearly flat, with exactly **two** shadow steps, and the difference between them carries meaning.

### Shadow Vocabulary
- **Sheet** (`--shadow-soft`: `0 10px 28px -24px` at 45% ink): in-page containers — cards, form sheets, data panels, the audio player, empty states. It is barely perceptible by design. It says "this is a separate sheet on the desk", not "this is elevated".
- **Floating** (`--shadow`: `0 1px 2px` at 7% plus `0 18px 42px -24px` at 38% ink): things that genuinely sit above the page and can be dismissed or scrolled past — the theme menu, the fixed mobile navigation, the sticky confirmation bar, the authentication card.

Both shadows are tinted with the theme's own ink, never neutral black.

### Named Rules

**The Two Steps Rule.** There is no third shadow. Before reaching for a new one, answer whether the element is a sheet or a floater; if it is neither, it needs a hairline, not depth.

**The Floating Test Rule.** A full shadow is earned only by something that overlays page content. If the element scrolls with the page and cannot be dismissed, it gets the Sheet shadow or nothing. This is testable: point at the element and ask whether content passes underneath it.

## Shapes

Corners are restrained and the radius encodes the size of the thing.

- **Control** (6px): buttons, inputs, selects, small menu items
- **Panel** (8px): notices, attention panels, dashed empty inlines
- **Card** (9px): cards, form sheets, data panels, floating menus
- **Surface** (12px): the largest framed regions — the page frame, the authentication card
- **Pill** (999px): chips, status pills, segmented controls, header controls
- **Dot** (50%): status marks and swatches

Borders are the primary separator and they are quiet: 1px, `--border` to separate and `--border-strong` to enclose something interactive. A dashed `--border-strong` marks an inline empty state.

### Named Rules

**The Five Radii Rule.** Six values, listed above, plus the two round ones. Strays currently exist in the stylesheet (`4px`, `7px`, `10px`); they are drift, not vocabulary.

## Components

### Buttons
- **Shape:** Control radius (6px), 44px tall, `0 16px` padding, 13px at weight 700. The height is the accessibility floor from PRODUCT.md, not a style choice.
- **Primary:** Brand ground, Paper text; hover deepens to Brand Strong.
- **Secondary:** Paper Raised ground with a Border Strong outline and Ink Soft text; hover darkens the outline and the text to Ink.
- **Quiet:** transparent until hover, when it takes a Paper Muted ground.
- **Danger:** outlined in Danger by default; the solid variant is reserved for the irreversible action in a confirmation.
- **Motion:** a 1px lift on hover over 120ms, returning to rest on press. No bounce, no elastic easing.

### Fields
- **Style:** Paper ground, Border Strong outline, Control radius, 44px tall, `10px 12px` padding.
- **Focus:** the border moves to Brand and a 2px Brand Wash outline sits outside it at 1px offset.
- **Error:** the border moves to Danger and thickens to 1.5px; the message sits directly beneath the field with an icon, never as a placeholder or a tooltip.
- **Labels** are Label type in Ink Soft and are always real labels.

### Chips (choice groups)
- **Style:** Pill radius, 44px tall, Paper ground with a Border Strong outline and Muted text.
- **Selected:** Brand outline, Brand Wash ground, Brand Strong text at weight 700 — three simultaneous signals, so selection never depends on colour alone.
- The underlying radio input is visually hidden but focusable; focus draws a 2px Focus outline at 3px offset around the chip.

### Cards and panels
- **Corner:** Card radius (9px). **Ground:** Paper Raised. **Border:** 1px Border. **Shadow:** Sheet.
- **Padding:** 17px for a data panel, 22px for a form sheet.
- Never nest a card inside a card. If content inside a card needs separation, use a hairline.

### Status labels
A status is always shape plus colour plus words: a 9px ringed dot, a semantic colour, and a Persian label. The running state fills the dot and pulses it over 1.8s. The pill variant tints its own ground from the current colour via `color-mix`.

### Application header
Header ground, Paper wordmark, Brand Soft quiet text, Brand Line hairlines — identical in every mode, in all four themes. It is sticky, 66px tall (56px in operator density), and carries the brand, navigation, the mode control, the theme picker, and sign-out.

### Stage rail (signature component)
The vertical list of pipeline stages is the component that most defines this product. Each row carries a mark, a name, and a state word. The complete row fills its mark with Brand; the pending row recedes to Disabled at weight 400; the current row takes a Paper Strong ground, a bolder darker label, a Brand state word, a pulsing Accent mark, and a 3px Brand rail on its leading edge.

### Named Rules

**The Current-Row Rule.** A coloured rail on the leading edge of a row is permitted for exactly one purpose: marking the row the reader is currently on. It must never decorate a card, a panel, or a section, and it is never the only signal — the current row also changes ground, weight, and state word. A rail without that redundancy is decoration and must be removed.

**The Five Signals Rule.** Every state worth showing is carried by at least two of: words, shape, weight, ground, colour. Colour alone never carries state.

## Do's and Don'ts

Accessibility and inclusion commitments — RTL as the native direction, WCAG AA contrast, the 44px minimum target, keyboard-operable OTP entry, labels that are never placeholders — live in PRODUCT.md and bind this system. They are not repeated here.

### Do:
- **Do** take every colour from a role token so the component survives all four themes.
- **Do** separate with whitespace and a hairline before reaching for a container.
- **Do** keep one primary action per view.
- **Do** give blocking and refusal states the same typographic care as success states — a block is a finding, not an error.
- **Do** wrap Latin identifiers in `dir="ltr"` with bidi isolation inside Persian sentences.
- **Do** put wide tables in their own `overflow-x: auto` container.
- **Do** use functional motion only: 120–180ms opacity and position transitions, no bounce, no elastic easing.

### Don't:
- **Don't** use purple or blue gradients, glow effects, or glassmorphism.
- **Don't** place generic AI illustrations or rounded-square icon tiles above headings.
- **Don't** nest cards inside cards.
- **Don't** open a view with a large empty hero.
- **Don't** show fake progress, invented percentages, or fabricated activity. Progress is computed from real stages and units or it is not shown.
- **Don't** draw decorative charts with no decision attached to them.
- **Don't** use low-contrast gray text; the neutrals are tinted and each has a defined recession role.
- **Don't** build an English-first layout and translate it into Persian.
- **Don't** let any colour change with `data-mode`.
- **Don't** animate a loading percentage unless its units are real.
- **Don't** kill all motion for `prefers-reduced-motion` without leaving an alternative signal. The reduced-motion rule is scoped to the one looping animation in the system (the running pulse); it freezes the mark at full opacity rather than removing it, and the system's brief, non-looping functional transitions keep running.
