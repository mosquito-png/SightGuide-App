---
name: SightGuide AI
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1b1b1b'
  surface-container: '#1f1f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353535'
  on-surface: '#e2e2e2'
  on-surface-variant: '#c4c7c8'
  inverse-surface: '#e2e2e2'
  inverse-on-surface: '#303030'
  outline: '#8e9192'
  outline-variant: '#444748'
  surface-tint: '#c6c6c7'
  primary: '#ffffff'
  on-primary: '#2f3131'
  primary-container: '#e2e2e2'
  on-primary-container: '#636565'
  inverse-primary: '#5d5f5f'
  secondary: '#c6c6cb'
  on-secondary: '#2f3034'
  secondary-container: '#46464b'
  on-secondary-container: '#b5b4ba'
  tertiary: '#ffffff'
  on-tertiary: '#303032'
  tertiary-container: '#e4e2e4'
  on-tertiary-container: '#656466'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e2e2e2'
  primary-fixed-dim: '#c6c6c7'
  on-primary-fixed: '#1a1c1c'
  on-primary-fixed-variant: '#454747'
  secondary-fixed: '#e3e2e7'
  secondary-fixed-dim: '#c6c6cb'
  on-secondary-fixed: '#1a1b1f'
  on-secondary-fixed-variant: '#46464b'
  tertiary-fixed: '#e4e2e4'
  tertiary-fixed-dim: '#c8c6c8'
  on-tertiary-fixed: '#1b1b1d'
  on-tertiary-fixed-variant: '#474649'
  background: '#131313'
  on-background: '#e2e2e2'
  surface-variant: '#353535'
typography:
  display-core:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: 0em
  body-xl:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '400'
    lineHeight: 30px
    letterSpacing: 0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
    letterSpacing: 0.01em
  label-bold:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '700'
    lineHeight: 20px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  margin-mobile: 24px
  margin-desktop: 64px
  gutter: 16px
  touch-target-min: 56px
---

## Brand & Style

The design system is built on the philosophy of **Empathetic Minimalism**. It merges the precision of high-end industrial design with the warmth of human-centered accessibility. The objective is to provide a UI that feels like a premium physical tool—reliable, tactile, and calm—rather than a flickering digital screen.

The aesthetic follows a **Sophisticated Modernist** approach:
- **Minimalism:** Aggressive reduction of visual noise to focus on clarity and high-contrast information.
- **Human-Centered:** Large touch targets and high-legibility type scales designed specifically for users with varying degrees of visual impairment.
- **Futuristic Texture:** Subtle use of depth and tonal layering to give the interface a "solid" feel, moving away from flat web conventions toward a more premium, device-like experience.
- **The Core:** An iconic, fluid "SightGuide Core" serves as the visual heartbeat of the AI, using soft organic motion rather than flashy animations.

## Colors

This design system utilizes a **High-Contrast Monochromatic** palette. The default mode is **Dark**, providing a deep black canvas that reduces eye strain and maximizes the "pop" of essential information for users with light sensitivity.

- **Primary (Pure White):** Used for critical text and primary icons to ensure WCAG AAA compliance.
- **Secondary (Cool Grey):** Reserved for secondary information and disabled states.
- **Tertiary (Charcoal):** Used for container backgrounds and surface elevation.
- **Neutral (Deep Black):** The base background color to provide infinite depth.
- **Accent (Subtle Silver):** Used sparingly for "The Core" and premium highlights to indicate active AI processing.

## Typography

Typography is the primary interface element. We use **Inter** for its exceptional legibility and systematic grit. 

- **Scale:** All font sizes are intentionally oversized to accommodate users with low vision.
- **Contrast:** Text should almost always be Pure White (#FFFFFF) on Deep Black (#000000) or Charcoal (#1C1C1E).
- **Letter Spacing:** Increased slightly for body text to prevent "crowding" of characters, improving readability at high zoom levels.
- **Hierarchy:** Use font weight rather than color to distinguish importance, ensuring that even if a user perceives color poorly, the structural hierarchy remains clear.

## Layout & Spacing

The layout is **Fluid and Contextual**, prioritizing vertical flow and massive interaction areas. 

- **The 8px Rhythm:** All spacing and sizing must be multiples of 8px.
- **Margins:** Generous 24px side margins on mobile prevent accidental edge-taps and provide a "frame" for the content.
- **Touch Targets:** A minimum height of 56px for all interactive elements to ensure ease of use for motor-impaired or visually impaired users.
- **Safe Zones:** Content is centered vertically in many views to keep the most important information in the "active zone" of the thumb and eye.

## Elevation & Depth

To maintain a premium, industrial feel, depth is created through **Tonal Layering** and **High-Contrast Outlines** rather than traditional fuzzy shadows.

- **Surface Levels:** 
  - Level 0: Pure Black (Background)
  - Level 1: Charcoal #1C1C1E (Primary Containers)
  - Level 2: Soft Grey #2C2C2E (Raised Elements/Buttons)
- **Borders:** Every interactive card or container uses a 1px solid border (#3A3A3C) to define its edges against the black background.
- **Glassmorphism:** Used exclusively for the navigation bar or "The Core" overlay, with a heavy backdrop blur (20px+) and low opacity (10-15%) to maintain context without sacrificing legibility.

## Shapes

The shape language is **Soft-Geometric**. We avoid sharp corners to keep the vibe approachable and "organic."

- **Standard Elements:** 0.5rem (8px) for buttons and small cards.
- **Main Containers:** 1rem (16px) for large message blocks and image previews.
- **Interaction Orbs:** Fully rounded (pill/circle) for voice activation triggers and status indicators.
- **The Core:** A perfect circle that pulses subtly, representing the AI’s "presence."

## Components

- **The SightGuide Core:** A centered, circular orb. When listening, it should exhibit a slow, "breathing" scale animation. When processing, a subtle silver inner glow rotates.
- **Message Blocks:** Use high-contrast Charcoal backgrounds with Pure White text. Borders should be visible and clearly define the start and end of the AI’s speech.
- **Primary Buttons:** High-contrast White background with Black text. This "inverted" look signifies the most important action.
- **Secondary Buttons:** Charcoal background with White text and a 1px Silver border.
- **Status Indicators:** Minimalist dots. Use a "Silver" dot for active, and "Dark Grey" for inactive. Avoid using green/red as the sole indicator for status.
- **Input Fields:** Large, 64px height fields with 2px borders when focused. Focus states must be extremely prominent (Pure White border).
- **Haptic Integration:** Every component interaction should be paired with distinct haptic feedback patterns to reinforce the visual state change.