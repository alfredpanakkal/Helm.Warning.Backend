# Implementation Plan: Companion Frontend Discovery Prompt & Integration Specs

## Overview
You are coordinating two AI Studio applications for the Helm.Warning Maritime Safety Information (MSI) platform:
1. **This Backend System:** NAVAREA pipeline, coordinate parser, geometry generator, admin verification queue, security middleware, and Supabase database.
2. **The Other Frontend App:** The dedicated frontend interface communicating with this system via direct connection to the shared Supabase database and storage.

This plan details the structured prompt to deliver to your other AI Studio app's chat to extract its exact UI design system, map layer architecture, user interaction models, and Supabase query dependencies.

---

## Plan Structure

### 1. In-Depth Prompt Formulation for the Companion AI Studio Chat
We will provide a tailored, highly specific engineer-to-engineer prompt for you to paste into the companion frontend project. The prompt instructs the other AI Studio model to:
- **UI Design System Breakdown:**
  - Color palette (hex codes for backgrounds, surfaces, borders, text, and hazard accents).
  - Typography, layout grids, density tokens, and responsive breakpoints.
  - Component hierarchy (drawer layouts, tables, modals, cards, badges, and toggle switches).
- **Map & Spatial Layer Architecture:**
  - Mapping engine (Leaflet, MapLibre, OpenLayers, etc.) and tile provider configurations.
  - Layer hierarchy (base layers, seamark overlays, bathymetry, coordinate grids).
  - Geometry rendering rules (points, linestrings, bounding polygons, radius circles, and cluster markers).
  - Hazard severity coloring logic and SVG stroke/fill rules.
- **User Interaction & Bidirectional Sync:**
  - Map-to-list synchronization (marker selection opening drawers/accordions).
  - List-to-map synchronization (hover/click centering, panning, bounding box fitting).
  - Filter and search interactions (NAVAREA numbers, hazard status, date ranges, text queries).
- **Supabase Integration Schema:**
  - Supabase client initialization (environment variable names, anon key usage).
  - Tables queried (e.g., `public.nav_warnings`, `public.sources_registry`, `public.ingestion_generations`).
  - Expected column names, types, enum states, and storage bucket access.

### 2. Output Formatting & Quick-Copy Delivery
- Present the prompt ready to copy-paste directly into your other AI Studio conversation.
- Include instructions on how to take the resulting report back here so both apps remain aligned.

---

## User Review
Please review the plan above and click **Proceed** to generate the discovery prompt.
