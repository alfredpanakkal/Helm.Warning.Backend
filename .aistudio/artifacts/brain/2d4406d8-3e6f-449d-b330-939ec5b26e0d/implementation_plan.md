# Standalone Offline Test Suite (`test.html`) Implementation Plan

A single, fully self-contained HTML file containing both a Public Index view and an Admin Dashboard view, featuring every major HTML5 semantic element, a comprehensive form suite, data tables, interactive widgets, and embedded CSS styling designed for complete offline testing.

## User Review & Confirmed Choices

> [!NOTE] 
> Confirmed user choices from Phase 1 interview:
> - **Visual Theme**: Standard modern dark slate / navy aesthetic embedded directly within CSS `<style>` tags.
> - **Sample Data & Content Domain**: Default system testing, elements showcase, and operational dashboard items with real HTML5 semantics (no mock external dependencies).

---

## 1. Overview & Core Concept

- **What It Does**: Provides an offline-ready single-file HTML environment (`test.html`) that developers and QA testers can download and open directly in any standard browser. It features a vanilla JavaScript view toggle between a Public Index and an Admin Dashboard.
- **Key Capability**: Complete coverage of all HTML5 semantic layout tags, interactive form inputs, data tables, feedback meters, and modal dialogs with zero external network requests or stylesheet dependencies.

---

## 2. User Experience & Visual Design

- **Dual View Layout**:
  - **Public Index View**: Showcases public semantic layout elements (`<header>`, `<main>`, `<aside>`, `<article>`, `<figure>`, typography tags, interactive `<details>/<summary>` FAQ, feedback meters, and public contact forms).
  - **Admin Dashboard View**: Showcases high-density data tables (`<table>`, `<thead>`, `<tbody>`, `<tfoot>`), filter bars, action bars, complete HTML5 input forms, interactive `<dialog>` modals, and quick control widgets.
- **Top Bar View Switcher**: A sticky 3-zone header featuring the brand title, navigation, and a high-contrast view toggle button (`Index View` | `Admin View`).
- **Visual Styling & Embedded CSS**:
  - Dark Slate Canvas (`#0F172A`) with cool surface containers (`#1E293B`) and crisp borders (`#334155`).
  - High-contrast text (`#F8FAFC`) with emerald accent highlights (`#10B981`) for active views and primary actions.
  - Fully responsive grid layout adapted for desktop and mobile viewports.

---

## 3. Key Product Decisions & Trade-Offs

- **Single Self-Contained File Output**: All CSS styles reside within `<style>` tags in `<head>`, and all interaction handlers reside within `<script>` tags at the bottom of `<body>`. No external CSS frameworks (Tailwind/Bootstrap CDN) or JS libraries are linked, ensuring 100% offline reliability.
- **Vanilla JS View Switching**: Uses simple class toggling (`.view-active` vs `.hidden`) to switch between `<section id="index-view">` and `<section id="admin-view">` instantly without reloading the page.
- **Native `<dialog>` Element**: Utilizes browser-native `showModal()` and `close()` methods for zero-dependency interactive popups.

---

## 4. Technical Architecture & Component Structure

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Top Navigation Bar                              │
│  [ Brand Title ]              [ View Switcher: Index | Admin ]         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
┌──────────────────────────────┐          ┌──────────────────────────────┐
│     Section: Index View      │          │     Section: Admin View      │
│  - Semantic Layout           │          │  - High-Density Data Table   │
│  - Typography Suite          │          │  - HTML5 Form Suite          │
│  - Feedback <progress/meter> │          │  - Modal <dialog> Popups     │
│  - Interactive <details>     │          │  - Live Input Echo & Controls│
└──────────────────────────────┘          └──────────────────────────────┘
```

### Complete HTML5 Element Inventory Included:
1. **Semantic Layout**: `<header>`, `<main>`, `<aside>`, `<footer>`, `<nav>`, `<section>`, `<article>`, `<figure>`, `<figcaption>`
2. **Form Elements**: `<form>`, `<fieldset>`, `<legend>`, `<label>`, `<input>` (text, number, email, password, tel, url, date, time, datetime-local, month, week, color, range, checkbox, radio, file, hidden, search), `<select>` with `<optgroup>`, `<textarea>`, `<datalist>`, `<button>`
3. **Data Tables**: `<table>`, `<thead>`, `tbody`, `<tfoot>`, `<tr>`, `<th>`, `<td>`, `<caption>`
4. **Interactive & Feedback**: `<details>`, `<summary>`, `<dialog>`, `<progress>`, `<meter>`
5. **Text Formatting**: `<h1>`-`Sockets`, `<p>`, `<blockquote>`, `<pre>`, `<code>`, `<kbd>`, `<samp>`, `<mark>`, `<small>`, `<sub>`, `<sup>`, `<time>`, `<abbr>`, `<del>`, `<ins>`, `<address>`
