# Zakvaska UI facelift — audit and plan

Branch `claude/zakvaska-ui-facelift-3ff063`. Phase 1 of 4: nothing in the app has
changed yet. This is what I found and what I propose; Phases 2–4 wait for a go-ahead.

## Ground rules

- UI layer: templates, `app.css`, `app.js`, and chart geometry
  (`services/ribbon.py`, `services/charts.py`, `services/bakeplan.py` drawing code).
- No changes to models, storage, routes' behaviour, or alert/timing logic.
- Every action possible today stays possible.
- Bakery feel and jar artwork stay. Test suite stays green (it is green now).

## How to look at it

| | |
|---|---|
| Facelift copy | `http://127.0.0.1:8421` (launch config `zakvaska-facelift`) |
| Your real app | `http://127.0.0.1:8420`, untouched |
| Data | `./data/` in this worktree: a read-only snapshot of the live notebook taken 26 Nov. Throwaway; the scheduler is off in the copy so it fires no alerts. |
| Screenshots | `docs/facelift/shots/before/` — 22 screens × 390 / 1280 / 1920, full page, plus `report.json` (page heights, sideways scroll, clipped text). Gitignored: they show your notebook. |
| Re-shoot | `.venv/bin/python scripts/shots.py <label>` |

Screenshots are in the dark theme because the Mac is in dark mode. Light gets the
same treatment in Phase 2.

## Screen inventory

Heights are in screens (page height ÷ viewport height).

| Screen | Route | 390 | 1280 | 1920 |
|---|---|---|---|---|
| Home (shelf, ribbon, jar cards) | `/` | 2.7 | 2.4 | 1.8 |
| Jar detail | `/jars/{id}` | 8.2 | 6.2 | 4.6 |
| Jar new / edit | `/jars/new`, `/edit` | 1.9 | 1.5 | 1.1 |
| Feed a jar | `/jars/{id}/feed` | 2.7 | 2.3 | 1.7 |
| Observe | `/jars/{id}/observe` | 1.5 | 1.3 | 1.0 |
| Recipes list | `/recipes` | 13.0 | 6.4 | 4.8 |
| Recipe version | `/recipes/{id}/v/{n}` | 4.5 | 3.4 | 2.5 |
| Recipe new | `/recipes/new` | 1.9 | 1.4 | 1.0 |
| Recipe edit | `/recipes/{id}/edit` | 5.3 | 2.2 | 1.7 |
| Recipe diff | `/recipes/{id}/diff` | 2.4 | 1.9 | 1.4 |
| Bakes list | `/bakes` | 2.4 | 1.6 | 1.2 |
| Start a bake | `/bakes/new` | 2.5 | 1.0 | 1.0 |
| Bake in progress | `/bakes/{id}` | 6.2 | 6.0 | 4.4 |
| Bake done | `/bakes/{id}` | 4.7 | 4.1 | 3.0 |
| Bake result | `/bakes/{id}/result` | 1.3 | 1.0 | 1.0 |
| Plan a bake | `/plan` | 4.5 | 3.4 | 2.5 |
| Equipment | `/equipment` | 10.4 | 7.3 | 5.4 |
| Settings | `/settings` | 2.9 | 2.0 | 1.5 |
| Backup, About, Compare photos | | 1–3.9 | 1–2.4 | 1–1.8 |

Shared pieces: top bar + section nav, alert banner, footer, card, button (4 sizes),
badge/chip, stats row, form/fieldset, data table, timeline, shelf + jar art, loaf and
bread-maker art, ribbon, bake timeline, rise chart, time bar, cycle bars, photo gallery.

## What is wrong

### 1. Nothing uses width past 1188px

Every page is **pixel-for-pixel the same height at 1280 and 1920**. There is one
column, capped at `--page-max: 1188px`, and the only layout breakpoint that adds a
column is the two-up jar/recipe grid at 640px. At 1920 a third of the screen is
empty margin while the jar page runs 4.6 screens long.

### 2. Charts scale like pictures, so more width makes them worse

The ribbon and bake timeline are drawn in a fixed 360-unit viewBox and stretched to
the container. Stretching scales everything, text and row height included:

- At 1188px wide the type is 3.3× its design size. Jar names in the home ribbon
  render around 28px bold; the chart is ~850px tall for three jars, mostly empty.
- At 390px the same type is ~7px and the axis is unreadable.
- More width buys bigger letters, not more time resolution — the opposite of what
  you want.
- Labels collide: the ratio label (`1:3.3:3.3`) sits under the falling curve;
  on the bake timeline the current stage's name is overprinted by its neighbour
  (`Bulk ferment w…`), and step names cross the midnight rule.

