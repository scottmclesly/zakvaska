# Changelog

What changed in each release, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the numbers
follow [Semantic Versioning](https://semver.org/).

The section for a version is also its release notes: the release workflow
copies it onto the GitHub Release.

## [1.0.0] - 2026-11-27

The first public release. zakvaska is a lab notebook for sourdough starters
and the bread that comes of them: it runs on your own computer or a
Raspberry Pi, and everything you write in it stays there.

### Two ways to install

- **Desktop app** for macOS (Apple Silicon and Intel) and Windows. It keeps
  running in the system tray when the window is closed, so feeding and bake
  alerts still arrive, as native notifications. The notebook lives in your
  own app-data folder.
- **Docker image** for amd64 and arm64 (a 64-bit Raspberry Pi), published
  to GHCR. `docker compose up -d` with no configuration; the port and time
  zone are optional settings. One script installs or updates it on a Pi.

The desktop installers are not code-signed yet. The README has the one
extra step each system asks for.

### What it does

- **Starter jars**: feedings, rise observations, state changes and
  photos, on a timeline per jar. Two jars on the same flour are drawn
  against each other, which is how to compare a homemade starter with a
  bought one.
- **Feeding alerts** on the wall clock, with snooze, and a plan that keeps
  feeds out of the hours you are asleep or away.
- **Recipes** in baker's percentages, versioned: an edit writes a new
  version and old bakes keep meaning what they meant. A library of 33
  reference recipes, rye and wheat, can be added with one button.
- **Bakes**: plan one against the clock, follow it step by step with
  alerts for each step, the preheat, the folds and the lid, then record how
  it turned out and set two loaves side by side.
- **A West Bend bread maker's programs**, cycle by cycle, for timing a
  machine loaf.
- **Units**: grams, US cups and spoons, or ounces and pounds; Celsius or
  Fahrenheit. Stored in grams and Celsius whatever is shown.
- **Backup**: export everything as one zip (JSON, CSV and the photos) and
  restore it, with a check of the file first and a safety copy of what was
  there.

### New in this release

- A **demo notebook**, offered on an empty shelf: two rye jars with a few
  days of feedings, the recipe library and a finished loaf.
- **Check for a newer version** on the About page and in the desktop app's
  tray menu. It asks GitHub, from your browser, only when you press it.
- **Bakes are a wall of loaves**: each one a card led by its photograph,
  the newest photographed loaf hung larger, and a line that counts them up.
  A loaf not yet photographed gets the drawing of what it was.
- **Recipes are shelves to browse along**: what you have baked first, with
  your own photographs, then a shelf for each family of bread, each
  scrolling sideways. A card leads with its bread: the photo of the best
  loaf you baked from it, or the loaf drawn on a board in the shape it
  really is (a baguette is no longer a boule, and a tin loaf shows its
  crumb), with hydration, time and how often you have made it.
- **The feeding chart says where you are and what comes next**: the
  current time is flagged in red, the curve is thickest when the starter
  is at its best, each planned feed projects a dashed rise forward, and the
  hours a jar sits spent and hungry are drawn rather than left blank.
- **Compare jars on request**: "Add to comparison" on a jar's page, and a
  page that sets the jars you picked head to head on one clock.
- **A calmer header**: the three sections stand centred with the current
  one in the middle, Settings is an icon, and a jar is edited from the jar
  itself.
- A finished bake's day runs the full width under its figures, and
  "Compare with" sits under what went into the loaf.

### Known limits

- The desktop app listens on this computer only. To use the notebook from
  a phone, run it with Docker or from source.
- Phone notifications need the page open over HTTPS; a push to the phone
  is planned.
- 32-bit Raspberry Pi OS is not supported.
