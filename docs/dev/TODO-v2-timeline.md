# zakvaska v2: feeding ribbon and bake-day planner

Written 2026-11-22 from a planning chat with Scott. Same rules as v1: work phase by phase,
each phase ends with its acceptance checks passing, tests green, and a commit. Stop and ask
if anything here is ambiguous. CLAUDE.md conventions (UTC storage, °C/grams in the database,
server-side SVG, no JS build step, archive-never-delete, Alembic for every schema change)
all still apply.

**Before starting:** the working tree has about 1,200 lines of uncommitted changes (units
UI, recipes, measures). Finish and commit that work first, or ask Scott what it is. Do not
build on top of it uncommitted.

## Why

Scott's problem is timing, not technique. He keeps late hours (wakes around 10 am, codes
late at night, no fixed schedule), so a fixed "feed every 12 h" interval keeps landing at
4 am, and a bake day is a chain of steps whose times he can't see in advance. Two tools fix
that, sharing one timing model:

1. **Feeding ribbon:** see each jar's cycle on a timeline, see how bad a late or early
   feed is, and move feeds while the cycle stays aligned.
2. **Bake-day planner:** "if I start now (or want bread by 6 pm), when does each step
   happen, and does that fit my day?", then follow along live.

The key domain fact the design rests on: **the cycle length is controllable.** Peak timing
depends on feed ratio and temperature. At 1:1:1 and 80°F rye peaks in about 4–6 h; at 1:5:5
it takes about 10–14 h. So the app should not just warn about the next feed, it should
*suggest the ratio* that puts the next peak where Scott can be home.

## Phase A: timing model, settings, busy blocks

### A1. `app/services/timing.py` (pure functions, no DB)
- `predict_peak_h(ratio, temp_c, jar_factor=1.0) -> float`, where `ratio` = flour ÷ starter
  (1:5:5 → 5.0). Starting heuristic, clearly marked as such in the code:
  - `peak_h = REF_PEAK_H × (1 + RATIO_K × log2(ratio)) × 2 ** ((REF_TEMP_C − temp_c) / Q_STEP_C) × jar_factor`
  - Constants: `REF_PEAK_H = 5.0` (rye, 1:1:1, 25.5 °C / 78 °F), `RATIO_K = 0.43`,
    `Q_STEP_C = 10.0` (activity roughly doubles per 10 °C). Sanity targets the tests must
    hit within ±15%: 1:1:1 at 78 °F ≈ 5 h; 1:2:2 at 78 °F ≈ 7 h; 1:5:5 at 78 °F ≈ 10 h;
    1:5:5 at 73 °F ≈ 12 h.
  - Clamp `ratio` to 0.5–10 and `temp_c` to 15–35 °C, and say so in the UI if clamped.
- `solve_ratio(target_peak_h, temp_c, jar_factor) -> float`: invert the above, rounded to a
  practical ratio (nearest 0.5), clamped 0.5–10. This powers "feed 1:4:4 now and it peaks at
  13:00 tomorrow".
- `readiness(hours_since_feed, peak_h) -> Band`: piecewise bands, constants at module top:
  - `rising`: before 0.85 × peak
  - `peak` (best): 0.85–1.15 × peak
  - `ok`: 1.15–1.5 × peak (still fine to feed or build a levain from)
  - `past`: 1.5–2.0 × peak (collapsing, sour; feed soon)
  - `hungry`: beyond 2.0 × peak
  Also return a 0–1 score (1 at peak, smooth fall-off) for the curve drawn on the ribbon.
  This is Scott's "parabolic" best-time-to-feed range.
- Unit tests: monotonic (higher ratio → later peak; warmer → earlier), solve/predict round
  trip, band edges, clamping.

### A2. Settings (existing key/value `setting` table)
- `feeds_per_day`: `1` or `2`, default `2`. User-selectable because Scott may share the app.
  Per-jar override (nullable column `jar.feeds_per_day`, migration).
- `default_ferment_temp_c`: used when a feeding has no ambient temperature. Default 26.7 °C
  (80 °F, his proofing box setting).
- `ribbon_span_h`: 24 / 48 / 72, default 48.

### A3. Busy blocks (new table `busy_block`)
- Fields: `label`, `kind` (`recurring` / `once`), recurring: `weekday_mask` + `start_local`
  + `end_local` (may wrap past midnight); once: `start_utc`, `end_utc`; `archived`.
- Settings page section to add/edit them. Seed nothing; Scott's day varies, so ship with an
  empty list and an example in the form placeholder (e.g. "Sleep 02:00–10:00").
- Service `busy_intervals(start, end) -> list[(start, end, label)]`, computed in
  `ZAKVASKA_TZ` and returned in UTC. **Test across the DST change** (first Sunday of
  November and second Sunday of March).

**Accept:** model tests pass; settings and busy blocks save and round-trip; DST tests pass.

## Phase B: feeding ribbon

### B1. Plan for feeds
- A jar's **next planned feed** = last feed + its cycle length, where the cycle length is
  24 h ÷ `feeds_per_day`. The *predicted peak* comes from the timing model using the last
  feed's ratio and temperature (ambient temp, else the default setting), times the jar factor
  (Phase E; 1.0 until then).
- **Moving a feed keeps the cycle aligned:** Scott can move the next planned feed (time
  picker, plus −1 h / +1 h / −30 m / +30 m buttons, HTMX, no drag needed). Every later
  planned feed shifts by the same offset. Store as `jar.schedule_anchor_utc` (nullable,
  migration): the time one planned feed should fall at; later feeds repeat from it.
