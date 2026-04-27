---
name: Twitter Jobs
colors:
  background: '#f8f9ff'
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  surface-variant: '#d3e4fe'
  on-background: '#0b1c30'
  on-surface: '#0b1c30'
  on-surface-variant: '#3f4851'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#6f7883'
  outline-variant: '#bfc7d3'
  primary: '#00629d'
  on-primary: '#ffffff'
  primary-container: '#1d9bf0'
  on-primary-container: '#003050'
  inverse-primary: '#99cbff'
  secondary: '#006c49'
  on-secondary: '#ffffff'
  secondary-container: '#6cf8bb'
  on-secondary-container: '#00714d'
  tertiary: '#be0037'
  on-tertiary: '#ffffff'
  tertiary-container: '#ff5c6f'
  on-tertiary-container: '#630018'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
typography:
  h1:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: -0.01em
  h3:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: '1.4'
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: '1'
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.02em
rounded:
  sm: 0.25rem
  DEFAULT: 0.25rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 20px
  container-max: 1280px
  reading: 820px
shadows:
  card: '0px 2px 4px rgba(0,0,0,0.02)'
  elevated: '0px 4px 12px rgba(0,0,0,0.05)'
  overlay: '0px 12px 32px rgba(0,0,0,0.10)'
  lift: '0px 2px 0px rgba(0,0,0,0.10)'
---

## Brand & Style
The design system is built for high-velocity decision-making and professional clarity. The single user is a non-technical job seeker triaging incoming hiring tweets. The interface must minimize cognitive load while providing a premium, reliable experience.

The style is **Modern Minimalist** with a focus on functional aesthetics. Plenty of whitespace separates information-dense job listings, with subtle depth cues guiding the user's focus toward primary actions. Light and airy, yet structured enough to handle complex data triage.

## Colors
A curated palette designed for legibility and intent.

- **Primary Blue (`primary`):** Vibrant saturated blue used for brand presence and main navigational actions.
- **Emerald Green (`secondary`):** Reserved for "Accept," "Applied," and success states.
- **Soft Ruby (`tertiary`):** Used for "Dismiss," "Reject," and reject states; balanced to be visible without being aggressive.
- **Error (`error`):** Hard error states only — system failures, validation. Not interchangeable with `tertiary`.
- **Neutrals:** Background uses a soft off-white (`background` / `surface`, both `#f8f9ff`) to reduce eye strain. Lines use `outline-variant` to define boundaries without visual noise.

The `-fixed` Material You variants are intentionally **not used** in this system; surface-container ladder + container colors cover all needs.

## Typography
Inter only, system-ui fallback. Hierarchy comes from aggressive weight changes more than size shifts. Headlines use 600/700 with tighter letter spacing for a compact professional look. Body text prioritizes readability with generous line height. Labels use 500/600 weights to remain legible at small scale during triage.

## Layout & Spacing
Layout follows a **fixed grid** model centered to focus the triage deck.

The spacing rhythm is built on an **8px baseline.** Large internal margins (`lg` = 24px or more) inside cards keep job information feeling premium and uncrowded. Components like chips and small buttons use `xs` = 4px or `sm` = 8px to maintain a tight, interactive feel.

Two named container widths:
- `reading` (820px) — used for the inbox and review-queue (the screens where the user reads tweet text).
- `container-max` (1280px) — used for tabular and form-heavy screens (`/all`, `/training`).

## Elevation & Depth
Depth is created through tonal layers and four named shadow tokens:

- **`shadow-card`** `0px 2px 4px rgba(0,0,0,0.02)` — default for resting cards (job rows, filter bar, training form).
- **`shadow-elevated`** `0px 4px 12px rgba(0,0,0,0.05)` — buttons on hover, raised primary actions.
- **`shadow-overlay`** `0px 12px 32px rgba(0,0,0,0.10)` — dropdowns, popovers, modals.
- **`shadow-lift`** `0px 2px 0px rgba(0,0,0,0.10)` — primary buttons get a 2px bottom "lift" to suggest tactility.

Tailwind's default shadow utilities (`shadow-sm`, `shadow-md`, `shadow-lg`) are **not** used in this system; reach for the named tokens above instead.

## Shapes
Rounded shape language to soften the analytical nature of the tool.

- **`rounded-sm` / `rounded`** (4px) — small inline status pills.
- **`rounded-lg`** (8px) — buttons, inputs, dropdowns, secondary cards.
- **`rounded-xl`** (12px) — primary cards (job rows, filter bar, training form, history table).
- **`rounded-full`** — chips, pills, status badges, search input, filter chips, avatars.

## Components

- **TopNav.** Fixed-top, 64px tall (`h-16`), `bg-surface-container-lowest`, `border-b border-outline-variant`, `shadow-sm`. No raw Tailwind `slate-*` references — only brand tokens.
- **Buttons.** Primary buttons are `bg-primary text-on-primary` with `shadow-lift`. Success and Dismiss buttons use `secondary` and `tertiary-container` palettes; for low-emphasis variants use `secondary-container/40` or `tertiary-container/30` backgrounds with full-opacity foreground text.
- **Chips.** Pill-shaped (`rounded-full`) with a 1px border. Status chips use the brand colors with a 30–40% opacity container background and 100% opacity foreground.
- **Cards.** White (`surface-container-lowest`) background, `1px border-outline-variant`, `rounded-xl` (12px), `shadow-card` at rest, `shadow-elevated` on hover, generous internal padding (`p-lg` = 24px).
- **Input fields.** Soft container background (`surface-container-low`), `border-outline-variant`. On focus, border transitions to `primary` with `ring-1 ring-primary` glow. `rounded-lg` (8px).
- **Lists / table rows.** Borderless rows separated by `divide-outline-variant/40`. Subtle hover state changes background to `surface-container-low/30`.
