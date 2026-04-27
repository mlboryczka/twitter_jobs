---
name: Twitter Jobs
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#3f4851'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#6f7883'
  outline-variant: '#bfc7d3'
  surface-tint: '#00629d'
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
  primary-fixed: '#cfe5ff'
  primary-fixed-dim: '#99cbff'
  on-primary-fixed: '#001d33'
  on-primary-fixed-variant: '#004a78'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffdada'
  tertiary-fixed-dim: '#ffb3b6'
  on-tertiary-fixed: '#40000c'
  on-tertiary-fixed-variant: '#920028'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
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
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  container-max: 1280px
  gutter: 20px
---

## Brand & Style
The design system is built for high-velocity decision-making and professional clarity. It targets recruiters and hiring managers who require an interface that minimizes cognitive load while providing a premium, reliable experience. 

The style is **Modern Minimalist** with a focus on functional aesthetics. It utilizes plenty of whitespace to separate information-dense job listings, while employing subtle depth cues to guide the user's focus toward primary actions. The interface should feel light and airy, yet structured enough to handle complex data triage.

## Colors
This design system uses a curated palette designed for legibility and intent. 
- **Primary Blue:** A vibrant, saturated blue used for brand presence and main navigational actions.
- **Emerald Green:** Reserved for "Accept," "Shortlist," and "Success" states, providing a positive reinforcement.
- **Soft Ruby:** Used for "Dismiss," "Reject," or "Error" states, balanced to be visible without being overly aggressive.
- **Neutrals:** The background uses a soft off-white to reduce eye strain, while borders use a cool light gray to define boundaries without adding visual noise.

## Typography
The design system relies exclusively on **Inter** to deliver a systematic and utilitarian feel. The hierarchy is established through aggressive weight changes rather than extreme size shifts. Headlines use Semibold and Bold weights with tighter letter spacing for a compact, professional look. Body text prioritizes readability with a generous line height, while labels use Medium or Semibold weights to ensure they remain legible at smaller scales during triage tasks.

## Layout & Spacing
The layout follows a **Fixed Grid** model for the main dashboard to ensure consistency across different screen sizes, centering the triage deck for better focus. 

The spacing rhythm is built on an 8px baseline. Large internal margins (24px+) are used within cards to keep candidate information feeling premium and uncrowded. Components like chips and small buttons use 4px or 8px increments to maintain a tight, interactive feel.

## Elevation & Depth
Depth is created through a combination of **Tonal Layers** and **Ambient Shadows**. 
- **Level 0 (Background):** The soft off-white surface (#F9FAFB).
- **Level 1 (Cards/Surface):** Pure white (#FFFFFF) with a 1px border (#E2E8F0) and a very soft, high-diffusion shadow (0px 2px 4px rgba(0,0,0,0.02)).
- **Level 2 (Interactive/Hover):** Buttons and active chips use a slightly more pronounced shadow (0px 4px 12px rgba(0,0,0,0.05)) to suggest "squish" and tactility.
- **Level 3 (Overlays):** Modals and dropdowns use a deep, soft shadow to clearly separate them from the triage stack.

## Shapes
The design system adopts a **Rounded** shape language to soften the analytical nature of the tool. 
- Standard components (Inputs, Cards) use a **0.5rem (8px)** radius.
- Large containers use **1rem (16px)** for a modern, nested appearance.
- Interactive elements like tags and buttons use a **Pill-shape** (fully rounded) when they represent discrete, draggable, or high-action items, contrasting against the more structural rectangular cards.

## Components
- **Buttons:** Primary buttons are vibrant blue with white text and a subtle 2px bottom "lift" shadow. Success and Dismiss buttons use the Emerald and Ruby palettes respectively, with low-opacity background tints for secondary states.
- **Chips:** These are pill-shaped with a light-gray stroke and a subtle elevation. Status chips use the primary, success, or ruby colors with a 10% opacity background and 100% opacity text.
- **Triage Cards:** The core component. Features a white background, 1px light gray border, and ample padding. Profiles are clearly segmented with a thin horizontal rule.
- **Input Fields:** Use the soft off-white background with a slightly darker border. On focus, the border transitions to the primary blue with a soft glow effect (focus ring).
- **Lists:** Clean, borderless rows with subtle hover states that change the background to a faint gray to indicate interactivity.