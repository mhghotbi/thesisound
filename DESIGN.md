# Thesisound Design Direction

## Character

Calm, literary, research-oriented, and precise.

The interface should feel closer to a serious reading and listening tool than a SaaS analytics template. It should not advertise “AI” as decoration.

## Anti-references

Avoid:

- purple/blue gradients;
- glow effects;
- glassmorphism;
- generic AI illustrations;
- card-inside-card dashboards in Simple Mode;
- rounded-square icon tiles above headings;
- large empty hero sections;
- fake progress and fake activity;
- low-contrast gray text;
- decorative charts without a decision attached;
- English-first layouts translated into Persian.

## Layout

- Root document is RTL.
- Simple Mode uses a narrow reading column, not a dashboard grid.
- Operator Mode may use denser tables and split panes.
- Keep one primary action per view.
- Use whitespace and rules before introducing containers.
- Borders are quiet; shadows are exceptional.
- Border radius is restrained.

## Typography

Primary Persian typeface: Vazirmatn.

- Body: 16px / 1.9
- Small: 13px / 1.7
- H1: 30px / 1.35
- H2: 22px / 1.45
- H3: 17px / 1.55

Identifiers, filenames, timestamps, costs, model names, phone numbers, OTP values, hashes, and URLs use bidi isolation and `dir="ltr"` when appropriate.

## Color

Use tinted neutrals rather than pure gray.

- Paper: `#f7f5ef`
- Surface: `#fffdf8`
- Ink: `#17231d`
- Muted: `#66736b`
- Rule: `#d9ddd7`
- Accent: `#176b4d`
- Accent quiet: `#e7f1eb`
- Warning: `#9a5b16`
- Warning quiet: `#fff3df`
- Danger: `#a33b32`
- Danger quiet: `#fbe9e6`
- Info: `#315b74`
- Info quiet: `#e9f1f5`

Color is never the only carrier of state.

## Components

- `AppHeader`
- `StepRail`
- `ProjectRow`
- `StatusLabel`
- `AttentionPanel`
- `Field`
- `PrimaryButton`
- `SecondaryButton`
- `SourceRow`
- `SourceStatus`
- `ImpactSummary`
- `TechnicalDetails`

## Motion

Use only functional motion:

- 120–180ms opacity/position transition;
- no bounce or elastic easing;
- respect reduced-motion;
- avoid animated loading percentages unless units are real.

## Accessibility

- visible focus ring;
- 44px minimum interactive height;
- form errors next to fields;
- semantic headings;
- labels are not placeholders;
- status includes text and icon;
- keyboard-operable OTP inputs;
- WCAG AA contrast target;
- no reliance on hover.