### 3. Jar labels are cut by character count

`jar_art.html` truncates the name at 10 characters and the caption at 11, whatever
the size of the jar. On the shelf today: `One in a M…`, `King Arthu…`. The label has
a font-size floor, so longer names lose letters rather than shrink or wrap.

### 4. The important thing is rarely on the first screen

- **Home** leads with a decorative shelf, then the ribbon, then cards that repeat the
  shelf. All three jars read "Hungry" but you scroll to find the Fed-it buttons at
  390. A **bake in progress does not appear on home at all**.
- **Bake in progress**: 11 stage cards, each with a full-width button and a note
  box, whether done, current or hours away. The weigh-out table — needed at step 3 —
  is below all of them, five screens down.
- **Jar detail**: status, ribbon, next-feed mover, notes, "move it", bakes, photo
  upload, then the timeline. Rarely-used controls (state change, archive, upload)
  sit above the history you actually read.
- **Equipment**: all 12 programs are permanently open edit forms. 7.3 screens to
  look at cycle bars.
- **Recipes**: 36 cards, two-up, each with a stats row and an "Open" button; 6.4
  screens, no filter or search.

### 5. Forms stretch to fill

Fields take equal shares of the row regardless of content: a two-digit temperature
gets a 400px box, and on `/plan` the form occupies a full screen before any result
shows. Cards on `/plan` and `/settings` butt against each other with no gap.

### 6. Phone breakages

- Home: the shelf scrolls sideways and hides the third jar (594px in 358px).
- `/recipes`: the whole page scrolls sideways by 4px.
- `/about`: a `code` span spills 84px past the edge.
- Equipment and recipe tables scroll sideways inside their cards (603px in 324px).
- Section nav takes a second header row; page actions float mid-header.

### 7. The stylesheet is a history, not a system

`app.css` is 2,283 lines in 24 sections named after the feature that added them
("Phase 1: jars", "The ghost jar"…).

| | Distinct values in use |
|---|---|
| Hex colours | 108 (9 are tokens) |
| Font sizes | 30, mixing rem, px and em; several between 6.5 and 9.5px |
| Spacing values | 20 (every px from 1 to 12) |
| Radii | 12 |
| Breakpoints | 6 (520, 560, 620, 639/640, 720) |
| Dark-mode blocks | 6, scattered |

Two unrelated heading styles (`h2` serif, and uppercase `.section-title`) are used
interchangeably inside and outside cards. Buttons come in four heights; the bake
sheet uses full-width ones, everything else doesn't. The file input is unstyled.

## Proposal

### Tokens (one `:root` block, light and dark side by side)

- **Colour**: keep today's palette; name it. Surfaces `--paper`, `--card`,
  `--card-sunk`; ink `--ink`, `--ink-soft`; `--crust` (accent); status `--ok`,
  `--warn`, `--danger`, `--chill` (fridge blue); `--wood-*`; and one **stage palette**
  (`--stage-levain`, `-mix`, `-rise`, `-bake`, `-cool`, `-wait`) shared by the time
  bar, cycle bars, bake timeline and legends, which currently each pick their own.
- **Type**: 6 steps, fluid with `clamp()`: `--text-xs` 12 → `--text-2xl` 30–38.
  Serif display for headings, system sans for the rest, tabular numerals for times
  and weights. Floor of 11px anywhere, charts included.
- **Space**: 4-based scale `--s-1…--s-8` = 4, 8, 12, 16, 24, 32, 48, 64.
- **Radii**: `--r-sm` 6, `--r-md` 10, `--r-lg` 14, `--r-pill`.
- **Shadow**: `--lift-1` (cards), `--lift-2` (sticky bars, popovers).
- **Breakpoints**: 640 (phone → tablet), 1024 (laptop), 1600 (wide). Components
  adapt by **container query**, so a card behaves the same in a side panel as on a
  phone.

### Components

card · panel (card with header/actions slot) · button (primary, quiet, danger; two
sizes) · badge/status · stat · form row (label, control, hint, sized by content:
`--field-num` 8ch, `--field-time`, `--field-text`) · data table (stacks to rows on
phone instead of scrolling) · timeline · disclosure (for rarely-used controls) ·
action bar. The stylesheet is reorganised as tokens → base → layout → components →
screens.

### Layout and navigation

- **Phone**: bottom tab bar for the five sections (thumb reach, frees the header);
  the header keeps brand + the page's own action. A sticky action bar on jar and
  bake pages for the primary action.
- **Laptop**: top bar as now, page actions right-aligned next to the title rather
  than floating in the header.
