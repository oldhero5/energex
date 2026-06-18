# Energex S4 — Frontend Experience Design (FUTURE WORK)

**Status:** design brief / future work. Not built in S1.
**Design north star:** [Orano Innovations](https://www.orano.group/experience/innovation/en) by
[Immersive Garden](https://immersive-g.com/projects/orano/) (Awwwards Site of the Month) — immersive,
cinematic, WebGL/Three.js, scroll-driven narrative with stylized (non-photoreal) 3D, motion + sound
design, and gamified interactive beats.
**Relationship to the platform:** this expands the **S4 — Frontend** row of the platform's program
decomposition (the *Energex Unified Platform Design* spec, §1). The headline feature is already locked
there: an `as_of` **time-travel slider** that flags reconstructed vs true vintages.

---

## 0. Repo & licensing boundary (the clean boundary)

The app is **not built in this repo.** It ships from a **separate, PRIVATE repository** and is the
**commercial product**.

```
energex (THIS repo)                    energex-app (SEPARATE, PRIVATE repo)
PolyForm Noncommercial (source-avail)  proprietary / commercial
data platform + analytics + S2 API     the frontend experience (the paid offering)
        │                                          │
        └──────── S2 read API (HTTPS/Tailscale) ───┘
                  as_of first-class; JSON
```

Why this boundary is clean:
- **Open-core monetization.** The noncommercial platform stays free for individuals; the polished
  cross-device app is the paid product, with no license friction between them.
- **Decoupled evolution.** The only contract between the two repos is the **S2 read API** (§5). This
  repo owns/freezes that contract; the private app consumes it. Neither repo imports the other.
- **Security.** The app NEVER touches ArcticDB/MinIO directly — it only calls S2 (`read_as_of`), which
  is the single read seam and the place auth/rate-limiting live.

What lives where: this doc (the brief + the API contract the app depends on) lives here so the
boundary is documented from both sides; **all frontend code lives in the private repo.**

---

## 1. The central design idea: cinematic shell, instrument-grade core

Orano is a *marketing experience* — linear, low data density, scroll-as-gimmick, watch-once. Energex is
a *data application* — high density, used daily, must be fast and legible under pressure. Copying
Orano's scroll-driven linearity onto a trading cockpit would be hostile.

So the product has **two registers**, and the craft is in the seam between them:

- **Lobby (cinematic):** landing, onboarding, narrative explainers. This is where we spend the
  Orano-grade budget — WebGL, motion, sound, scroll storytelling. Goal: make bitemporal
  point-in-time correctness *feel* like the differentiator it is, then drop the user into work.
- **Cockpit (instrument-grade):** the daily analysis surface. Borrow Orano's *craft* (depth,
  typographic confidence, purposeful motion, cinematic data viz, restraint) but NOT its linearity.
  Dense, keyboard-fast on desktop, thumb-fast on phone.

**Borrow vs adapt from the reference:**

| Orano technique | Energex use |
|---|---|
| Stylized (non-photoreal) WebGL 3D | A signature 3D **term-structure ribbon** / vol surface — hero only, never the daily default |
| Scroll-driven narrative | Lobby/onboarding ONLY; the cockpit is non-linear and stateful |
| Gamified "press/drag" beats | Interactive **explainers** — e.g. drag the `as_of` slider to watch a backfill collapse, learning the honesty boundary by doing |
| Motion + sound design | Motion: yes, purposeful + `prefers-reduced-motion`. Sound: off by default (it's a tool) |
| Cinematic pacing | Reserved for transitions that preserve context (`as_of` scrubbing, drill-down), not for gating work |

---

## 2. Design system

- **Mood:** dark, depth, focus. Editorial typography meets instrument panel.
- **Palette:** near-black layered backgrounds with subtle depth gradients; one restrained electric
  accent; **semantic** colors for up/down, contango/backwardation, and a distinct **"reconstructed
  vintage"** warning hue (the honesty boundary made visible). Never rely on red/green alone
  (color-blind safe + iconography/labels).
- **Typography:** confident display face for the lobby; **tabular/monospace numerals** everywhere data
  appears (aligned decimals are non-negotiable for prices/curves).
- **Motion:** 60fps, context-preserving (shared-element transitions, slider scrubbing); fully respects
  `prefers-reduced-motion`.
- **Depth/3D:** used as punctuation, not wallpaper. Default charts are fast 2D; 3D is opt-in for the
  hero surfaces.

---

## 3. Product surfaces (mapped to real Energex data)

| Surface | Data (via S2) | Notes |
|---|---|---|
| Immersive landing / onboarding | — | The Orano-grade moment; explains point-in-time correctness |
| Cockpit / dashboard | watchlist: latest spot, curve snapshot, storage vs band | Entry point for daily use |
| **Futures curve & term structure** | dated futures: contango/backwardation, roll yield | Signature **3D curve-over-time ribbon** (WebGL) |
| Volatility | realized / Parkinson / Garman-Klass | Vol surface; reuse existing analytics |
| Fundamentals | EIA gas storage, crude stocks (vs 5-yr band), NOAA HDD/CDD | Bitemporal — show the vintage |
| Spot prices | FRED WTI / Brent / Henry Hub | Degenerate stream |
| **`as_of` time-travel** | every series, any knowledge time | **Headline interaction** (§6) |
| Agent chat | S3 LangGraph, read-only, threads `as_of` | Renders inline charts |

The Dagster webserver (`:3000`) is the **operator console, not the product** — out of scope for the app.

---

## 4. Cross-device: one app, laptop AND phone

**Strategy — responsive PWA first (recommended).** A single responsive web app, installable as a PWA,
served from the always-on Mac Studio over Tailscale. One codebase covers laptop + tablet + phone,
ships instant updates, installs to the home screen, and works partially offline. A native shell
(Capacitor/React Native wrapper) is a *later* option only if app-store presence or deep native
features are needed — not v1.

**Responsive registers (same data + semantics, device-appropriate interaction):**

- **Laptop/desktop:** multi-pane cockpit, dense grids, hover affordances, **command palette +
  keyboard shortcuts**, multi-chart layouts, the 3D surfaces.
- **Tablet:** two-pane, touch + pointer hybrid.
- **Phone:** single-column card stack, bottom tab nav, **thumb-reachable** controls, progressive
  disclosure (summary card → drill-down). The `as_of` slider becomes a large **touch scrubber with
  snap-to-vintage**; the curve is swipeable; 3D degrades to an interactive 2D small-multiple.

**Performance budget (phones / cellular are the constraint):**
- **Code-split the lobby from the cockpit** so the working surface loads fast; lazy-load Three.js.
- **GPU/DPR detection** → 2D fallback for the 3D surfaces on weak devices; cap pixel ratio.
- **Server-side downsampling/aggregation in S2** (don't ship 1m bars to a phone); virtualized tables,
  windowed time series, optimistic `as_of` scrubbing with client cache.
- **PWA caching** of the last view; **explicitly surface data staleness + the active `as_of`** (this
  doubles as honesty-boundary UX).
- **Accessibility:** WCAG AA, large touch targets, keyboard nav on desktop, reduced-motion + color-safe.

---

## 5. The API contract this repo owns (the seam)

The private app depends ONLY on the **S2 read API** (FastAPI, JSON, `as_of` first-class on every
endpoint — already specified in the platform spec §5.7/S2). This is the boundary to freeze before app
work begins. Indicative surface the app needs:

- `GET /instruments` — symbology catalog (what's available, units, revision mode).
- `GET /curve?commodity=&as_of=` — dated-futures curve as known at `as_of`.
- `GET /term-structure?commodity=&as_of=` — contango/backwardation + roll yield.
- `GET /volatility?instrument=&method=&as_of=` — realized/Parkinson/Garman-Klass.
- `GET /fundamentals?series=&as_of=` — EIA/NOAA with vintage + `reconstructed` flag.
- `GET /spot?instrument=&as_of=` — FRED benchmark spot.
- `GET /series/{id}/vintages` — available knowledge times (drives the time-travel slider).
- `POST /agent` (stream) — S3 chat, threads `as_of`, returns text + chart payloads.

Every response carries the resolved `as_of` and a `reconstructed: bool`. S2 emits Plotly JSON today;
the app should treat that as a **data source** and render natively (lightweight-charts / visx / a 3D
layer) for full control, falling back to Plotly rendering where speed-to-ship matters.

---

## 6. Signature interactions (where Orano craft meets the data)

1. **`as_of` time-travel scrubber (headline).** Cinematic scrubbing through *knowledge time*; the UI
   recolors/badges any series that is a **reconstructed** baseline vs a **true** forward vintage. This
   is the product's differentiator and a direct, visible expression of the platform's crown-jewel
   invariant (bitemporal point-in-time correctness + honesty boundary).
2. **3D term-structure ribbon.** The forward curve swept over time as a stylized WebGL surface — the
   Orano-grade hero, desktop-first, 2D small-multiple fallback on phones.
3. **Narrative onboarding.** Orano-style scroll story that teaches *why* point-in-time correctness
   matters, ending by dropping the user into the cockpit on a live instrument.
4. **Interactive explainer (the "gameplay" analog).** Drag the `as_of` slider on a worked example and
   watch a late backfill collapse into "now" — learning the honesty boundary by doing.

---

## 7. Technical architecture (private app repo)

- **Framework:** recommend **React + Next.js + TypeScript** (largest financial-charting ecosystem,
  hireable, strong PWA/SSR story). *Alternative:* **Vue + Nuxt**, which matches the Orano/Immersive
  Garden lineage — viable, smaller fin-charting ecosystem. **Decide before M1.**
- **3D:** Three.js (react-three-fiber if React) for the hero surfaces.
- **2D charts:** TradingView **lightweight-charts** for time series/candles; **visx**/Plotly for
  analytics. (S2's Plotly JSON is a fallback renderer.)
- **Motion/scroll:** GSAP or Framer Motion; Lenis for smooth scroll in the lobby.
- **Data layer:** TanStack Query with **`as_of` as part of the query key** so time-travel is just
  cache addressing; SSE/stream for the agent.
- **PWA:** Workbox service worker + installable manifest; offline last-view cache.
- **Auth:** Tailscale network-auth for the single-user/always-on phase; add OIDC/app auth when it
  becomes a multi-tenant commercial product.
- **Hosting:** served from the Mac Studio behind Tailscale; CDN/edge optional later.

---

## 8. Phasing (future-work milestones)

- **M0 — Freeze the S2 API contract** (§5). The boundary comes first.
- **M1 — Cockpit MVP:** responsive, 2D charts, working `as_of` slider. Instrument-grade core first.
- **M2 — PWA + phone polish:** offline, touch scrubber, performance budget enforced.
- **M3 — Signature 3D + immersive lobby:** the Orano layer (curve ribbon, narrative onboarding).
- **M4 — Agent chat (S3)** integration.
- **M5 — Commercial hardening:** auth, multi-tenant, billing → the paid product.

---

## 9. Risks & open questions

- **Cinematic vs functional balance.** Mitigation: cockpit-first; the immersive layer is marketing/
  onboarding, never gating daily work.
- **3D performance on phones.** Mitigation: code-split + GPU detection + 2D fallback.
- **Framework choice (React/Next vs Vue/Nuxt).** Decide at M0/M1.
- **Plotly-from-S2 vs native rendering.** Lean native for control; Plotly for speed-to-ship.
- **Auth/multi-tenant** timing as the app turns commercial.
- **Is an immersive layer worth it for a daily tool?** Likely yes for landing/onboarding/sales;
  measure before investing beyond that.

---

### Sources
- [Orano — Immersive Garden project page](https://immersive-g.com/projects/orano/)
- [Orano case study (Studio Immersive Garden, Medium)](https://medium.com/@hello_11138/orano-case-study-36dbb465b6cc)
- [Orano wins Awwwards Site of the Month](https://www.awwwards.com/orano-from-immersive-garden-wins-site-of-the-month-novemeber.html)