- **Late feed:** when a feed is logged late, offer two choices on the feed confirmation:
  "Keep my usual times" (next feed stays on the anchor; the app suggests a ratio via
  `solve_ratio` so the peak lands near it) or "Shift my schedule" (anchor moves to the new
  feed time). Default: keep usual times.
- **Ratio suggestion on the Fed-it form:** "Next feed planned at 13:00 → feed about 1:4:4 at
  80 °F to peak around then." Pre-fill nothing automatically; it's advice.

### B2. Rendering
- Server-side SVG like `charts.py` (reuse `PlotBox`/`time_bar` patterns). One ribbon per
  jar on the jar page; stacked ribbons for all active jars on the dashboard, sharing one
  time axis.
- Ribbon contents: hour ticks with local times and day labels, a "now" line, past feeds as
  markers (with ratio), the predicted rise curve after each feed coloured by readiness band
  (rising / peak / ok / past / hungry), planned future feeds as hollow markers, logged
  observations as dots on the curve, and **busy blocks shaded** so Scott can see a planned
  feed landing in "Sleep".
- A planned feed inside a busy block gets a warning badge and a one-click "move to the
  nearest free time" suggestion, with the matching ratio.

### B3. Alerts
- Replace the fixed `feed_interval_room_h` due time with the planned next feed when a plan
  exists; keep the interval as the fallback. Fridge and other states unchanged.
- Alert rows stay derived state (rebuilt by `reconcile`); keep it idempotent.

**Accept:** ribbon renders for both jars at phone and desktop width; moving a planned feed
shifts all later ones; a late feed offers both choices; the alert follows the plan; tests
cover anchor maths and the busy-block overlap.

## Phase C: bake-day planner

### C1. Inputs (`/plan`, and "Plan a bake" on each recipe version)
- Recipe version, starter jar, total flour (default from the version).
- Mode: **Start at** (default: now) or **Bread ready by**.
- Levain: ratio (default 1:2:2), temperature (default setting), amount (from the recipe's
  levain line).
- Kneading: bread maker program + loaf size (durations from `EquipmentCycle`: knead1 + rest +
  knead2), with a "knead only, then I take over" option (Scott's current method), or a manual
  knead duration.
- Final rise: duration estimate (default 2.5 h when the recipe has instant yeast, 5 h when
  starter-only; editable), target "1.5× in the pan".
- Bake: oven, temperature, minutes (from recipe stages if present); cool: default 120 min.

### C2. Steps (generated; recipe stages override where they exist)
Each step has `name`, `duration_min`, `hands_on` (bool), `must_be_home` (bool):
1. Wait for the jar to be in its `peak`/`ok` band, if it isn't at start time (passive).
2. **Build levain** and feed the main jar (hands-on, 10 min).
3. Levain rises to peak: duration from `predict_peak_h` with the levain ratio and temp
   (passive; must be home at the end).
4. Mix and knead (hands-on to load, then machine time).
5. Shape into the greased pan (hands-on, 10 min).
6. Final rise (passive; must be home at the end).
7. Bake (must be home).
8. Cool, then bag (passive; bag step is a 2 min hands-on reminder).

### C3. Output
- A timeline (SVG, same visual language as the ribbon) with clock times on every step
  boundary, busy blocks shaded, and the levain build marked on the jar's readiness curve.
- A step table: start, end, hands-on / must-be-home, conflict flag.
- **Conflicts:** any hands-on step, or the end of a must-be-home step, inside a busy block.
- **"Find a time that works":** search the next 48 h in 15-minute steps for the earliest start
  with no conflicts; show it as a one-click alternative. Also offer "bread ready by" back-
  scheduling (this replaces the v2 "back-scheduling" item in CLAUDE.md).
- A start-time slider (`<input type=range>` + HTMX `hx-trigger="input changed delay:200ms"`)
  so Scott can scrub the start and watch the steps move. No JS build step.

**Accept:** with fixed inputs and a fixed "now", the generated step times match hand-computed
values in tests; conflicts and the earliest-workable search are tested; back-scheduling
produces the same plan as the equivalent forward one.

## Phase D: follow-along

- "Start this bake" on a plan creates a `bake` (status in progress) and `bake_stage_log` rows
  with `planned_start` and `planned_min` filled in (the table already has these columns).
- Bake page gets a **Now** panel: current step, countdown to the next hands-on step, and the
  rest of the timeline. Existing start/end buttons record actual times.
- New `AlertKind.STAGE_DUE`: fires at each hands-on step's planned start (and at the end of
  must-be-home steps), through the same reconcile/acknowledge/snooze path and browser
  notifications as feeding alerts. Migration for the enum.
- "Re-plan from now": when a step runs long or short, shift every later step's
  `planned_start` from the actual time and re-check conflicts.
- When the levain step ends, prompt "Is it at peak?" so the real levain time gets recorded.

**Accept:** a bake started from a plan carries planned times; stage alerts fire and clear;
re-plan shifts later steps; actual times land on the stage logs.

## Phase E: learning each jar

- Add a one-tap **"Peaked now"** button on the jar page and dashboard card (an observation
  with a `peaked=True` flag, migration) so recording the peak costs nothing.
- `jar_factor` = observed peak hours ÷ predicted peak hours, exponentially weighted over the
  last 5 cycles that have a recorded peak, clamped 0.5–2.0. Use the levain-peak prompt from
  Phase D as data too.
- Show it plainly on the jar page: "Old Rye peaks about 20% later than the model expects."
- Until a jar has 3 recorded peaks, label predictions "estimate".

**Accept:** factor tests with synthetic data; the ribbon and planner use the factor.

## Out of scope here
Phone push (ntfy), the ESP32 sensor ingest API, Raspberry Pi deployment: still later.