- **Wide (≥1600)**: page grows to ~1760px and gains a column instead of margins.
- Three page shapes: `page--read` (forms, 720px), `page--work` (main + side panel),
  `page--wide` (charts, full width).

| Screen | Wide layout | Result |
|---|---|---|
| Home | "Now" panel first (next feed per jar with Fed-it, next alert, bake in progress), ribbon full width, shelf as the jar row with status under each jar | cards no longer repeat the shelf; target 1 screen |
| Jar detail | left: status, actions, ribbon, next feed, rise chart · right: timeline, scrolling on its own · state/archive/upload in disclosures | 4.6 → ~1.5 screens |
| Bake in progress | left (sticky): right-now, day timeline, weigh-out · right: running sheet as one timeline, done steps one line each, current step expanded | 4.4 → ~1.5 |
| Plan | left: compact form (sticky) · right: scrubber, timeline, clashes, step table | result visible without scrolling |
| Recipe | left: scale + ingredients · right: stages | 2.5 → ~1.2 |
| Recipes list | dense 3–4 column grid, family filter chips, whole card is the link | 4.8 → ~1.5 |
| Equipment | read view (name, menu number, cycle bars) in a grid; edit form in a disclosure | 5.4 → ~1.5 |
| Settings | cards in a two-column grid; fields sized to content | 1.5 → 1 |

### Charts

Geometry stops being a fixed 360 units. `ribbon.build()` and the bake timeline take a
target width; the template renders **three renditions** (about 360, 760, 1280 units
wide) and a container query shows the one that fits. Type stays at its designed size
at every width, extra width becomes extra hours per pixel and more tick labels, and
row height stays constant. It remains server-drawn inline SVG with no JS, and live
refresh works unchanged. Label placement gets collision rules (ratio label beside the
curve, stage names inside the bar when they fit, outside when they don't, never across
another bar). The rise chart gets the same treatment.

Cost: the SVG markup is emitted three times (a few KB). The alternative — measuring
in JS and re-requesting — adds a round trip and a flash; I recommend the renditions.

### Jar labels

- The tape carries the **name only**, wrapped to two lines at a word break by the
  template, sized by `clamp()` on container-query units so it follows the jar's
  rendered size, with `<title>` giving the full name on hover/long-press.
- The caption (flour / culture / "control") moves **under the jar** as HTML, where it
  can line-clamp to two lines with the full text as a tooltip.
- The 10- and 11-character cuts go away.

### Tests

Four test files pin facts about `app.css` (`test_layout_css`, `test_ghost_jar`,
`test_jar_cap_color`, `test_settings_units`). Where the facelift renames a selector,
I rewrite the test to pin the same fact against the new rule rather than delete it.

## Creative ideas

Each would be its own commit in Phase 4. Tick the ones you want.

| # | Idea | Why |
|---|---|---|
| 1 | **Chalkboard "Today"** on home: next feed, next alert, bake step in chalk on a slate | the at-a-glance panel gets the bakery character instead of being another card |
| 2 | **Jars show their mood**: a hungry jar's contents slump and its tape gets a red corner; a peaking jar domes | status readable from the artwork, across the kitchen |
| 3 | **Counter mode** for a running bake: one step, huge type, one big button, screen kept awake | floury hands, phone propped on the counter |
| 4 | **Recipe as an index card** with a print stylesheet (recipe + weigh-out on one page) | paper by the scale beats a phone |
| 5 | **Dough composition bar** on a recipe: flour / water / levain / salt as one stacked bar | baker's percentages at a glance, and a quick visual diff between versions |
| 6 | **Head-to-head strip**: the two rye jars on one shared axis, homemade vs control | the experiment is the point of the notebook |
| 7 | **Recipe search-as-you-type** plus family chips (client-side filter) | 36 recipes and growing |
| 8 | **Second shelf** instead of sideways scroll when jars don't fit | keeps the shelf honest on a phone |
| 9 | **Manual light/dark switch** remembered per device | a bright kitchen at night |

## Needs a decision

1. **Bake in progress on home.** `home.py` does not pass bakes to the template today.
   Showing one needs a few read-only lines in that route. It is view code, not
   model/alert logic, but it is outside "templates and CSS". OK to include?
2. **Idea 6** needs the ribbon service to draw two jars on one row. Chart code, so in
   bounds by your ruling; flagging that it is the largest of the ideas.
3. **Bottom tab bar on phone** — a real change of habit. Yes, or keep links on top?
4. **Rise chart**: the notebook has no observations, so I could not audit it with
   real data. I'd add a few made-up observations to the copy only.

## Deferred / needs backend

Nothing yet beyond item 1 above. This section is filled in as phases land.
